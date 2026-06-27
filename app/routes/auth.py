from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from app.models import (
    AdmissionApplication,
    Class,
    ClassSubject,
    Parent,
    PaymentGatewaySetting,
    StudentClass,
    StudentTermAccess,
    StudentTermRegistration,
    Subject,
    TenantPublicProfile,
    Term,
    User,
)
from app import db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user authentication with multi-tenant data separation."""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Check if tenant context is set
        if not hasattr(g, 'current_tenant_id') or g.current_tenant_id is None:
            flash('System error: Tenant not found. Please contact administrator.', 'error')
            return render_template('login.html', admin_exists=False)
        
        # Query user by email AND current tenant ID for multi-tenant isolation
        user = User.query.filter_by(
            email=email,
            tenant_id=g.current_tenant_id
        ).first()
        
        # Validate credentials securely
        if user and check_password_hash(user.password_hash, password):
            login_user(user)

            if user.role == 'student' and _student_portal_is_locked(user):
                flash('Your portal is locked for this term until payment is confirmed.', 'error')
                return redirect(url_for('auth.portal_locked'))
            
            # Role-based redirect after successful login
            if user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
            elif user.role == 'teacher':
                return redirect(url_for('results.dashboard'))
            elif user.role == 'student':
                return redirect(url_for('auth.student_dashboard'))
            elif user.role == 'attendant':
                return redirect(url_for('attendance.dashboard'))
            elif user.role == 'parent':
                return redirect(url_for('auth.parent_dashboard'))
            else:
                return redirect(url_for('auth.login'))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('login.html', admin_exists=_admin_exists())

@auth_bp.route('/logout')
@login_required
def logout():
    """Log out the current user and redirect to login page."""
    logout_user()
    return redirect(url_for('auth.login'))

@auth_bp.route('/')
def index():
    """Home page / index route - shows landing page."""
    if current_user.is_authenticated:
        # Redirect to appropriate dashboard based on role
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        elif current_user.role == 'teacher':
            return redirect(url_for('results.dashboard'))
        elif current_user.role == 'student':
            return redirect(url_for('auth.student_dashboard'))
        elif current_user.role == 'attendant':
            return redirect(url_for('attendance.dashboard'))
        elif current_user.role == 'parent':
            return redirect(url_for('auth.parent_dashboard'))
    profile = TenantPublicProfile.query.filter_by(tenant_id=g.current_tenant_id).first()
    classes = Class.query.filter_by(tenant_id=g.current_tenant_id).order_by(Class.name).all()
    return render_template('landing.html', profile=profile, classes=classes)


def _student_portal_is_locked(user):
    payment_settings = PaymentGatewaySetting.query.filter_by(tenant_id=user.tenant_id).first()
    if payment_settings and not payment_settings.require_payment_for_portal:
        return False

    active_term = Term.query.filter_by(tenant_id=user.tenant_id, is_active=True).first()
    if not active_term:
        return False

    access = StudentTermAccess.query.filter_by(
        tenant_id=user.tenant_id,
        student_id=user.id,
        term_id=active_term.id
    ).first()

    if not access:
        access = StudentTermAccess(
            tenant_id=user.tenant_id,
            student_id=user.id,
            term_id=active_term.id,
            portal_unlocked=False,
            is_paid=False
        )
        db.session.add(access)
        db.session.commit()

    return not access.portal_unlocked


def _admin_exists():
    if not hasattr(g, 'current_tenant_id') or g.current_tenant_id is None:
        return False

    return User.query.filter_by(
        tenant_id=g.current_tenant_id,
        role='admin'
    ).first() is not None


@auth_bp.route('/admission/apply', methods=['GET', 'POST'])
def apply_admission():
    """Public admission application; does not create a portal account."""
    profile = TenantPublicProfile.query.filter_by(tenant_id=g.current_tenant_id).first()

    if profile and not profile.admission_open:
        flash('Admission application is currently closed.', 'error')
        return redirect(url_for('auth.index'))

    classes = Class.query.filter_by(tenant_id=g.current_tenant_id).order_by(Class.name).all()

    if request.method == 'POST':
        required = ['applicant_name', 'parent_name', 'parent_email', 'parent_phone']
        if not all(request.form.get(field, '').strip() for field in required):
            flash('Please complete all required fields.', 'error')
            return render_template('admission_apply.html', classes=classes)

        application = AdmissionApplication(
            tenant_id=g.current_tenant_id,
            applicant_name=request.form.get('applicant_name').strip(),
            parent_name=request.form.get('parent_name').strip(),
            parent_email=request.form.get('parent_email').strip().lower(),
            parent_phone=request.form.get('parent_phone').strip(),
            requested_class_id=request.form.get('requested_class_id') or None,
            previous_school=request.form.get('previous_school') or None,
            notes=request.form.get('notes') or None,
        )
        db.session.add(application)
        db.session.commit()

        flash('Admission application submitted. The school will review it and contact you.', 'success')
        return redirect(url_for('auth.index'))

    return render_template('admission_apply.html', classes=classes)


@auth_bp.route('/portal-locked')
@login_required
def portal_locked():
    payment_settings = PaymentGatewaySetting.query.filter_by(tenant_id=current_user.tenant_id).first()
    active_term = Term.query.filter_by(tenant_id=current_user.tenant_id, is_active=True).first()
    return render_template('portal_locked.html', payment_settings=payment_settings, active_term=active_term)


@auth_bp.route('/student/register-term', methods=['GET', 'POST'])
@login_required
def student_term_registration():
    """Returning student term registration with subject selection."""
    if current_user.role != 'student':
        flash('Only students can complete term registration.', 'error')
        return redirect(url_for('auth.index'))

    active_term = Term.query.filter_by(tenant_id=current_user.tenant_id, is_active=True).first()
    if not active_term:
        flash('No active term is available for registration.', 'error')
        return redirect(url_for('auth.index'))

    classes = Class.query.filter_by(tenant_id=current_user.tenant_id).order_by(Class.name).all()
    subjects = Subject.query.filter_by(tenant_id=current_user.tenant_id).order_by(Subject.name).all()
    class_subjects = ClassSubject.query.filter_by(tenant_id=current_user.tenant_id).all()

    subject_map = {}
    required_map = {}
    for item in class_subjects:
        subject_map.setdefault(item.class_id, set()).add(item.subject_id)
        if item.is_required:
            required_map.setdefault(item.class_id, set()).add(item.subject_id)

    if request.method == 'POST':
        class_id = request.form.get('class_id')
        selected_subject_ids = set(request.form.getlist('subject_ids'))

        if not class_id:
            flash('Please select your class.', 'error')
            return render_template(
                'student_term_registration.html',
                active_term=active_term,
                classes=classes,
                subjects=subjects,
                subject_map=subject_map,
                subject_map_json={map_class_id: list(subject_ids) for map_class_id, subject_ids in subject_map.items()},
                required_map=required_map,
                existing_subject_ids=set()
            )

        class_id_int = int(class_id)
        selected_subject_ids.update(str(subject_id) for subject_id in required_map.get(class_id_int, set()))

        if not selected_subject_ids:
            flash('Please select at least one subject.', 'error')
            return redirect(url_for('auth.student_term_registration'))

        existing_enrollment = StudentClass.query.filter_by(
            tenant_id=current_user.tenant_id,
            student_id=current_user.id,
            class_id=class_id_int,
            term_id=active_term.id
        ).first()
        if not existing_enrollment:
            db.session.add(StudentClass(
                tenant_id=current_user.tenant_id,
                student_id=current_user.id,
                class_id=class_id_int,
                term_id=active_term.id
            ))

        StudentTermRegistration.query.filter_by(
            tenant_id=current_user.tenant_id,
            student_id=current_user.id,
            term_id=active_term.id
        ).delete()

        for subject_id in selected_subject_ids:
            db.session.add(StudentTermRegistration(
                tenant_id=current_user.tenant_id,
                student_id=current_user.id,
                term_id=active_term.id,
                class_id=class_id_int,
                subject_id=int(subject_id),
                status='submitted'
            ))

        access = StudentTermAccess.query.filter_by(
            tenant_id=current_user.tenant_id,
            student_id=current_user.id,
            term_id=active_term.id
        ).first()
        if not access:
            access = StudentTermAccess(
                tenant_id=current_user.tenant_id,
                student_id=current_user.id,
                term_id=active_term.id,
                portal_unlocked=False,
                is_paid=False
            )
            db.session.add(access)

        db.session.commit()
        flash('Term registration submitted. Portal access will open after payment confirmation.', 'success')
        return redirect(url_for('auth.portal_locked'))

    existing_subject_ids = {
        item.subject_id for item in StudentTermRegistration.query.filter_by(
            tenant_id=current_user.tenant_id,
            student_id=current_user.id,
            term_id=active_term.id
        ).all()
    }

    return render_template(
        'student_term_registration.html',
        active_term=active_term,
        classes=classes,
        subjects=subjects,
        subject_map=subject_map,
        subject_map_json={class_id: list(subject_ids) for class_id, subject_ids in subject_map.items()},
        required_map=required_map,
        existing_subject_ids=existing_subject_ids
    )


@auth_bp.route('/student/dashboard')
@login_required
def student_dashboard():
    """Student dashboard route."""
    if _student_portal_is_locked(current_user):
        flash('Your portal is locked for this term until payment is confirmed.', 'error')
        return redirect(url_for('auth.portal_locked'))
    return render_template('dashboard.html')


@auth_bp.route('/parent/dashboard')
@login_required
def parent_dashboard():
    """Parent dashboard route."""
    if current_user.role != 'parent':
        flash('Only parents or guardians can access the parent dashboard.', 'error')
        return redirect(url_for('auth.index'))

    return render_template('dashboard.html')


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    """Handle user registration with role selection."""
    admin_exists = _admin_exists()

    if request.method == 'GET':
        return render_template('login.html', admin_exists=admin_exists)

    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')
    
    if not all([name, email, password, role]):
        flash('All fields are required', 'error')
        return render_template('login.html', admin_exists=admin_exists)
    
    if role not in ['admin', 'teacher', 'attendant', 'parent']:
        flash('Invalid role selected', 'error')
        return render_template('login.html', admin_exists=admin_exists)

    if role == 'admin' and admin_exists:
        flash('This school already has an admin. Ask the admin to create your account.', 'error')
        return render_template('login.html', admin_exists=admin_exists)
    
    # Check if tenant context is set
    if not hasattr(g, 'current_tenant_id') or g.current_tenant_id is None:
        flash('System error: Tenant not found. Please contact administrator.', 'error')
        return render_template('login.html', admin_exists=admin_exists)
    
    # Check if email already exists for this tenant
    existing = User.query.filter_by(
        tenant_id=g.current_tenant_id,
        email=email
    ).first()
    
    if existing:
        flash('Email already registered', 'error')
        return render_template('login.html', admin_exists=admin_exists)
    
    # Create new user
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
        db.session.add(Parent(
            tenant_id=g.current_tenant_id,
            user_id=user.id,
            phone=request.form.get('phone') or None,
            address=request.form.get('address') or None
        ))

    db.session.commit()
    
    flash('Account created successfully! Please sign in.', 'success')
    return redirect(url_for('auth.login'))
