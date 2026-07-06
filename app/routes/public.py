from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, g
from flask_login import current_user, login_user
from werkzeug.security import check_password_hash
from app.models import Tenant, User

public_bp = Blueprint('public', __name__)


def _tenant_landing_context():
    if not getattr(g, 'current_tenant', None):
        return {}
    profile = Tenant.query.filter_by(id=g.current_tenant_id).first()
    return {'tenant': g.current_tenant, 'tenant_domain': g.current_domain, 'profile': getattr(g, 'current_tenant', None)}


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
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('public.master_dashboard'))

        flash('Invalid credentials.', 'error')
        return render_template('public/master_login.html')

    if current_user.is_authenticated and current_user.role == 'super_admin':
        tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
        tenant_data = []
        for tenant in tenants:
            students = User.query.filter_by(tenant_id=tenant.id, role='student').order_by(User.name).all()
            tenant_data.append({
                'tenant': tenant,
                'school_code': tenant.structured_code,
                'student_count': len(students),
                'students': students,
            })
        return render_template('public/master_dashboard.html', tenant_data=tenant_data)

    return render_template('public/master_login.html')
