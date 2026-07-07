from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, abort, g, jsonify
from flask_login import current_user, login_required, login_user
from werkzeug.security import check_password_hash
from app.models import Tenant, User
from app import db

public_bp = Blueprint('public', __name__)

LOCAL_ADMIN_ROLES = ('admin', 'primary_admin', 'secondary_admin')


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


@public_bp.route('/contact')
def contact():
    if getattr(g, 'current_tenant', None):
        abort(404)
    return render_template('public/contact.html')


@public_bp.route('/admin')
def school_admin_redirect():
    if not getattr(g, 'current_tenant', None):
        abort(404)
    return redirect(url_for('auth.login'))


@public_bp.route('/_master_hq_2026', methods=['GET', 'POST'])
def master_dashboard():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash('Email and password are required.', 'error')
            return render_template('public/master_login.html')

        user = User.query.filter_by(email=email.strip().lower(), role='super_admin').first()
        if user and user.password_hash and check_password_hash(user.password_hash, password) and _is_master_owner(user):
            login_user(user)
            return redirect(url_for('public.master_dashboard'))

        flash('Invalid credentials.', 'error')
        return render_template('public/master_login.html')

    if current_user.is_authenticated and _is_master_owner(current_user):
        tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
        tenant_data = []
        total_students = User.query.filter_by(role='student').count()
        total_active_schools = Tenant.query.filter_by(is_active=True).count()
        pending_admins = User.query.filter(
            User.role.in_(['admin', 'primary_admin', 'secondary_admin']),
            User.is_approved.is_(False)
        ).order_by(User.created_at.asc()).all()
        for tenant in tenants:
            students = User.query.filter_by(tenant_id=tenant.id, role='student').order_by(User.name).all()
            admins = User.query.filter(
                User.tenant_id == tenant.id,
                User.role.in_(['admin', 'primary_admin', 'secondary_admin'])
            ).count()
            teachers = User.query.filter_by(tenant_id=tenant.id, role='teacher').count()
            families = User.query.filter_by(tenant_id=tenant.id, role='parent').count()
            tenant_data.append({
                'tenant': tenant,
                'school_code': tenant.structured_code,
                'student_count': len(students),
                'admin_count': admins,
                'teacher_count': teachers,
                'family_count': families,
                'students': students,
            })
        return render_template(
            'public/master_dashboard.html',
            tenant_data=tenant_data,
            total_students=total_students,
            total_active_schools=total_active_schools,
            pending_admins=pending_admins
        )

    return render_template('public/master_login.html')


@public_bp.route('/_master_hq_2026/admins/<int:user_id>/accept', methods=['POST'])
@login_required
def accept_school_admin(user_id):
    if not _is_master_owner(current_user):
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
@login_required
def master_tenant_detail(tenant_id):
    if not _is_master_owner(current_user):
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


@public_bp.route('/_master_hq_2026/tenant/<int:tenant_id>/metrics')
@login_required
def master_tenant_metrics(tenant_id):
    if not _is_master_owner(current_user):
        abort(403)

    tenant = Tenant.query.filter_by(id=tenant_id).first_or_404()
    return jsonify({
        'school_id': tenant.id,
        'school_name': tenant.name,
        'school_prefix': tenant.school_prefix,
        'is_active': tenant.is_active,
        'billing_type': tenant.billing_type,
        'total_students': User.query.filter_by(tenant_id=tenant.id, role='student').count(),
        'total_teachers': User.query.filter_by(tenant_id=tenant.id, role='teacher').count(),
        'total_families': User.query.filter_by(tenant_id=tenant.id, role='parent').count(),
    })


@public_bp.route('/_master_hq_2026/tenant/<int:tenant_id>/billing', methods=['POST'])
@login_required
def update_tenant_billing(tenant_id):
    if not _is_master_owner(current_user):
        abort(403)

    tenant = Tenant.query.filter_by(id=tenant_id).first_or_404()
    billing_type = request.form.get('billing_type')
    if billing_type not in ['student_pay', 'school_pay']:
        flash('Invalid billing type.', 'error')
        return redirect(url_for('public.master_dashboard'))

    tenant.billing_type = billing_type
    tenant.school_prefix = (request.form.get('school_prefix') or tenant.school_prefix or 'SCH').strip().upper()[:12]
    tenant.is_active = request.form.get('is_active') == 'on'
    db.session.commit()
    flash(f'{tenant.name} billing and lock status updated.', 'success')
    return redirect(url_for('public.master_dashboard'))
