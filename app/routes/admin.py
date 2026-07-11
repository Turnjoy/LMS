from datetime import datetime
from flask import Blueprint, request, jsonify, g, render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app.models import (
    AdmissionApplication,
    ClassSubject,
    FeeCategory,
    FeeInstallmentMilestone,
    FeeInstallmentPlan,
    PaymentGatewaySetting,
    PaymentTransaction,
    SchoolSetupPreference,
    Assignment,
    AssignmentSubmission,
    ClassArm,
    ClassLevel,
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
from app.auth_utils import ensure_custom_id, generate_temporary_password
from sqlalchemy import or_

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

LOCAL_ADMIN_ROLES = ('school_admin', 'admin', 'primary_admin', 'secondary_admin')


@admin_bp.before_request
def require_tenant_context():
    if not getattr(g, 'current_tenant', None):
        abort(404)
    if current_user.is_authenticated and current_user.tenant_id != g.current_tenant_id:
        abort(403)

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
    items = []
    for item in (raw_value or '').replace(',', '\n').splitlines():
        value = item.strip()
        if len(value) == 1 and value.isalpha():
            value = value.upper()
        if value and value.lower() not in [existing.lower() for existing in items]:
            items.append(value)
    return items


def _base_class_levels_for_type(school_type):
    levels = []
    if school_type in ('primary', 'both', 'combined'):
        levels.extend([('Primary 1', 'primary'), ('Primary 2', 'primary'), ('Primary 3', 'primary')])
        levels.extend([('Primary 4', 'primary'), ('Primary 5', 'primary'), ('Primary 6', 'primary')])
    if school_type in ('secondary', 'both', 'combined'):
        levels.extend([('JSS 1', 'secondary'), ('JSS 2', 'secondary'), ('JSS 3', 'secondary')])
        levels.extend([('SSS 1', 'secondary'), ('SSS 2', 'secondary'), ('SSS 3', 'secondary')])
    return levels


def _get_or_create_class_level(name, category, sort_order=0):
    level = ClassLevel.query.filter_by(tenant_id=g.current_tenant_id, name=name).first()
    if level:
        level.category = category or level.category
        level.sort_order = sort_order
        return level, False
    level = ClassLevel(
        tenant_id=g.current_tenant_id,
        name=name,
        category=category,
        sort_order=sort_order
    )
    db.session.add(level)
    db.session.flush()
    return level, True


def _get_or_create_class_arm(level, arm_name):
    arm = ClassArm.query.filter_by(
        tenant_id=g.current_tenant_id,
        class_level_id=level.id,
        name=arm_name
    ).first()
    if arm:
        return arm, False
    arm = ClassArm(tenant_id=g.current_tenant_id, class_level_id=level.id, name=arm_name)
    db.session.add(arm)
    db.session.flush()
    return arm, True


def _class_name_for_level_arm(level_name, arm_name):
    separator = '' if len(arm_name) == 1 and arm_name.isalpha() else ' '
    return f'{level_name}{separator}{arm_name}'


def _admin_section():
    if current_user.role == 'primary_admin':
        return 'primary'
    if current_user.role == 'secondary_admin':
        return 'secondary'
    return current_user.section


def _apply_section_scope(query, model=Class):
    section = _admin_section()
    if section:
        return query.filter(model.section == section)
    return query


def _class_metadata(class_name):
    normalized = (class_name or '').lower()
    section = None
    if normalized.startswith(('playgroup', 'kg', 'nursery', 'primary')):
        section = 'primary'
    elif normalized.startswith(('jss', 'sss')):
        section = 'secondary'

    arm = None
    compact = (class_name or '').strip()
    if compact and compact[-1:].isalpha() and compact[-1:].upper() in [chr(code) for code in range(65, 91)]:
        arm = compact[-1:].upper()

    track = _sss_track_for_class(class_name) if normalized.startswith('sss') else None
    return section, arm, track


def _generate_class_names(sections, arms, sss_tracks):
    generated = []
    arms = arms or ['A']

    if 'playgroup' in sections:
        generated.extend([f'Playgroup {arm}' for arm in arms])

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
    if normalized.startswith(('playgroup', 'kg', 'nursery', 'primary')):
        return 'primary'
    if normalized.startswith('jss'):
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
@role_required('local_admin')
def dashboard():
    """Admin dashboard for school management."""
    section = _admin_section()
    class_query = Class.query.filter_by(tenant_id=g.current_tenant_id)
    if section:
        class_query = class_query.filter_by(section=section)
    scoped_classes = class_query.all()
    scoped_class_ids = [class_obj.id for class_obj in scoped_classes]

    user_count = User.query.filter_by(tenant_id=g.current_tenant_id).count()
    if section:
        user_count = User.query.join(StudentClass, StudentClass.student_id == User.id).filter(
            User.tenant_id == g.current_tenant_id,
            User.role == 'student',
            StudentClass.tenant_id == g.current_tenant_id,
            StudentClass.class_id.in_(scoped_class_ids or [0])
        ).distinct().count()

    stats = {
        'users': user_count,
        'classes': len(scoped_classes),
        'subjects': Subject.query.filter_by(tenant_id=g.current_tenant_id).count(),
        'active_terms': Term.query.filter_by(tenant_id=g.current_tenant_id, is_active=True).count(),
        'pending_admissions': AdmissionApplication.query.filter_by(tenant_id=g.current_tenant_id, status='pending').count(),
    }
    return render_template('portal/dashboard.html', stats=stats, admin_section=section)


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


def _split_setup_lines(raw_value):
    """Parse newline-separated setup rows without splitting CSV-style commas."""
    return [line.strip() for line in (raw_value or '').splitlines() if line.strip()]


def _parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, '%Y-%m-%d').date()


