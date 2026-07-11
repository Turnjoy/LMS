from flask import Blueprint, request, jsonify, g, render_template
from flask_login import login_required, current_user
from app.models import Result, TeacherAssignment, User
from app.decorators import role_required
from app import db

results_bp = Blueprint('results', __name__, url_prefix='/results')


@results_bp.route('/dashboard')
@login_required
@role_required('teacher')
def dashboard():
    """Teacher dashboard for viewing and managing results."""
    assignments = TeacherAssignment.query.filter_by(
        tenant_id=g.current_tenant_id,
        teacher_id=current_user.id
    ).all()
    stats = {
        'my_classes': len({assignment.class_id for assignment in assignments}),
        'my_subjects': len({assignment.subject_id for assignment in assignments}),
    }
    return render_template(
        'portal/dashboard.html',
        stats=stats,
        teacher_assignments=assignments
    )


@results_bp.route('/', methods=['POST'])
@login_required
@role_required('teacher')
def submit_grades():
    """
    Submit student grades with teacher authorization check.
    Verifies the teacher is assigned to teach the specific subject/class before saving.
    """
    data = request.get_json()
    
    student_id = data.get('student_id')
    subject_id = data.get('subject_id')
    class_id = data.get('class_id')
    term_id = data.get('term_id')
    ca_score = data.get('ca_score', 0.0)
    exam_score = data.get('exam_score', 0.0)
    remarks = data.get('remarks')
    
    # Verify teacher is assigned to this subject/class/term combination
    assignment = TeacherAssignment.query.filter_by(
        tenant_id=g.current_tenant_id,
        teacher_id=current_user.id,
        class_id=class_id,
        subject_id=subject_id,
        term_id=term_id
    ).first()
    
    if not assignment:
        return jsonify({'error': 'You are not authorized to grade this subject/class'}), 403
    
    # Check if result already exists, update if it does
    result = Result.query.filter_by(
        tenant_id=g.current_tenant_id,
        student_id=student_id,
        subject_id=subject_id,
        class_id=class_id,
        term_id=term_id
    ).first()
    
    if result:
        result.ca_score = ca_score
        result.exam_score = exam_score
        result.remarks = remarks
        result.inputted_by = current_user.id
    else:
        result = Result(
            tenant_id=g.current_tenant_id,
            student_id=student_id,
            subject_id=subject_id,
            class_id=class_id,
            term_id=term_id,
            ca_score=ca_score,
            exam_score=exam_score,
            remarks=remarks,
            inputted_by=current_user.id
        )
        db.session.add(result)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Grades submitted successfully',
        'total_score': result.total_score
    }), 200


@results_bp.route('/<int:result_id>/publish', methods=['POST'])
@login_required
@role_required('teacher')
def publish_result(result_id):
    """Publish a result to make it visible to students."""
    result = Result.query.filter_by(
        id=result_id,
        tenant_id=g.current_tenant_id
    ).first()
    
    if not result:
        return jsonify({'error': 'Result not found'}), 404
    
    # Verify teacher authorization
    assignment = TeacherAssignment.query.filter_by(
        tenant_id=g.current_tenant_id,
        teacher_id=current_user.id,
        class_id=result.class_id,
        subject_id=result.subject_id,
        term_id=result.term_id
    ).first()
    
    if not assignment:
        return jsonify({'error': 'Unauthorized to publish this result'}), 403
    
    result.is_published = True
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Result published successfully'}), 200


@results_bp.route('/student/<int:student_id>')
@login_required
@role_required('teacher', 'student', 'local_admin')
def get_student_results(student_id):
    """Get all results for a specific student."""
    # If student, only allow viewing own results
    if current_user.role == 'student' and current_user.id != student_id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # If teacher, verify they teach at least one subject the student is enrolled in
    if current_user.role == 'teacher':
        has_assignment = TeacherAssignment.query.filter_by(
            tenant_id=g.current_tenant_id,
            teacher_id=current_user.id
        ).first()
        if not has_assignment:
            return jsonify({'error': 'Unauthorized'}), 403
    
    results = Result.query.filter_by(
        tenant_id=g.current_tenant_id,
        student_id=student_id
    )
    if current_user.role == 'student':
        results = results.filter_by(is_published=True)
    results = results.all()
    
    results_data = [{
        'id': r.id,
        'subject_id': r.subject_id,
        'subject_name': r.subject.name if r.subject else None,
        'class_id': r.class_id,
        'class_name': r.class_obj.name if r.class_obj else None,
        'term_id': r.term_id,
        'term_name': r.term.name if r.term else None,
        'ca_score': r.ca_score,
        'exam_score': r.exam_score,
        'total_score': r.total_score,
        'is_published': r.is_published,
        'remarks': r.remarks
    } for r in results]
    
    return jsonify({'results': results_data}), 200
