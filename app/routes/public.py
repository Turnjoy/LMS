import hmac
import re
from urllib.parse import urlparse

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, abort, g, jsonify, session
from flask_login import current_user, login_required, login_user
from sqlalchemy import or_
from werkzeug.security import check_password_hash
from app.auth_utils import ensure_custom_id
from app.models import (
    AdmissionApplication,
    Assignment,
    AssignmentSubmission,
    Attendance,
    CBTExam,
    CBTQuestion,
    Class,
    ClassArm,
    ClassLevel,
    ClassSubject,
    FeeCategory,
    FeeInstallmentMilestone,
    FeeInstallmentPlan,
    Parent,
    PaymentGatewaySetting,
    PaymentTransaction,
    Result,
    SchoolSetupPreference,
    StudentClass,
    StudentParent,
    StudentSubjectRegistration,
    StudentTermAccess,
    StudentTermRegistration,
    Subject,
    TeacherAssignment,
    Tenant,
    TenantAISetting,
    TenantPublicProfile,
    TenantSubject,
    Term,
    User,
)
from app import db

public_bp = Blueprint('public', __name__)

LOCAL_ADMIN_ROLES = ('school_admin', 'admin', 'primary_admin', 'secondary_admin')


def _tenant_landing_context():
    if not getattr(g, 'current_tenant', None):
        return {}
    profile = Tenant.query.filter_by(id=g.current_tenant_id).first()
    return {'tenant': g.current_tenant, 'tenant_domain': g.current_domain, 'profile': getattr(g, 'current_tenant', None)}


def _is_master_owner(user):
    if not user.is_authenticated or user.role != 'super_admin':
        return False
    owner_email = current_app.config.get('MASTER_OWNER_EMAIL')
    return not owner_email or ((user.email or '').lower() == owner_email.lower())


def _master_password_matches(password):
    configured = current_app.config.get('MASTER_ADMIN_PASSWORD')
    if not configured or not password:
        return False
    return hmac.compare_digest(str(password), str(configured))


def _is_master_admin():
    return bool(session.get('is_super_admin')) or _is_master_owner(current_user)


def _school_status(tenant):
    if tenant.status in ('pending', 'rejected'):
        return tenant.status
    return 'active' if tenant.is_active and tenant.status in ('active', 'approved') else 'rejected'


def _school_payload(tenant):
    status = _school_status(tenant)
    return {
        'id': tenant.id,
        'name': tenant.name,
        'custom_domain': tenant.custom_domain,
        'subdomain': tenant.subdomain,
        'is_active': tenant.is_active,
        'status': status,
        'status_label': 'Active' if status == 'active' else status.title(),
        'billing_type': tenant.billing_type,
        'school_prefix': tenant.school_prefix,
        'setup_completed': tenant.setup_completed,
    }


def _slugify_school(value):
    slug = re.sub(r'[^a-z0-9]+', '-', (value or '').strip().lower()).strip('-')
    return (slug or 'school')[:50]


def _school_prefix(value):
    letters = re.sub(r'[^A-Za-z0-9]', '', value or '').upper()
    return (letters[:6] or 'SCH')[:12]


def _normalize_application_website(value):
    raw_value = (value or '').strip().lower()
    if not raw_value:
        return ''
    parsed = urlparse(raw_value if '://' in raw_value else f'https://{raw_value}')
    host = (parsed.netloc or parsed.path or '').split('/')[0].strip().rstrip('.')
    if host.startswith('www.'):
        host = host[4:]
    return host


def _unique_application_subdomain(seed):
    base = _slugify_school(seed)
    candidate = base
    suffix = 2
    while Tenant.query.filter_by(subdomain=candidate).first():
        trimmed_base = base[: max(1, 50 - len(str(suffix)) - 1)]
        candidate = f'{trimmed_base}-{suffix}'
        suffix += 1
    return candidate


def _normalize_subdomain(value):
    return re.sub(r'[^a-z0-9-]+', '-', (value or '').strip().lower()).strip('-')[:50]