def _parse_installment_milestones(labels, percentages, due_dates):
    milestones = []
    for index, label in enumerate(labels):
        label = (label or '').strip()
        if not label:
            continue
        try:
            percentage = float(percentages[index] or 0)
        except (IndexError, TypeError, ValueError):
            percentage = 0
        due_date = due_dates[index] if index < len(due_dates) else None
        milestones.append({
            'label': label,
            'percentage': percentage,
            'due_date': _parse_date(due_date),
        })
    return milestones


@admin_bp.route('/setup', methods=['GET', 'POST'])
@login_required
@role_required('local_admin')
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
                section, arm, track = _class_metadata(class_name)
                db.session.add(Class(tenant_id=tenant.id, name=class_name, section=section, arm=arm, track=track))
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

    classes = _apply_section_scope(Class.query.filter_by(tenant_id=tenant.id)).order_by(Class.name).all()
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
@role_required('local_admin')
def setup_wizard():
    """Guided setup for class levels, class arms, subjects, and first imports."""
    preference = SchoolSetupPreference.query.filter_by(tenant_id=g.current_tenant_id).first()
    if not preference:
        preference = SchoolSetupPreference(tenant_id=g.current_tenant_id)
        db.session.add(preference)
        db.session.commit()

    if request.method == 'POST':
        setup_mode = request.form.get('setup_mode') or 'quick'
        if setup_mode not in ('quick', 'manual'):
            flash('Choose Quick Automated Template Setup or Manual Custom School Setup.', 'error')
            return redirect(url_for('admin.setup_wizard'))

        school_type = request.form.get('school_type') or 'both'
        if school_type not in ('primary', 'secondary', 'both', 'combined'):
            flash('Choose Primary, Secondary, or Both before completing setup.', 'error')
            return redirect(url_for('admin.setup_wizard'))
        arms = _parse_list(request.form.get('arms')) or ['A']
        default_subjects = 'Mathematics\nEnglish Language\nCivic Education'
        subject_names = _split_setup_items(request.form.get('subjects')) or _split_setup_items(default_subjects)
        teacher_rows = _split_setup_lines(request.form.get('teachers'))
        student_rows = _split_setup_lines(request.form.get('students'))

        preference.setup_mode = setup_mode
        preference.school_type = school_type
        preference.sections = [school_type]
        preference.arms = arms
        preference.sss_tracks = ['Science', 'Humanities', 'Commercial']
        tenant = Tenant.query.get(g.current_tenant_id)
        if tenant:
            tenant.sections = 'both' if school_type in ('both', 'combined') else school_type

        created_levels = 0
        created_arms = 0
        created_classes = 0
        created_subjects = 0
        invited_users = []
        generated_classes = []

        for sort_order, (level_name, category) in enumerate(_base_class_levels_for_type(school_type), start=1):
            level, level_created = _get_or_create_class_level(level_name, category, sort_order)
            created_levels += int(level_created)

            for subject_name in subject_names:
                subject = Subject.query.filter_by(
                    tenant_id=g.current_tenant_id,
                    class_level_id=level.id,
                    name=subject_name
                ).first()
                if not subject:
                    subject = Subject(
                        tenant_id=g.current_tenant_id,
                        class_level_id=level.id,
                        name=subject_name
                    )
                    db.session.add(subject)
                    db.session.flush()
                    created_subjects += 1

            for arm_name in arms:
                arm, arm_created = _get_or_create_class_arm(level, arm_name)
                created_arms += int(arm_created)
                class_name = _class_name_for_level_arm(level.name, arm.name)
                class_obj = Class.query.filter_by(tenant_id=g.current_tenant_id, name=class_name).first()
                if not class_obj:
                    class_obj = Class(
                        tenant_id=g.current_tenant_id,
                        class_level_id=level.id,
                        class_arm_id=arm.id,
                        name=class_name,
                        section=category,
                        arm=arm.name
                    )
                    db.session.add(class_obj)
                    db.session.flush()
                    created_classes += 1

                for subject in Subject.query.filter_by(tenant_id=g.current_tenant_id, class_level_id=level.id).all():
                    _get_or_create_class_subject(class_obj.id, subject.id, is_required=True)

                generated_classes.append(class_obj)

        for row in teacher_rows:
            parts = [part.strip() for part in row.split(',')]
            if len(parts) < 2:
                continue
            name, email = parts[0], parts[1].lower()
            if not name or not email or User.query.filter_by(tenant_id=g.current_tenant_id, email=email).first():
                continue
            password = generate_temporary_password()
            user = User(
                tenant_id=g.current_tenant_id,
                name=name,
                email=email,
                role='teacher',
                is_approved=True,
                is_first_login=True,
                payment_status='paid'
            )
            ensure_custom_id(user, g.current_tenant, datetime.utcnow())
            user.set_password(password)
            db.session.add(user)
            invited_users.append((email, password))

        class_lookup = {class_obj.name.lower(): class_obj for class_obj in generated_classes}
        active_term = Term.query.filter_by(tenant_id=g.current_tenant_id, is_active=True).first()
        if not active_term:
            active_term = Term(
                tenant_id=g.current_tenant_id,
                name='First Term',
                session=f'{datetime.utcnow().year}/{datetime.utcnow().year + 1}',
                is_active=True
            )
            db.session.add(active_term)
            db.session.flush()

        for row in student_rows:
            parts = [part.strip() for part in row.split(',')]
            if len(parts) < 3:
                continue
            name, email, class_name = parts[0], parts[1].lower(), parts[2].lower()
            if not name or not email or User.query.filter_by(tenant_id=g.current_tenant_id, email=email).first():
                continue
            password = generate_temporary_password()
            student = User(
                tenant_id=g.current_tenant_id,
                name=name,
                email=email,
                role='student',
                is_approved=True,
                is_first_login=True,
                payment_status='unpaid'
            )
            ensure_custom_id(student, g.current_tenant, datetime.utcnow())
            student.set_password(password)
            db.session.add(student)
            db.session.flush()
            class_obj = class_lookup.get(class_name)
            if class_obj:
                db.session.add(StudentClass(
                    tenant_id=g.current_tenant_id,
                    student_id=student.id,
                    class_id=class_obj.id,
                    term_id=active_term.id
                ))
            invited_users.append((email, password))

        if tenant:
            tenant.setup_completed = True
            tenant.is_active = True
            tenant.status = 'active'

        db.session.commit()
        flash(
            'Setup complete. Added '
            f'{created_levels} levels, {created_arms} arms, {created_classes} class streams, '
            f'{created_subjects} subjects, and {len(invited_users)} users.',
            'success'
        )
        return redirect(url_for('admin.dashboard'))

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
@role_required('local_admin')
def class_subjects():
    """Select subjects offered by each class."""
    classes = _apply_section_scope(Class.query.filter_by(tenant_id=g.current_tenant_id)).order_by(Class.name).all()
    subjects = Subject.query.filter_by(tenant_id=g.current_tenant_id).order_by(Subject.name).all()

    if request.method == 'POST':
        ClassSubject.query.filter(
            ClassSubject.tenant_id == g.current_tenant_id,
            ClassSubject.class_id.in_([class_obj.id for class_obj in classes] or [0])
        ).delete(synchronize_session=False)

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
@role_required('local_admin')
def teacher_assignments():
    """Assign teachers to configured subject + class arm combinations."""
    active_term = Term.query.filter_by(tenant_id=g.current_tenant_id, is_active=True).first()
    teachers = User.query.filter_by(
        tenant_id=g.current_tenant_id,
        role='teacher'
    ).order_by(User.name).all()
    classes = _apply_section_scope(Class.query.filter_by(tenant_id=g.current_tenant_id)).order_by(Class.name).all()
    class_ids = [class_obj.id for class_obj in classes]
    class_subjects = ClassSubject.query.filter(
        ClassSubject.tenant_id == g.current_tenant_id,
        ClassSubject.class_id.in_(class_ids or [0])
    ).all()
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
    ).filter(TeacherAssignment.class_id.in_(class_ids or [0])).order_by(TeacherAssignment.created_at.desc()).all()
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
@role_required('local_admin')
def admissions():
    """Review admission applications for this school."""
    status = request.args.get('status', 'pending')
    query = AdmissionApplication.query.filter_by(tenant_id=g.current_tenant_id)
    if status != 'all':
        query = query.filter_by(status=status)

    applications = query.order_by(AdmissionApplication.created_at.desc()).all()
    classes = _apply_section_scope(Class.query.filter_by(tenant_id=g.current_tenant_id)).order_by(Class.name).all()
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
@role_required('local_admin')
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
        role='student',
        is_approved=True,
        is_first_login=True,
        payment_status='unpaid'
    )
    ensure_custom_id(student, g.current_tenant, datetime.utcnow())
    password = generate_temporary_password()
    student.set_password(password)
    db.session.add(student)
    db.session.flush()

    if class_id and term_id:
        class_obj = Class.query.filter_by(id=class_id, tenant_id=g.current_tenant_id).first()
        if _admin_section() and (not class_obj or class_obj.section != _admin_section()):
            db.session.rollback()
            flash('Selected class is outside your section workspace.', 'error')
            return redirect(url_for('admin.admissions'))
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


