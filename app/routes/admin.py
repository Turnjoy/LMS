from flask import Blueprint, request, jsonify, g, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import (
    AdmissionApplication,
    ClassSubject,
    PaymentGatewaySetting,
    SchoolSetupPreference,
    StudentTermAccess,
    StudentTermRegistration,
    TenantPublicProfile,
    User,
    Class,
    Subject,
    Term,
    Tenant,
    Parent,
    StudentParent,
    StudentClass,
    TenantAISetting,
    TeacherAssignment,
)
from app.decorators import role_required
from app import db
from sqlalchemy import or_
from datetime import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

PRIMARY_JSS_CORE_SUBJECTS = [
    'Mathematics',
    'English Language',
    'Basic Science and Technology',
]

PRIMARY_JSS_EXTRA_OPTIONS = [
    'Christian Religious Studies (CRS)',
    'Islamic Religious Studies (IRS)',
    'French',
    'Computer Studies/ICT',
    'Agricultural Science',
    'Home Economics',
]

SSS_CORE_SUBJECTS = [
    'Mathematics',
    'English Language',
    'Civic Education',
]

SSS_TRACK_SUBJECTS = {
    'Science': ['Biology', 'Physics', 'Chemistry', 'Further Mathematics'],
    'Commercial': ['Economics', 'Financial Accounting', 'Commerce'],
    'Humanities': ['Economics', 'Government', 'Literature-in-English'],
}

SSS_EXTRA_ELECTIVES = [
    'Geography',
    'Technical Drawing',
    'Marketing',
    'Computer Studies',
    'Agricultural Science',
    'Dyeing & Bleaching',
    'Data Processing',
    'Visual Art',
    'Insurance',
]


def _parse_list(raw_value):
    return [item.strip().upper() for item in (raw_value or '').replace(',', '\n').splitlines() if item.strip()]


def _generate_class_names(sections, arms, sss_tracks):
    generated = []
    arms = arms or ['A']

    if 'kg' in sections:
        for level in range(1, 4):
            generated.extend([f'KG {level}{arm}' for arm in arms])

    if 'nursery' in sections:
        for level in range(1, 4):
            generated.extend([f'Nursery {level}{arm}' for arm in arms])

    if 'primary' in sections:
        for level in range(1, 7):
            generated.extend([f'Primary {level}{arm}' for arm in arms])

    if 'jss' in sections:
        for level in range(1, 4):
            generated.extend([f'JSS {level}{arm}' for arm in arms])

    if 'sss' in sections:
        tracks = sss_tracks or ['Science', 'Humanities', 'Commercial']
        for level in range(1, 4):
            for track in tracks:
                generated.extend([f'SSS {level} {track} {arm}' for arm in arms])

    return generated


def _get_or_create_subject(name):
    subject = Subject.query.filter_by(
        tenant_id=g.current_tenant_id,
        name=name
    ).first()
    if subject:
        return subject, False

    subject = Subject(tenant_id=g.current_tenant_id, name=name)
    db.session.add(subject)
    db.session.flush()
    return subject, True


def _get_or_create_class_subject(class_id, subject_id, is_required=True):
    class_subject = ClassSubject.query.filter_by(
        tenant_id=g.current_tenant_id,
        class_id=class_id,
        subject_id=subject_id
    ).first()
    if class_subject:
        if is_required and not class_subject.is_required:
            class_subject.is_required = True
        return class_subject, False

    class_subject = ClassSubject(
        tenant_id=g.current_tenant_id,
        class_id=class_id,
        subject_id=subject_id,
        is_required=is_required
    )
    db.session.add(class_subject)
    return class_subject, True


def _class_section(class_name):
    normalized = (class_name or '').strip().lower()
    if normalized.startswith(('primary', 'jss')):
        return 'primary_jss'
    if normalized.startswith('sss'):
        return 'sss'
    return None


def _sss_track_for_class(class_name):
    normalized = (class_name or '').lower()
    for track in SSS_TRACK_SUBJECTS:
        if track.lower() in normalized:
            return track
    return None