def _ensure_school_initialization(tenant):
    if not TenantAISetting.query.filter_by(tenant_id=tenant.id).first():
        db.session.add(TenantAISetting(tenant_id=tenant.id))

    if not TenantPublicProfile.query.filter_by(tenant_id=tenant.id).first():
        db.session.add(TenantPublicProfile(
            tenant_id=tenant.id,
            headline='Welcome to our school',
            admission_message='Apply for admission and our team will review it.'
        ))

    if not PaymentGatewaySetting.query.filter_by(tenant_id=tenant.id).first():
        db.session.add(PaymentGatewaySetting(
            tenant_id=tenant.id,
            payment_instructions='Pay school fees through the approved school account, then contact the bursary for confirmation.'
        ))


def _delete_school_tree(tenant):
    tenant_id = tenant.id
    for model in [
        StudentSubjectRegistration,
        TenantSubject,
        ClassSubject,
        StudentTermRegistration,
        StudentTermAccess,
        FeeInstallmentMilestone,
        FeeInstallmentPlan,
        FeeCategory,
        PaymentTransaction,
        AdmissionApplication,
        AssignmentSubmission,
        CBTQuestion,
        CBTExam,
        Assignment,
        Attendance,
        Result,
        TeacherAssignment,
        StudentClass,
        StudentParent,
        Parent,
        SchoolSetupPreference,
        TenantAISetting,
        TenantPublicProfile,
        PaymentGatewaySetting,
        User,
        Term,
        Subject,
        Class,
        ClassArm,
        ClassLevel,
    ]:
        model.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    db.session.delete(tenant)


def _master_dashboard_context():
    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    tenant_data = []
    total_students = User.query.filter_by(role='student').count()
    total_schools = Tenant.query.count()
    total_active_schools = Tenant.query.filter(
        Tenant.is_active.is_(True),
        Tenant.status.in_(('active', 'approved'))
    ).count()
    total_pending_schools = Tenant.query.filter_by(status='pending').count()
    pending_admins = User.query.filter(
        User.role.in_(LOCAL_ADMIN_ROLES),
        User.is_approved.is_(False)
    ).order_by(User.created_at.asc()).all()
    for tenant in tenants:
        students = User.query.filter_by(tenant_id=tenant.id, role='student').count()
        admins = User.query.filter(
            User.tenant_id == tenant.id,
            User.role.in_(LOCAL_ADMIN_ROLES)
        ).count()
        teachers = User.query.filter_by(tenant_id=tenant.id, role='teacher').count()
        families = User.query.filter_by(tenant_id=tenant.id, role='parent').count()
        domain = tenant.application_website or tenant.custom_domain or tenant.subdomain or ''
        section_config = (tenant.sections or 'both').title()
        sss_tracks = [
            track.strip()
            for track in (tenant.sss_tracks or 'Science,Humanities,Commercial').split(',')
            if track.strip()
        ]
        tenant_data.append({
            'id': tenant.id,
            'name': tenant.name,
            'status': _school_status(tenant),
            'school_code': tenant.structured_code,
            'domain': domain,
            'contact_name': tenant.application_contact_name or 'Not provided',
            'contact_email': tenant.application_contact_email or '',
            'contact_phone': tenant.application_contact_phone or '',
            'billing_type': tenant.billing_type,
            'section_config': section_config,
            'sss_tracks': sss_tracks,
            'student_count': students,
            'admin_count': admins,
            'teacher_count': teachers,
            'family_count': families,
        })
    return {
        'tenant_data': tenant_data,
        'total_schools': total_schools,
        'total_students': total_students,
        'total_active_schools': total_active_schools,
        'total_pending_schools': total_pending_schools,
        'pending_admins': pending_admins,
    }