@admin_bp.route('/payments', methods=['GET', 'POST'])
@login_required
@role_required('local_admin')
def payments():
    """Manage student payment status and portal access."""
    active_term = Term.query.filter_by(tenant_id=g.current_tenant_id, is_active=True).first()
    classes = _apply_section_scope(Class.query.filter_by(tenant_id=g.current_tenant_id)).order_by(Class.name).all()
    class_ids = [class_obj.id for class_obj in classes]
    categories = FeeCategory.query.filter_by(tenant_id=g.current_tenant_id).order_by(FeeCategory.name).all()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'category':
            name = (request.form.get('name') or '').strip()
            if not name:
                flash('Fee category name is required.', 'error')
                return redirect(url_for('admin.payments'))
            existing = FeeCategory.query.filter_by(tenant_id=g.current_tenant_id, name=name).first()
            if not existing:
                db.session.add(FeeCategory(
                    tenant_id=g.current_tenant_id,
                    name=name,
                    description=request.form.get('description') or None,
                    is_active=request.form.get('is_active') == 'on'
                ))
                db.session.commit()
            flash('Fee category saved.', 'success')
            return redirect(url_for('admin.payments'))

        if action == 'plan':
            category_id = request.form.get('fee_category_id')
            class_id = request.form.get('class_id') or None
            term_id = request.form.get('term_id') or (active_term.id if active_term else None)
            amount = float(request.form.get('amount') or 0)
            category = FeeCategory.query.filter_by(id=category_id, tenant_id=g.current_tenant_id).first()
            class_obj = None
            if class_id:
                class_obj = Class.query.filter_by(id=class_id, tenant_id=g.current_tenant_id).first()
            if not category or (class_id and (not class_obj or class_obj.id not in class_ids)):
                flash('Invalid category or class for this school workspace.', 'error')
                return redirect(url_for('admin.payments'))

            plan = FeeInstallmentPlan(
                tenant_id=g.current_tenant_id,
                fee_category_id=category.id,
                class_id=class_obj.id if class_obj else None,
                term_id=term_id,
                amount=amount,
                installments_enabled=request.form.get('installments_enabled') == 'on'
            )
            db.session.add(plan)
            db.session.flush()

            milestones = _parse_installment_milestones(
                request.form.getlist('milestone_label'),
                request.form.getlist('milestone_percentage'),
                request.form.getlist('milestone_due_date')
            )
            total_percentage = sum(item['percentage'] for item in milestones)
            if plan.installments_enabled and round(total_percentage, 2) != 100:
                db.session.rollback()
                flash('Installment milestones must add up to 100%.', 'error')
                return redirect(url_for('admin.payments'))

            for milestone in milestones:
                db.session.add(FeeInstallmentMilestone(
                    tenant_id=g.current_tenant_id,
                    plan_id=plan.id,
                    label=milestone['label'],
                    percentage=milestone['percentage'],
                    due_date=milestone['due_date']
                ))

            db.session.commit()
            flash('Fee plan saved.', 'success')
            return redirect(url_for('admin.payments'))

    students_query = User.query.filter_by(tenant_id=g.current_tenant_id, role='student')
    if _admin_section():
        students_query = students_query.join(StudentClass, StudentClass.student_id == User.id).filter(
            StudentClass.tenant_id == g.current_tenant_id,
            StudentClass.class_id.in_(class_ids or [0])
        ).distinct()
    students = students_query.order_by(User.name).all()
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

    plans = FeeInstallmentPlan.query.filter_by(tenant_id=g.current_tenant_id).order_by(FeeInstallmentPlan.created_at.desc()).all()
    transactions = PaymentTransaction.query.filter_by(tenant_id=g.current_tenant_id).order_by(PaymentTransaction.created_at.desc()).limit(20).all()
    return render_template(
        'portal/admin_payments.html',
        active_term=active_term,
        access_records=access_records,
        categories=categories,
        plans=plans,
        classes=classes,
        transactions=transactions
    )