def _subjects_for_generated_class(class_name, primary_jss_extras, sss_extra_electives):
    section = _class_section(class_name)
    if section == 'primary_jss':
        return {
            'required': PRIMARY_JSS_CORE_SUBJECTS,
            'optional': primary_jss_extras,
        }

    if section == 'sss':
        track = _sss_track_for_class(class_name) or 'Science'
        return {
            'required': SSS_CORE_SUBJECTS + SSS_TRACK_SUBJECTS.get(track, []),
            'optional': sss_extra_electives,
        }

    return {'required': [], 'optional': []}


def _apply_curriculum_matrix(classes, primary_jss_extras, sss_extra_electives):
    created_subjects = 0
    created_class_subjects = 0

    for class_obj in classes:
        matrix = _subjects_for_generated_class(
            class_obj.name,
            primary_jss_extras,
            sss_extra_electives
        )

        for subject_name in matrix['required']:
            subject, created = _get_or_create_subject(subject_name)
            created_subjects += int(created)
            _, linked = _get_or_create_class_subject(class_obj.id, subject.id, is_required=True)
            created_class_subjects += int(linked)

        for subject_name in matrix['optional']:
            subject, created = _get_or_create_subject(subject_name)
            created_subjects += int(created)
            _, linked = _get_or_create_class_subject(class_obj.id, subject.id, is_required=False)
            created_class_subjects += int(linked)

    return created_subjects, created_class_subjects


@admin_bp.route('/dashboard')
@login_required
@role_required('admin')
def dashboard():
    """Admin dashboard for school management."""
    stats = {
        'users': User.query.filter_by(tenant_id=g.current_tenant_id).count(),
        'classes': Class.query.filter_by(tenant_id=g.current_tenant_id).count(),
        'subjects': Subject.query.filter_by(tenant_id=g.current_tenant_id).count(),
        'active_terms': Term.query.filter_by(tenant_id=g.current_tenant_id, is_active=True).count(),
        'pending_admissions': AdmissionApplication.query.filter_by(tenant_id=g.current_tenant_id, status='pending').count(),
    }
    return render_template('portal/dashboard.html', stats=stats)


def _split_setup_items(raw_value):
    """Parse comma/newline separated setup values into unique names."""
    if not raw_value:
        return []

    normalized = raw_value.replace(',', '\n')
    seen = set()
    items = []

    for item in normalized.splitlines():
        name = item.strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            items.append(name)

    return items


def _parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, '%Y-%m-%d').date()