@public_bp.route('/')
def index():
    if getattr(g, 'current_tenant', None):
        profile = g.current_tenant.public_profile
        classes = None
        from app.models import Class
        classes = Class.query.filter_by(tenant_id=g.current_tenant_id).order_by(Class.name).all()
        return render_template('portal/landing.html', profile=profile, classes=classes)

    return render_template('public/index.html')


@public_bp.route('/about')
def about():
    if getattr(g, 'current_tenant', None):
        abort(404)
    return render_template('public/about.html')


@public_bp.route('/pricing')
def pricing():
    if getattr(g, 'current_tenant', None):
        abort(404)
    return render_template('public/pricing.html')


@public_bp.route('/apply', methods=['GET', 'POST'])
def apply_school():
    if getattr(g, 'current_tenant', None):
        abort(404)

    if request.method == 'POST':
        school_name = (request.form.get('school_name') or '').strip()
        desired_subdomain = _normalize_subdomain(request.form.get('subdomain'))
        admin_name = (request.form.get('admin_name') or '').strip()
        admin_email = (request.form.get('admin_email') or '').strip().lower()
        admin_password = request.form.get('admin_password') or ''

        if not all([school_name, desired_subdomain, admin_name, admin_email, admin_password]):
            flash('Please complete the school name, desired subdomain, admin name, admin email, and admin password.', 'error')
            return render_template('public/apply.html'), 400
        if len(admin_password) < 8:
            flash('Admin password must be at least 8 characters.', 'error')
            return render_template('public/apply.html'), 400
        if not re.match(r'^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$', desired_subdomain):
            flash('Use a valid subdomain with letters, numbers, and hyphens only.', 'error')
            return render_template('public/apply.html'), 400

        existing = Tenant.query.filter(
            or_(
                Tenant.subdomain == desired_subdomain,
                Tenant.application_contact_email == admin_email,
            )
        ).first()
        if existing:
            status_label = 'Active' if _school_status(existing) == 'active' else _school_status(existing).title()
            flash(f'This school request is already on file. Current status: {status_label}.', 'info')
            return render_template('public/apply.html', submitted_school=existing), 200

        tenant = Tenant(
            name=school_name,
            subdomain=desired_subdomain,
            school_prefix=_school_prefix(school_name),
            status='pending',
            is_active=False,
            setup_completed=False,
            application_contact_name=admin_name,
            application_contact_email=admin_email,
        )
        db.session.add(tenant)
        db.session.flush()

        admin = User(
            tenant_id=tenant.id,
            name=admin_name,
            email=admin_email,
            role='school_admin',
            is_approved=True,
            is_first_login=True,
            payment_status='paid',
        )
        ensure_custom_id(admin, tenant, tenant.created_at)
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()
        flash(f'Application submitted. Your admin ID is {admin.school_generated_id}. Sign in with your email and password after approval.', 'success')
        return render_template('public/apply.html', submitted_school=tenant), 201

    return render_template('public/apply.html')


@public_bp.route('/contact')
def contact():
    if getattr(g, 'current_tenant', None):
        abort(404)
    return render_template('public/contact.html')


@public_bp.route('/admin')
def school_admin_redirect():
    if not getattr(g, 'current_tenant', None):
        return redirect(url_for('public.master_dashboard'))
    return redirect(url_for('auth.login'))


@public_bp.route('/turnjoy-master-admin', methods=['GET', 'POST'])
@public_bp.route('/_master_hq_2026', methods=['GET', 'POST'])
def master_dashboard():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if _master_password_matches(password):
            session['is_super_admin'] = True
            return redirect(url_for('public.master_dashboard'))

        if not email or not password:
            flash('Master password is required.', 'error')
            return render_template('public/master_login.html')

        user = User.query.filter_by(email=email.strip().lower(), role='super_admin').first()
        if user and user.password_hash and check_password_hash(user.password_hash, password) and _is_master_owner(user):
            login_user(user)
            session['is_super_admin'] = True
            return redirect(url_for('public.master_dashboard'))

        flash('Invalid credentials.', 'error')
        return render_template('public/master_login.html')

    if _is_master_admin():
        return render_template('public/master_dashboard.html', **_master_dashboard_context())

    return render_template('public/master_login.html')