@admin_bp.route('/payments/<int:access_id>/mark-paid', methods=['POST'])
@login_required
@role_required('local_admin')
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
    if access.student:
        access.student.payment_status = 'paid'
    db.session.commit()

    flash('Payment confirmed and portal unlocked.', 'success')
    return redirect(url_for('admin.payments'))


@admin_bp.route('/announcement', methods=['POST'])
@login_required
@role_required('local_admin')
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
@role_required('local_admin')
def create_user():
    """Create a new user (admin, teacher, student, or attendant)."""
    data = request.get_json()
    
    name = data.get('name')
    email = data.get('email')
    role = data.get('role')
    
    if not all([name, email, role]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if role not in ['school_admin', 'admin', 'primary_admin', 'secondary_admin', 'teacher', 'student', 'attendant', 'parent']:
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
        phone_number=data.get('phone_number') or data.get('phone'),
        role=role,
        section=data.get('section') or ('primary' if role == 'primary_admin' else ('secondary' if role == 'secondary_admin' else None)),
        is_approved=True,
        is_first_login=True,
        payment_status=data.get('payment_status') or ('unpaid' if role in ['student', 'parent'] else 'paid')
    )
    ensure_custom_id(user, g.current_tenant, datetime.utcnow())
    temporary_password = data.get('temporary_password') or generate_temporary_password()
    user.set_password(temporary_password)
    
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
        'user_id': user.id,
        'school_generated_id': user.school_generated_id,
        'temporary_password': temporary_password
    }), 201


