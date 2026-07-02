from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import and_, func

from app import db
from app.decorators import role_required
from app.models import (
    Class,
    GlobalSubjectRepository,
    StudentClass,
    StudentSubjectRegistration,
    TenantSubject,
    Term,
    User,
)

api_subjects_bp = Blueprint('api_subjects', __name__, url_prefix='/api')


def _tenant_id():
    return current_user.tenant_id


@api_subjects_bp.route('/admin/global-subjects', methods=['GET'])
@login_required
@role_required('admin')
def get_global_subjects():
    subjects = GlobalSubjectRepository.query.order_by(
        GlobalSubjectRepository.category,
        GlobalSubjectRepository.name
    ).all()

    return jsonify({
        'success': True,
        'subjects': [
            {
                'id': subject.id,
                'name': subject.name,
                'category': subject.category,
            }
            for subject in subjects
        ]
    }), 200


@api_subjects_bp.route('/admin/assign-subject', methods=['POST'])
@login_required
@role_required('admin')
def assign_subject():
    data = request.get_json(silent=True) or {}
    global_subject_id = data.get('global_subject_id')
    class_level_id = data.get('class_level_id')
    assigned_teacher_id = data.get('assigned_teacher_id')

    if not global_subject_id or not class_level_id:
        return jsonify({'error': 'global_subject_id and class_level_id are required'}), 400

    try:
        global_subject = GlobalSubjectRepository.query.get(global_subject_id)
        if not global_subject:
            return jsonify({'error': 'Global subject not found'}), 404

        class_level = Class.query.filter_by(
            id=class_level_id,
            tenant_id=_tenant_id()
        ).first()
        if not class_level:
            return jsonify({'error': 'Class level not found for this tenant'}), 404

        teacher = None
        if assigned_teacher_id:
            teacher = User.query.filter_by(
                id=assigned_teacher_id,
                tenant_id=_tenant_id(),
                role='teacher'
            ).first()
            if not teacher:
                return jsonify({'error': 'Assigned teacher not found for this tenant'}), 404

        tenant_subject = TenantSubject.query.filter_by(
            tenant_id=_tenant_id(),
            global_subject_id=global_subject.id,
            class_level_id=class_level.id
        ).first()

        if tenant_subject:
            tenant_subject.assigned_teacher_id = teacher.id if teacher else None
            status_code = 200
            message = 'Subject assignment updated'
        else:
            tenant_subject = TenantSubject(
                tenant_id=_tenant_id(),
                global_subject_id=global_subject.id,
                class_level_id=class_level.id,
                assigned_teacher_id=teacher.id if teacher else None
            )
            db.session.add(tenant_subject)
            status_code = 201
            message = 'Subject assigned successfully'

        db.session.commit()
        return jsonify({
            'success': True,
            'message': message,
            'tenant_subject_id': tenant_subject.id,
        }), status_code
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': 'Unable to assign subject', 'details': str(exc)}), 500


@api_subjects_bp.route('/student/available-subjects', methods=['GET'])
@login_required
@role_required('student')
def get_available_subjects():
    active_term = Term.query.filter_by(tenant_id=_tenant_id(), is_active=True).first()
    enrollment_query = StudentClass.query.filter_by(
        tenant_id=_tenant_id(),
        student_id=current_user.id
    )
    if active_term:
        enrollment_query = enrollment_query.filter_by(term_id=active_term.id)

    enrollment = enrollment_query.order_by(StudentClass.created_at.desc()).first()
    if not enrollment:
        return jsonify({'error': 'Student is not enrolled in a class for the current term'}), 404

    rows = db.session.query(
        TenantSubject,
        GlobalSubjectRepository,
        func.count(StudentSubjectRegistration.id).label('total_registered_students')
    ).join(
        GlobalSubjectRepository,
        TenantSubject.global_subject_id == GlobalSubjectRepository.id
    ).outerjoin(
        StudentSubjectRegistration,
        and_(
            StudentSubjectRegistration.tenant_subject_id == TenantSubject.id,
            StudentSubjectRegistration.tenant_id == _tenant_id()
        )
    ).filter(
        TenantSubject.tenant_id == _tenant_id(),
        TenantSubject.class_level_id == enrollment.class_id
    ).group_by(
        TenantSubject.id,
        GlobalSubjectRepository.id
    ).order_by(
        GlobalSubjectRepository.category,
        GlobalSubjectRepository.name
    ).all()

    return jsonify({
        'success': True,
        'class_level_id': enrollment.class_id,
        'subjects': [
            {
                'tenant_subject_id': tenant_subject.id,
                'global_subject_id': global_subject.id,
                'name': global_subject.name,
                'category': global_subject.category,
                'assigned_teacher_id': tenant_subject.assigned_teacher_id,
                'total_registered_students': total_registered_students,
            }
            for tenant_subject, global_subject, total_registered_students in rows
        ]
    }), 200


@api_subjects_bp.route('/student/register-subjects', methods=['POST'])
@login_required
@role_required('student')
def register_subjects():
    data = request.get_json(silent=True) or {}
    subject_ids = data.get('tenant_subject_ids') or data.get('subject_ids') or []

    if not isinstance(subject_ids, list) or not subject_ids:
        return jsonify({'error': 'tenant_subject_ids must be a non-empty array'}), 400

    try:
        tenant_subjects = TenantSubject.query.filter(
            TenantSubject.tenant_id == _tenant_id(),
            TenantSubject.id.in_(subject_ids)
        ).all()

        if len(tenant_subjects) != len(set(subject_ids)):
            return jsonify({'error': 'One or more selected subjects do not belong to this tenant'}), 400

        class_level_ids = {subject.class_level_id for subject in tenant_subjects}
        active_term = Term.query.filter_by(tenant_id=_tenant_id(), is_active=True).first()
        enrollment_query = StudentClass.query.filter_by(
            tenant_id=_tenant_id(),
            student_id=current_user.id
        )
        if active_term:
            enrollment_query = enrollment_query.filter_by(term_id=active_term.id)
        enrollment = enrollment_query.order_by(StudentClass.created_at.desc()).first()

        if not enrollment or class_level_ids != {enrollment.class_id}:
            return jsonify({'error': 'Selected subjects must match the student current class level'}), 400

        StudentSubjectRegistration.query.filter_by(
            tenant_id=_tenant_id(),
            student_id=current_user.id
        ).delete()

        for tenant_subject in tenant_subjects:
            db.session.add(StudentSubjectRegistration(
                tenant_id=_tenant_id(),
                student_id=current_user.id,
                tenant_subject_id=tenant_subject.id
            ))

        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'Subject registration submitted',
            'registered_count': len(tenant_subjects),
        }), 201
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': 'Unable to register subjects', 'details': str(exc)}), 500