@public_bp.route('/_master_hq_2026/admins/<int:user_id>/accept', methods=['POST'])
def accept_school_admin(user_id):
    if not _is_master_admin():
        abort(403)

    user = User.query.filter(
        User.id == user_id,
        User.role.in_(LOCAL_ADMIN_ROLES)
    ).first_or_404()
    user.is_approved = True
    db.session.commit()
    flash(f'{user.name} has been approved as a local school admin.', 'success')
    return redirect(url_for('public.master_dashboard'))


@public_bp.route('/_master_hq_2026/tenant/<int:tenant_id>')
def master_tenant_detail(tenant_id):
    if not _is_master_admin():
        abort(403)

    tenant = Tenant.query.filter_by(id=tenant_id).first_or_404()
    admin_count = User.query.filter(
        User.tenant_id == tenant.id,
        User.role.in_(LOCAL_ADMIN_ROLES)
    ).count()
    teacher_count = User.query.filter_by(tenant_id=tenant.id, role='teacher').count()
    student_count = User.query.filter_by(tenant_id=tenant.id, role='student').count()
    family_count = User.query.filter_by(tenant_id=tenant.id, role='parent').count()
    section_config = (tenant.sections or 'both').title()
    sss_tracks = [track.strip() for track in (tenant.sss_tracks or 'Science,Humanities,Commercial').split(',') if track.strip()]

    return render_template(
        'public/master_tenant_detail.html',
        tenant=tenant,
        admin_count=admin_count,
        teacher_count=teacher_count,
        student_count=student_count,
        family_count=family_count,
        section_config=section_config,
        sss_tracks=sss_tracks,
    )


@public_bp.route('/turnjoy-master-admin/tenant/<int:tenant_id>/metrics')
@public_bp.route('/_master_hq_2026/tenant/<int:tenant_id>/metrics')
def master_tenant_metrics(tenant_id):
    if not _is_master_admin():
        abort(403)

    tenant = Tenant.query.filter_by(id=tenant_id).first_or_404()
    return jsonify({
        'school_id': tenant.id,
        'school_name': tenant.name,
        'school_prefix': tenant.school_prefix,
        'status': _school_status(tenant),
        'status_label': 'Active' if _school_status(tenant) == 'active' else _school_status(tenant).title(),
        'is_active': tenant.is_active,
        'billing_type': tenant.billing_type,
        'total_students': User.query.filter_by(tenant_id=tenant.id, role='student').count(),
        'total_teachers': User.query.filter_by(tenant_id=tenant.id, role='teacher').count(),
        'total_families': User.query.filter_by(tenant_id=tenant.id, role='parent').count(),
    })


@public_bp.route('/turnjoy-master-admin/tenant/<int:tenant_id>/billing', methods=['POST'])
@public_bp.route('/_master_hq_2026/tenant/<int:tenant_id>/billing', methods=['POST'])
def update_tenant_billing(tenant_id):
    if not _is_master_admin():
        abort(403)

    tenant = Tenant.query.filter_by(id=tenant_id).first_or_404()
    billing_type = request.form.get('billing_type')
    if billing_type not in ['student_pay', 'school_pay']:
        flash('Invalid billing type.', 'error')
        return redirect(url_for('public.master_dashboard'))

    tenant.billing_type = billing_type
    tenant.school_prefix = (request.form.get('school_prefix') or tenant.school_prefix or 'SCH').strip().upper()[:12]
    tenant.is_active = request.form.get('is_active') == 'on'
    tenant.status = 'active' if tenant.is_active else 'rejected'
    db.session.commit()
    flash(f'{tenant.name} billing and lock status updated.', 'success')
    return redirect(url_for('public.master_dashboard'))