@admin_bp.route('/setup', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def setup_school():
    """Configure tenant profile, classes, subjects, term, and AI settings."""
    tenant = Tenant.query.get(g.current_tenant_id)
    if not tenant:
        flash('School profile not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    ai_settings = TenantAISetting.query.filter_by(tenant_id=tenant.id).first()
    if not ai_settings:
        ai_settings = TenantAISetting(tenant_id=tenant.id)
        db.session.add(ai_settings)
        db.session.commit()

    public_profile = TenantPublicProfile.query.filter_by(tenant_id=tenant.id).first()
    if not public_profile:
        public_profile = TenantPublicProfile(
            tenant_id=tenant.id,
            headline='Welcome to Demo High School',
            about='Demo High School is committed to academic excellence, discipline, creativity, and digital learning for every child.',
            admission_message='Apply for admission and our team will review your application.'
        )
        db.session.add(public_profile)
        db.session.commit()

    payment_settings = PaymentGatewaySetting.query.filter_by(tenant_id=tenant.id).first()
    if not payment_settings:
        payment_settings = PaymentGatewaySetting(
            tenant_id=tenant.id,
            payment_instructions='Pay school fees through the approved school account, then contact the bursary for confirmation.'
        )
        db.session.add(payment_settings)
        db.session.commit()

    if request.method == 'POST':
        custom_domain = request.form.get('custom_domain', '').strip().lower()
        if custom_domain.startswith('www.'):
            custom_domain = custom_domain[4:]
        tenant.custom_domain = custom_domain or None
        if tenant.custom_domain:
            tenant.name = tenant.custom_domain
        tenant.logo_url = request.form.get('logo_url') or None
        tenant.primary_color = request.form.get('primary_color') or tenant.primary_color
        tenant.secondary_color = request.form.get('secondary_color') or tenant.secondary_color

        public_profile.headline = request.form.get('headline') or public_profile.headline
        public_profile.about = request.form.get('about') or None
        public_profile.admission_message = request.form.get('admission_message') or None
        public_profile.admission_open = request.form.get('admission_open') == 'on'

        created_classes = 0
        for class_name in _split_setup_items(request.form.get('classes')):
            exists = Class.query.filter_by(tenant_id=tenant.id, name=class_name).first()
            if not exists:
                db.session.add(Class(tenant_id=tenant.id, name=class_name))
                created_classes += 1

        created_subjects = 0
        for subject_name in _split_setup_items(request.form.get('subjects')):
            exists = Subject.query.filter_by(tenant_id=tenant.id, name=subject_name).first()
            if not exists:
                db.session.add(Subject(tenant_id=tenant.id, name=subject_name))
                created_subjects += 1

        term_name = request.form.get('term_name', '').strip()
        session = request.form.get('session', '').strip()
        if term_name and session:
            existing_term = Term.query.filter_by(
                tenant_id=tenant.id,
                name=term_name,
                session=session
            ).first()
            if not existing_term:
                db.session.add(Term(
                    tenant_id=tenant.id,
                    name=term_name,
                    session=session,
                    start_date=_parse_date(request.form.get('start_date')),
                    end_date=_parse_date(request.form.get('end_date')),
                    is_active=request.form.get('is_active_term') == 'on'
                ))

        ai_settings.provider = request.form.get('ai_provider') or 'openai'
        ai_settings.model_name = request.form.get('ai_model') or 'gpt-4o-mini'
        ai_settings.assistant_name = request.form.get('assistant_name') or 'School AI Assistant'
        ai_settings.system_prompt = request.form.get('system_prompt') or None
        ai_settings.enabled_for_teachers = request.form.get('enabled_for_teachers') == 'on'
        ai_settings.enabled_for_students = request.form.get('enabled_for_students') == 'on'

        payment_settings.provider = request.form.get('payment_provider') or 'manual'
        payment_settings.public_key = request.form.get('payment_public_key') or None
        payment_settings.secret_key = request.form.get('payment_secret_key') or None
        payment_settings.currency = request.form.get('payment_currency') or 'NGN'
        payment_settings.payment_instructions = request.form.get('payment_instructions') or None
        payment_settings.require_payment_for_portal = request.form.get('require_payment_for_portal') == 'on'

        db.session.commit()
        flash(f'School setup saved. Added {created_classes} classes and {created_subjects} subjects.', 'success')
        return redirect(url_for('admin.setup_school'))

    classes = Class.query.filter_by(tenant_id=tenant.id).order_by(Class.name).all()
    subjects = Subject.query.filter_by(tenant_id=tenant.id).order_by(Subject.name).all()
    terms = Term.query.filter_by(tenant_id=tenant.id).order_by(Term.created_at.desc()).all()

    return render_template(
        'portal/admin_setup.html',
        classes=classes,
        subjects=subjects,
        terms=terms,
        ai_settings=ai_settings
        ,
        public_profile=public_profile,
        payment_settings=payment_settings
    )


@admin_bp.route('/setup-wizard', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def setup_wizard():
    """Guided setup for class structure after domain linking."""
    preference = SchoolSetupPreference.query.filter_by(tenant_id=g.current_tenant_id).first()
    if not preference:
        preference = SchoolSetupPreference(tenant_id=g.current_tenant_id)
        db.session.add(preference)
        db.session.commit()

    if request.method == 'POST':
        setup_mode = request.form.get('setup_mode') or 'hybrid'
        school_type = request.form.get('school_type') or 'combined'
        sections = request.form.getlist('sections')
        arms = _parse_list(request.form.get('arms')) or ['A']
        sss_tracks = request.form.getlist('sss_tracks') or ['Science', 'Humanities', 'Commercial']
        primary_jss_extras = request.form.getlist('primary_jss_extras')
        sss_extra_electives = request.form.getlist('sss_extra_electives')

        preference.setup_mode = setup_mode
        preference.school_type = school_type
        preference.sections = sections
        preference.arms = arms
        preference.sss_tracks = sss_tracks

        created_classes = 0
        generated_classes = []
        for class_name in _generate_class_names(sections, arms, sss_tracks):
            exists = Class.query.filter_by(tenant_id=g.current_tenant_id, name=class_name).first()
            if not exists:
                exists = Class(tenant_id=g.current_tenant_id, name=class_name)
                db.session.add(exists)
                db.session.flush()
                created_classes += 1
            generated_classes.append(exists)

        created_subjects, created_class_subjects = _apply_curriculum_matrix(
            generated_classes,
            primary_jss_extras,
            sss_extra_electives
        )

        db.session.commit()
        flash(
            'Setup saved. Added '
            f'{created_classes} classes, {created_subjects} subjects, '
            f'and {created_class_subjects} class-subject links.',
            'success'
        )
        return redirect(url_for('admin.class_subjects'))

    return render_template(
        'portal/admin_setup_wizard.html',
        preference=preference,
        primary_jss_core_subjects=PRIMARY_JSS_CORE_SUBJECTS,
        primary_jss_extra_options=PRIMARY_JSS_EXTRA_OPTIONS,
        sss_core_subjects=SSS_CORE_SUBJECTS,
        sss_track_subjects=SSS_TRACK_SUBJECTS,
        sss_extra_electives=SSS_EXTRA_ELECTIVES
    )


@admin_bp.route('/class-subjects', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def class_subjects():
    """Select subjects offered by each class."""
    classes = Class.query.filter_by(tenant_id=g.current_tenant_id).order_by(Class.name).all()
    subjects = Subject.query.filter_by(tenant_id=g.current_tenant_id).order_by(Subject.name).all()

    if request.method == 'POST':
        ClassSubject.query.filter_by(tenant_id=g.current_tenant_id).delete()

        for class_obj in classes:
            selected_subjects = request.form.getlist(f'class_{class_obj.id}_subjects')
            required_subjects = request.form.getlist(f'class_{class_obj.id}_required')

            for subject_id in selected_subjects:
                db.session.add(ClassSubject(
                    tenant_id=g.current_tenant_id,
                    class_id=class_obj.id,
                    subject_id=int(subject_id),
                    is_required=subject_id in required_subjects
                ))

        db.session.commit()
        flash('Class subject setup saved.', 'success')
        return redirect(url_for('admin.class_subjects'))

    existing = ClassSubject.query.filter_by(tenant_id=g.current_tenant_id).all()
    selected_map = {}
    required_map = {}
    for item in existing:
        selected_map.setdefault(item.class_id, set()).add(item.subject_id)
        if item.is_required:
            required_map.setdefault(item.class_id, set()).add(item.subject_id)

    return render_template(
        'portal/admin_class_subjects.html',
        classes=classes,
        subjects=subjects,
        selected_map=selected_map,
        required_map=required_map
    )


@admin_bp.route('/teacher-assignments', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def teacher_assignments():
    """Assign teachers to configured subject + class arm combinations."""
    active_term = Term.query.filter_by(tenant_id=g.current_tenant_id, is_active=True).first()
    teachers = User.query.filter_by(
        tenant_id=g.current_tenant_id,
        role='teacher'
    ).order_by(User.name).all()
    classes = Class.query.filter_by(tenant_id=g.current_tenant_id).order_by(Class.name).all()
    class_subjects = ClassSubject.query.filter_by(tenant_id=g.current_tenant_id).all()
    configured_subject_ids = {item.subject_id for item in class_subjects}
    subjects = Subject.query.filter(
        Subject.tenant_id == g.current_tenant_id,
        Subject.id.in_(configured_subject_ids or [0])
    ).order_by(Subject.name).all()

    if request.method == 'POST':
        teacher_id = request.form.get('teacher_id')
        class_id = request.form.get('class_id')
        subject_id = request.form.get('subject_id')
        term_id = request.form.get('term_id') or (active_term.id if active_term else None)

        if not all([teacher_id, class_id, subject_id, term_id]):
            flash('Teacher, class, subject, and term are required.', 'error')
            return redirect(url_for('admin.teacher_assignments'))

        teacher = User.query.filter_by(
            id=teacher_id,
            tenant_id=g.current_tenant_id,
            role='teacher'
        ).first()
        class_obj = Class.query.filter_by(id=class_id, tenant_id=g.current_tenant_id).first()
        subject = Subject.query.filter_by(id=subject_id, tenant_id=g.current_tenant_id).first()
        term = Term.query.filter_by(id=term_id, tenant_id=g.current_tenant_id).first()
        class_subject = ClassSubject.query.filter_by(
            tenant_id=g.current_tenant_id,
            class_id=class_id,
            subject_id=subject_id
        ).first()

        if not all([teacher, class_obj, subject, term]):
            flash('Invalid teacher, class, subject, or term for this school.', 'error')
            return redirect(url_for('admin.teacher_assignments'))

        if not class_subject:
            flash('That subject is not configured for the selected class arm.', 'error')
            return redirect(url_for('admin.teacher_assignments'))

        existing = TeacherAssignment.query.filter_by(
            tenant_id=g.current_tenant_id,
            teacher_id=teacher.id,
            class_id=class_obj.id,
            subject_id=subject.id,
            term_id=term.id
        ).first()

        if existing:
            flash('This teacher assignment already exists.', 'error')
            return redirect(url_for('admin.teacher_assignments'))

        db.session.add(TeacherAssignment(
            tenant_id=g.current_tenant_id,
            teacher_id=teacher.id,
            class_id=class_obj.id,
            subject_id=subject.id,
            term_id=term.id
        ))
        db.session.commit()
        flash(f'{teacher.name} assigned to {subject.name} - {class_obj.name}.', 'success')
        return redirect(url_for('admin.teacher_assignments'))

    terms = Term.query.filter_by(tenant_id=g.current_tenant_id).order_by(Term.created_at.desc()).all()
    assignments = TeacherAssignment.query.filter_by(
        tenant_id=g.current_tenant_id
    ).order_by(TeacherAssignment.created_at.desc()).all()
    class_subject_map = {}
    for item in class_subjects:
        class_subject_map.setdefault(item.class_id, []).append(item.subject_id)

    return render_template(
        'portal/admin_teacher_assignments.html',
        active_term=active_term,
        terms=terms,
        teachers=teachers,
        classes=classes,
        subjects=subjects,
        assignments=assignments,
        class_subject_map=class_subject_map
    )


@admin_bp.route('/admissions')
@login_required
@role_required('admin')
def admissions():
    """Review admission applications for this school."""
    status = request.args.get('status', 'pending')
    query = AdmissionApplication.query.filter_by(tenant_id=g.current_tenant_id)
    if status != 'all':
        query = query.filter_by(status=status)

    applications = query.order_by(AdmissionApplication.created_at.desc()).all()
    classes = Class.query.filter_by(tenant_id=g.current_tenant_id).order_by(Class.name).all()
    active_term = Term.query.filter_by(tenant_id=g.current_tenant_id, is_active=True).first()

    return render_template(
        'portal/admin_admissions.html',
        applications=applications,
        classes=classes,
        active_term=active_term,
        status=status
    )


@admin_bp.route('/admissions/<int:application_id>/<action>', methods=['POST'])
@login_required
@role_required('admin')
def review_admission(application_id, action):
    """Accept or reject an admission application."""
    application = AdmissionApplication.query.filter_by(
        id=application_id,
        tenant_id=g.current_tenant_id
    ).first_or_404()

    if application.status != 'pending':
        flash('This application has already been reviewed.', 'error')
        return redirect(url_for('admin.admissions'))

    if action == 'reject':
        application.status = 'rejected'
        application.admin_note = request.form.get('admin_note') or None
        application.reviewed_at = datetime.utcnow()
        db.session.commit()
        flash('Admission application rejected.', 'success')
        return redirect(url_for('admin.admissions'))

    if action != 'accept':
        flash('Invalid review action.', 'error')
        return redirect(url_for('admin.admissions'))

    email = request.form.get('student_email') or application.parent_email
    password = request.form.get('temporary_password') or 'student123'
    class_id = request.form.get('class_id') or application.requested_class_id
    term_id = request.form.get('term_id')
    amount_due = float(request.form.get('amount_due') or 0)

    existing = User.query.filter_by(
        tenant_id=g.current_tenant_id,
        email=email
    ).first()
    if existing:
        flash('A user with that email already exists for this school.', 'error')
        return redirect(url_for('admin.admissions'))

    student = User(
        tenant_id=g.current_tenant_id,
        name=application.applicant_name,
        email=email,
        role='student'
    )
    student.set_password(password)
    db.session.add(student)
    db.session.flush()

    if class_id and term_id:
        enrollment = StudentClass(
            tenant_id=g.current_tenant_id,
            student_id=student.id,
            class_id=class_id,
            term_id=term_id
        )
        db.session.add(enrollment)

    if term_id:
        access = StudentTermAccess(
            tenant_id=g.current_tenant_id,
            student_id=student.id,
            term_id=term_id,
            amount_due=amount_due,
            amount_paid=0,
            is_paid=False,
            portal_unlocked=False
        )
        db.session.add(access)

    application.status = 'accepted'
    application.created_student_id = student.id
    application.admin_note = request.form.get('admin_note') or None
    application.reviewed_at = datetime.utcnow()

    db.session.commit()
    flash(f'Admission accepted. Student login is {email} with temporary password {password}.', 'success')
    return redirect(url_for('admin.admissions'))


@admin_bp.route('/payments')
@login_required
@role_required('admin')
def payments():
    """Manage student payment status and portal access."""
    active_term = Term.query.filter_by(tenant_id=g.current_tenant_id, is_active=True).first()
    students = User.query.filter_by(tenant_id=g.current_tenant_id, role='student').order_by(User.name).all()
    access_records = []

    if active_term:
        for student in students:
            access = StudentTermAccess.query.filter_by(
                tenant_id=g.current_tenant_id,
                student_id=student.id,
                term_id=active_term.id
            ).first()
            if not access:
                access = StudentTermAccess(
                    tenant_id=g.current_tenant_id,
                    student_id=student.id,
                    term_id=active_term.id
                )
                db.session.add(access)
        db.session.commit()
        access_records = StudentTermAccess.query.filter_by(
            tenant_id=g.current_tenant_id,
            term_id=active_term.id
        ).all()

    return render_template('portal/admin_payments.html', active_term=active_term, access_records=access_records)


@admin_bp.route('/payments/<int:access_id>/mark-paid', methods=['POST'])
@login_required
@role_required('admin')
def mark_payment_paid(access_id):
    access = StudentTermAccess.query.filter_by(
        id=access_id,
        tenant_id=g.current_tenant_id
    ).first_or_404()

    amount_paid = float(request.form.get('amount_paid') or access.amount_due or 0)
    access.amount_paid = amount_paid
    access.payment_reference = request.form.get('payment_reference') or None
    access.is_paid = True
    access.portal_unlocked = True
    db.session.commit()

    flash('Payment confirmed and portal unlocked.', 'success')
    return redirect(url_for('admin.payments'))


@admin_bp.route('/announcement', methods=['POST'])
@login_required
@role_required('admin')
def send_announcement():
    """
    Broadcast an announcement email to parents.
    Target can be 'all' for all parents or 'class' for specific class parents.
    """
    data = request.get_json()
    
    subject = data.get('subject')
    message = data.get('message')
    target = data.get('target', 'all')  # 'all' or 'class'
    class_id = data.get('class_id')
    
    if not subject or not message:
        return jsonify({'error': 'Subject and message are required'}), 400
    
    # Get current tenant
    tenant = Tenant.query.get(g.current_tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    
    # Build email list based on target
    email_list = []
    
    if target == 'all':
        # Get all parent emails for this tenant
        parents = Parent.query.filter_by(tenant_id=g.current_tenant_id).all()
        email_list = [p.user.email for p in parents if p.user and p.user.email]
    
    elif target == 'class':
        if not class_id:
            return jsonify({'error': 'class_id required for class target'}), 400
        
        # JOIN query to get parents of students in a specific class
        # Parent -> StudentParent -> Student (User) -> StudentClass -> Class
        from app.models import User as StudentUser
        
        query = db.session.query(Parent).join(
            StudentParent, Parent.id == StudentParent.parent_id
        ).join(
            StudentUser, StudentParent.student_id == StudentUser.id
        ).join(
            StudentClass, StudentUser.id == StudentClass.student_id
        ).filter(
            Parent.tenant_id == g.current_tenant_id,
            StudentClass.class_id == class_id,
            StudentClass.tenant_id == g.current_tenant_id
        ).distinct()
        
        parents = query.all()
        email_list = [p.user.email for p in parents if p.user and p.user.email]
    
    else:
        return jsonify({'error': 'Invalid target. Use "all" or "class"'}), 400
    
    # In production, this would integrate with an email service like SendGrid, Mailgun, etc.
    # For now, we'll simulate the email sending
    # TODO: Integrate with actual email service
    
    return jsonify({
        'success': True,
        'message': f'Announcement queued for {len(email_list)} recipients',
        'recipient_count': len(email_list),
        'recipients': email_list
    }), 200


@admin_bp.route('/users', methods=['POST'])
@login_required
@role_required('admin')
def create_user():
    """Create a new user (admin, teacher, student, or attendant)."""
    data = request.get_json()
    
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    role = data.get('role')
    
    if not all([name, email, password, role]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if role not in ['admin', 'teacher', 'student', 'attendant', 'parent']:
        return jsonify({'error': 'Invalid role'}), 400
    
    # Check if email already exists for this tenant
    existing = User.query.filter_by(
        tenant_id=g.current_tenant_id,
        email=email
    ).first()
    
    if existing:
        return jsonify({'error': 'Email already exists'}), 400
    
    user = User(
        tenant_id=g.current_tenant_id,
        name=name,
        email=email,
        role=role
    )
    user.set_password(password)
    
    db.session.add(user)
    db.session.flush()

    if role == 'parent':
        parent = Parent(
            tenant_id=g.current_tenant_id,
            user_id=user.id,
            phone=data.get('phone'),
            address=data.get('address')
        )
        db.session.add(parent)

    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'User created successfully',
        'user_id': user.id
    }), 201


@admin_bp.route('/classes', methods=['POST'])
@login_required
@role_required('admin')
def create_class():
    """Create a new class."""
    data = request.get_json()
    
    name = data.get('name')
    
    if not name:
        return jsonify({'error': 'Class name is required'}), 400
    
    class_obj = Class(
        tenant_id=g.current_tenant_id,
        name=name
    )
    
    db.session.add(class_obj)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Class created successfully',
        'class_id': class_obj.id
    }), 201


@admin_bp.route('/subjects', methods=['POST'])
@login_required
@role_required('admin')
def create_subject():
    """Create a new subject."""
    data = request.get_json()
    
    name = data.get('name')
    
    if not name:
        return jsonify({'error': 'Subject name is required'}), 400
    
    subject = Subject(
        tenant_id=g.current_tenant_id,
        name=name
    )
    
    db.session.add(subject)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Subject created successfully',
        'subject_id': subject.id
    }), 201


@admin_bp.route('/terms', methods=['POST'])
@login_required
@role_required('admin')
def create_term():
    """Create a new academic term."""
    data = request.get_json()
    
    name = data.get('name')
    session = data.get('session')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    
    if not all([name, session]):
        return jsonify({'error': 'Term name and session are required'}), 400
    
    from datetime import datetime
    
    term = Term(
        tenant_id=g.current_tenant_id,
        name=name,
        session=session,
        start_date=datetime.fromisoformat(start_date) if start_date else None,
        end_date=datetime.fromisoformat(end_date) if end_date else None
    )
    
    db.session.add(term)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Term created successfully',
        'term_id': term.id
    }), 201