@admin_bp.route('/reset-user-password', methods=['POST'])
@login_required
@role_required('local_admin')
def reset_user_password():
    """Reset a tenant user back into first-login onboarding."""
    data = request.get_json(silent=True) or request.form
    target_user_id = data.get('user_id')

    target = User.query.filter_by(
        id=target_user_id,
        tenant_id=g.current_tenant_id
    ).first_or_404()

    if target.role == 'super_admin':
        abort(403)

    temporary_password = generate_temporary_password()
    target.set_password(temporary_password)
    target.is_first_login = True
    db.session.commit()

    response = {
        'success': True,
        'message': 'Password reset. Share the temporary password with the user.',
        'school_generated_id': target.school_generated_id,
        'temporary_password': temporary_password
    }
    if request.is_json:
        return jsonify(response), 200
    flash(response['message'], 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/classes', methods=['POST'])
@login_required
@role_required('local_admin')
def create_class():
    """Create a new class."""
    data = request.get_json()
    
    name = data.get('name')
    
    if not name:
        return jsonify({'error': 'Class name is required'}), 400
    
    section, arm, track = _class_metadata(name)
    class_obj = Class(
        tenant_id=g.current_tenant_id,
        name=name,
        section=section,
        arm=arm,
        track=track
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
@role_required('local_admin')
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
@role_required('local_admin')
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
@role_required('local_admin')
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
@role_required('local_admin')
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


@admin_bp.route('/bulk-onboarding', methods=['GET', 'POST'])
@login_required
@role_required('local_admin')
def bulk_onboarding():
    """Upload CSV/XLSX files to create student or teacher accounts in bulk."""
    classes = _apply_section_scope(Class.query.filter_by(tenant_id=g.current_tenant_id)).order_by(Class.name).all()
    terms = Term.query.filter_by(tenant_id=g.current_tenant_id).order_by(Term.created_at.desc()).all()

    if request.method == 'GET':
        return render_template('portal/admin_bulk_onboarding.html', classes=classes, terms=terms)

    upload = request.files.get('spreadsheet')
    account_type = request.form.get('account_type')
    default_class_id = request.form.get('default_class_id') or None
    default_term_id = request.form.get('default_term_id') or None

    if account_type not in ['student', 'teacher'] or not upload:
        flash('Choose a Student or Teacher spreadsheet to upload.', 'error')
        return redirect(url_for('admin.bulk_onboarding'))

    try:
        import pandas as pd

        filename = (upload.filename or '').lower()
        if filename.endswith('.csv'):
            frame = pd.read_csv(upload)
        elif filename.endswith(('.xlsx', '.xls')):
            frame = pd.read_excel(upload, engine='openpyxl')
        else:
            flash('Upload a CSV or Excel file.', 'error')
            return redirect(url_for('admin.bulk_onboarding'))
    except ImportError:
        flash('Bulk onboarding requires pandas and openpyxl to be installed.', 'error')
        return redirect(url_for('admin.bulk_onboarding'))
    except Exception as exc:
        flash(f'Unable to read spreadsheet: {exc}', 'error')
        return redirect(url_for('admin.bulk_onboarding'))

    required_columns = {'name', 'email'}
    columns = {str(column).strip().lower(): column for column in frame.columns}
    if not required_columns.issubset(columns):
        flash('Spreadsheet must include name and email columns. Password is optional.', 'error')
        return redirect(url_for('admin.bulk_onboarding'))

    class_ids = {class_obj.id for class_obj in classes}
    created = 0
    skipped = []

    for index, row in frame.iterrows():
        name = str(row[columns['name']]).strip()
        email = str(row[columns['email']]).strip().lower()
        if not name or not email or email == 'nan':
            skipped.append(f'Row {index + 2}: missing name or email')
            continue

        if User.query.filter_by(tenant_id=g.current_tenant_id, email=email).first():
            skipped.append(f'Row {index + 2}: duplicate email {email}')
            continue

        user = User(
            tenant_id=g.current_tenant_id,
            name=name,
            email=email,
            role=account_type,
            phone_number=str(row[columns.get('phone_number')]).strip() if columns.get('phone_number') and not row.isna()[columns['phone_number']] else None,
            is_approved=True,
            is_first_login=True,
            payment_status='unpaid' if account_type == 'student' else 'paid'
        )
        ensure_custom_id(user, g.current_tenant, datetime.utcnow())
        temporary_password = str(row[columns['password']]).strip() if columns.get('password') and not row.isna()[columns['password']] else generate_temporary_password()
        user.set_password(temporary_password)
        db.session.add(user)
        db.session.flush()

        class_id = default_class_id
        if columns.get('class_id') and not row.isna()[columns['class_id']]:
            class_id = int(row[columns['class_id']])
        term_id = default_term_id
        if columns.get('term_id') and not row.isna()[columns['term_id']]:
            term_id = int(row[columns['term_id']])
        if account_type == 'student' and class_id and term_id and int(class_id) in class_ids:
            db.session.add(StudentClass(
                tenant_id=g.current_tenant_id,
                student_id=user.id,
                class_id=int(class_id),
                term_id=int(term_id)
            ))
        created += 1

    db.session.commit()
    flash(f'Bulk onboarding complete. Created {created} accounts. Skipped {len(skipped)} rows.', 'success')
    return render_template('portal/admin_bulk_onboarding.html', classes=classes, terms=terms, skipped=skipped)


@admin_bp.route('/payment-webhook/<provider>', methods=['POST'])
def payment_webhook(provider):
    """Receive Paystack/Flutterwave-style payment callbacks and update balances."""
    if provider not in ['paystack', 'flutterwave']:
        return jsonify({'error': 'Unsupported payment provider'}), 400

    payload = request.get_json(silent=True) or {}
    data = payload.get('data') or payload
    metadata = data.get('metadata') or data.get('meta') or {}
    reference = data.get('reference') or data.get('tx_ref') or data.get('flw_ref')
    status = (data.get('status') or payload.get('event') or '').lower()

    try:
        tenant_id = int(metadata.get('tenant_id'))
        student_id = int(metadata.get('student_id'))
        term_id = int(metadata.get('term_id')) if metadata.get('term_id') else None
        amount = float(data.get('amount') or 0)
        if provider == 'paystack' and amount > 1000:
            amount = amount / 100
    except (TypeError, ValueError):
        return jsonify({'error': 'Webhook metadata must include tenant_id and student_id'}), 400

    if not reference:
        return jsonify({'error': 'Payment reference is required'}), 400

    transaction = PaymentTransaction.query.filter_by(provider=provider, reference=reference).first()
    if not transaction:
        transaction = PaymentTransaction(
            tenant_id=tenant_id,
            student_id=student_id,
            term_id=term_id,
            provider=provider,
            reference=reference
        )
        db.session.add(transaction)

    transaction.amount = amount
    transaction.status = status or 'success'
    transaction.raw_payload = payload

    if transaction.status in ['success', 'successful', 'charge.success']:
        access = StudentTermAccess.query.filter_by(
            tenant_id=tenant_id,
            student_id=student_id,
            term_id=term_id
        ).first()
        if access:
            access.amount_paid = (access.amount_paid or 0) + amount
            access.payment_reference = reference
            access.is_paid = access.amount_paid >= (access.amount_due or 0)
            access.portal_unlocked = access.is_paid
            if access.is_paid and access.student:
                access.student.payment_status = 'paid'

    db.session.commit()
    return jsonify({'success': True}), 200


@admin_bp.route('/api/offline-sync/assignments', methods=['POST'])
@admin_bp.route('/api/offline-sync/quiz-submissions', methods=['POST'])
@login_required
@role_required('student')
def offline_sync_assignments():
    """Accept queued assignment/quiz payloads from low-bandwidth clients."""
    payload = request.get_json(silent=True) or {}
    items = payload.get('items') or []
    if not isinstance(items, list):
        return jsonify({'error': 'items must be an array'}), 400

    synced = []
    for item in items:
        assignment_id = item.get('assignment_id')
        client_sync_id = item.get('client_sync_id')
        if not assignment_id or not client_sync_id:
            synced.append({'client_sync_id': client_sync_id, 'status': 'rejected'})
            continue

        assignment = Assignment.query.filter_by(
            id=assignment_id,
            tenant_id=current_user.tenant_id,
            is_published=True
        ).first()
        if not assignment:
            synced.append({'client_sync_id': client_sync_id, 'status': 'missing_assignment'})
            continue

        submission = AssignmentSubmission.query.filter_by(
            tenant_id=current_user.tenant_id,
            client_sync_id=client_sync_id
        ).first()
        if not submission:
            submission = AssignmentSubmission.query.filter_by(
                tenant_id=current_user.tenant_id,
                assignment_id=assignment.id,
                student_id=current_user.id
            ).first()

        if not submission:
            submission = AssignmentSubmission(
                tenant_id=current_user.tenant_id,
                assignment_id=assignment.id,
                student_id=current_user.id,
                client_sync_id=client_sync_id
            )
            db.session.add(submission)

        submission.submission_text = item.get('submission_text') or submission.submission_text
        submission.quiz_answers = item.get('quiz_answers') or submission.quiz_answers
        submission.submitted_at = datetime.utcnow()
        synced.append({'client_sync_id': client_sync_id, 'status': 'synced'})

    db.session.commit()
    return jsonify({'success': True, 'items': synced}), 200