@public_bp.route('/turnjoy-master-admin/api/schools/<int:tenant_id>', methods=['PATCH', 'POST'])
def update_school_controls(tenant_id):
    if not _is_master_admin():
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json(silent=True) or {}
    tenant = Tenant.query.filter_by(id=tenant_id).first_or_404()

    if 'is_active' in data:
        tenant.is_active = bool(data['is_active'])
        tenant.status = 'active' if tenant.is_active else 'rejected'

    if 'status' in data:
        status = data['status']
        if status not in ['pending', 'active', 'approved', 'rejected']:
            return jsonify({'error': 'Invalid status'}), 400
        tenant.status = 'active' if status == 'approved' else status
        tenant.is_active = tenant.status == 'active'

    if 'billing_type' in data:
        billing_type = data['billing_type']
        if billing_type not in ['school_pay', 'student_pay']:
            return jsonify({'error': 'Invalid billing_type'}), 400
        tenant.billing_type = billing_type

    if 'school_prefix' in data:
        tenant.school_prefix = (data.get('school_prefix') or tenant.school_prefix or 'SCH').strip().upper()[:12]

    db.session.commit()
    return jsonify({'success': True, 'school': _school_payload(tenant)}), 200


@public_bp.route('/api/admin/school/<int:school_id>/accept', methods=['POST'])
def accept_school(school_id):
    if not session.get('is_super_admin'):
        return jsonify({'error': 'Forbidden'}), 403

    tenant = Tenant.query.filter_by(id=school_id).first_or_404()
    tenant.status = 'active'
    tenant.is_active = True
    _ensure_school_initialization(tenant)
    db.session.commit()
    return jsonify({'success': True, 'school': _school_payload(tenant)}), 200


@public_bp.route('/_master_hq_2026/school/<int:school_id>/accept', methods=['POST'])
def accept_school_html(school_id):
    if not _is_master_admin():
        abort(403)

    tenant = Tenant.query.filter_by(id=school_id).first_or_404()
    tenant.status = 'active'
    tenant.is_active = True
    _ensure_school_initialization(tenant)
    db.session.commit()
    flash(f'{tenant.name} has been approved.', 'success')
    return redirect(url_for('public.master_dashboard'))


@public_bp.route('/api/admin/school/<int:school_id>/reject', methods=['POST'])
def reject_school(school_id):
    if not session.get('is_super_admin'):
        return jsonify({'error': 'Forbidden'}), 403

    tenant = Tenant.query.filter_by(id=school_id).first_or_404()
    tenant.status = 'rejected'
    tenant.is_active = False
    db.session.commit()
    return jsonify({'success': True, 'school': _school_payload(tenant)}), 200


@public_bp.route('/_master_hq_2026/school/<int:school_id>/reject', methods=['POST'])
def reject_school_html(school_id):
    if not _is_master_admin():
        abort(403)

    tenant = Tenant.query.filter_by(id=school_id).first_or_404()
    tenant.status = 'rejected'
    tenant.is_active = False
    db.session.commit()
    flash(f'{tenant.name} has been rejected.', 'warning')
    return redirect(url_for('public.master_dashboard'))


@public_bp.route('/api/admin/school/<int:school_id>/delete', methods=['DELETE', 'POST'])
def delete_school(school_id):
    if not session.get('is_super_admin'):
        return jsonify({'error': 'Forbidden'}), 403

    tenant = Tenant.query.filter_by(id=school_id).first_or_404()
    _delete_school_tree(tenant)
    db.session.commit()
    return jsonify({'success': True, 'deleted_school_id': school_id}), 200


@public_bp.route('/_master_hq_2026/school/<int:school_id>/delete', methods=['POST'])
def delete_school_html(school_id):
    if not _is_master_admin():
        abort(403)

    tenant = Tenant.query.filter_by(id=school_id).first_or_404()
    tenant_name = tenant.name
    _delete_school_tree(tenant)
    db.session.commit()
    flash(f'{tenant_name} has been permanently deleted.', 'success')
    return redirect(url_for('public.master_dashboard'))