@admin_bp.route('/assign-teacher', methods=['POST'])
@login_required
@role_required('admin')
def assign_teacher():
    """Assign a teacher to a class and subject for a specific term."""
    data = request.get_json()
    
    teacher_id = data.get('teacher_id')
    class_id = data.get('class_id')
    subject_id = data.get('subject_id')
    term_id = data.get('term_id')
    
    if not all([teacher_id, class_id, subject_id, term_id]):
        return jsonify({'error': 'All fields are required'}), 400

    teacher = User.query.filter_by(
        id=teacher_id,
        tenant_id=g.current_tenant_id,
        role='teacher'
    ).first()
    class_obj = Class.query.filter_by(id=class_id, tenant_id=g.current_tenant_id).first()
    subject = Subject.query.filter_by(id=subject_id, tenant_id=g.current_tenant_id).first()
    term = Term.query.filter_by(id=term_id, tenant_id=g.current_tenant_id).first()

    if not all([teacher, class_obj, subject, term]):
        return jsonify({'error': 'Invalid teacher, class, subject, or term for this tenant'}), 400

    class_subject = ClassSubject.query.filter_by(
        tenant_id=g.current_tenant_id,
        class_id=class_id,
        subject_id=subject_id
    ).first()
    if not class_subject:
        return jsonify({'error': 'Subject is not configured for this class arm'}), 400
    
    # Check if assignment already exists
    existing = TeacherAssignment.query.filter_by(
        tenant_id=g.current_tenant_id,
        teacher_id=teacher.id,
        class_id=class_obj.id,
        subject_id=subject.id,
        term_id=term.id
    ).first()
    
    if existing:
        return jsonify({'error': 'Assignment already exists'}), 400
    
    assignment = TeacherAssignment(
        tenant_id=g.current_tenant_id,
        teacher_id=teacher.id,
        class_id=class_obj.id,
        subject_id=subject.id,
        term_id=term.id
    )
    
    db.session.add(assignment)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Teacher assigned successfully'
    }), 201


@admin_bp.route('/enroll-student', methods=['POST'])
@login_required
@role_required('admin')
def enroll_student():
    """Enroll a student in a class for a specific term."""
    data = request.get_json()
    
    student_id = data.get('student_id')
    class_id = data.get('class_id')
    term_id = data.get('term_id')
    
    if not all([student_id, class_id, term_id]):
        return jsonify({'error': 'All fields are required'}), 400
    
    # Check if enrollment already exists
    existing = StudentClass.query.filter_by(
        tenant_id=g.current_tenant_id,
        student_id=student_id,
        class_id=class_id,
        term_id=term_id
    ).first()
    
    if existing:
        return jsonify({'error': 'Student already enrolled in this class for this term'}), 400
    
    enrollment = StudentClass(
        tenant_id=g.current_tenant_id,
        student_id=student_id,
        class_id=class_id,
        term_id=term_id
    )
    
    db.session.add(enrollment)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Student enrolled successfully'
    }), 201
