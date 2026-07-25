from datetime import datetime
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from sqlalchemy import or_
from app.models import (
    AdmissionApplication,
    Class,
    ClassSubject,
    Course,
    CoursePurchase,
    LessonVideo,
    Parent,
    PaymentGatewaySetting,
    StudentClass,
    StudentTermAccess,
    StudentTermRegistration,
    Subject,
    TeacherAssignment,
    TenantPublicProfile,
    Term,
    User,
)
from app import db, mail
from app.auth_utils import ensure_custom_id, generate_temporary_password, password_matches, user_payment_locked
from app.auth_utils import live_room_name

auth_bp = Blueprint('auth', __name__)
LOCAL_ADMIN_ROLES = ('school_admin', 'admin', 'primary_admin', 'secondary_admin')

@auth_bp.before_request
def require_tenant_context():
    if request.endpoint in ['auth.forgot_id', 'auth.reset_password_request', 'auth.reset_password']:
        return
    if not getattr(g, 'current_tenant', None):
        abort(404)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle tenant-scoped email authentication with admin ID compatibility."""
    if request.method == 'POST':
        identifier = (request.form.get('email') or request.form.get('custom_id') or '').strip()
        password = request.form.get('password')
        
        # Check if tenant context is set
        if not hasattr(g, 'current_tenant_id') or g.current_tenant_id is None:
            flash('System error: Tenant not found. Please contact administrator.', 'error')
            return render_template('portal/login.html', admin_exists=False)
        
        if not g.current_tenant.is_active and g.current_tenant.billing_type == 'school_pay':
            flash('School Account Suspended - Please Contact Management', 'error')
            return render_template('portal/school_suspended.html', tenant=g.current_tenant), 403

        user = User.query.filter(
            User.tenant_id == g.current_tenant_id,
            or_(
                db.func.lower(User.email) == identifier.lower(),
                User.school_generated_id == identifier.upper(),
                User.custom_id == identifier.upper(),
            )
        ).first()

        if user and user_payment_locked(user, g.current_tenant):
            return _billing_lockout_response(user)

        # Validate credentials securely
        if user and password_matches(user, password):
            if not user.is_approved:
                flash('Your account application is still pending school approval.', 'error')
                return render_template('portal/login.html', admin_exists=_admin_exists())

            if user.is_first_login:
                session_payload = {'pending_user_id': user.id}
                from flask import session
                session['force_password_change'] = session_payload
                if request.accept_mimetypes.best == 'application/json' or request.is_json:
                    return jsonify({
                        'status': 'force_password_change',
                        'custom_id': user.school_generated_id or user.custom_id,
                        'message': 'Password change required before dashboard access.'
                    }), 200
                return render_template(
                    'portal/force_password_change.html',
                    custom_id=user.school_generated_id or user.custom_id,
                    status='force_password_change'
                ), 200

            login_user(user)

            if user.role == 'student' and _student_portal_is_locked(user):
                flash('Your portal is locked for this term until payment is confirmed.', 'error')
                return redirect(url_for('auth.portal_locked'))
            
            return redirect(_role_redirect(user))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('portal/login.html', admin_exists=_admin_exists())


def _billing_lockout_response(user):
    payload = {
        'status': 'payment_required',
        'message': 'Payment Required',
        'custom_id': user.custom_id,
    }
    if request.accept_mimetypes.best == 'application/json' or request.is_json:
        return jsonify(payload), 402
    flash('Payment Required', 'error')
    return render_template('portal/payment_required.html', payload=payload), 402


@auth_bp.route('/change-password', methods=['POST'])
@auth_bp.route('/auth/change-password', methods=['POST'])
def change_password():
    """Persist the first secure password and disable first-name login forever."""
    from flask import session

    pending = session.get('force_password_change') or {}
    user = User.query.filter_by(
        id=pending.get('pending_user_id'),
        tenant_id=g.current_tenant_id
    ).first()
    if not user:
        flash('Password reset session expired. Please sign in again.', 'error')
        return redirect(url_for('auth.login'))

    password = request.form.get('password') or ''
    confirm_password = request.form.get('confirm_password') or ''
    if len(password) < 8 or password != confirm_password:
        flash('Use a matching password with at least 8 characters.', 'error')
        return render_template('portal/force_password_change.html', custom_id=user.custom_id), 400

    if password.lower() == user.first_name.lower():
        flash('Choose a password that is not your first name.', 'error')
        return render_template('portal/force_password_change.html', custom_id=user.custom_id), 400

    user.set_password(password)
    user.is_first_login = False
    db.session.commit()
    session.pop('force_password_change', None)
    login_user(user)
    flash('Password saved. Your account is now secured.', 'success')
    return redirect(_role_redirect(user))


@auth_bp.route('/setup-wizard')
@login_required
def setup_wizard_redirect():
    if current_user.role not in LOCAL_ADMIN_ROLES:
        abort(403)
    return redirect(url_for('admin.setup_wizard'))


@auth_bp.route('/initial-setup', methods=['POST'])
def initial_setup():
    """Create the first tenant admin from the public setup wizard."""
    tenant = getattr(g, 'current_tenant', None)
    if not tenant:
        abort(404)

    if _admin_exists():
        flash('This school already has an administrator. Please sign in.', 'info')
        return redirect(url_for('auth.login'))

    admin_name = (request.form.get('admin_name') or '').strip()
    admin_email = (request.form.get('admin_email') or '').strip().lower()
    admin_password = request.form.get('admin_password') or ''
    confirm_password = request.form.get('confirm_password') or ''
    school_name = (request.form.get('school_name') or tenant.name or '').strip()
    primary_color = (request.form.get('primary_color') or tenant.primary_color or '#3498db').strip()
    secondary_color = (request.form.get('secondary_color') or tenant.secondary_color or '#2ecc71').strip()

    color_pattern = re.compile(r'^#[0-9a-fA-F]{6}$')
    if not all([admin_name, admin_email, admin_password, confirm_password, school_name]):
        flash('Please complete every setup field.', 'error')
        return render_template('portal/login.html', admin_exists=False), 400
    if len(admin_password) < 8 or admin_password != confirm_password:
        flash('Use a matching admin password with at least 8 characters.', 'error')
        return render_template('portal/login.html', admin_exists=False), 400
    if not color_pattern.match(primary_color) or not color_pattern.match(secondary_color):
        flash('Choose valid primary and secondary colors.', 'error')
        return render_template('portal/login.html', admin_exists=False), 400

    existing = User.query.filter_by(
        tenant_id=g.current_tenant_id,
        email=admin_email
    ).first()
    if existing:
        flash('That email is already registered for this school.', 'error')
        return render_template('portal/login.html', admin_exists=False), 400

    tenant.name = school_name
    tenant.primary_color = primary_color
    tenant.secondary_color = secondary_color
    tenant.setup_completed = True
    tenant.application_contact_name = tenant.application_contact_name or admin_name
    tenant.application_contact_email = tenant.application_contact_email or admin_email

    admin = User(
        tenant_id=g.current_tenant_id,
        name=admin_name,
        email=admin_email,
        role='school_admin',
        is_approved=True,
        is_first_login=False,
        payment_status='paid',
    )
    ensure_custom_id(admin, tenant, datetime.utcnow())
    admin.set_password(admin_password)

    db.session.add(admin)
    db.session.commit()

    flash(f'School setup completed. Your admin ID is {admin.custom_id}. Please sign in.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-id', methods=['GET', 'POST'])
@auth_bp.route('/auth/forgot-id', methods=['GET', 'POST'])
def forgot_id():
    """Recover a plaintext custom ID using tenant and registered contact detail."""
    if request.method == 'POST':
        school_id = request.form.get('school_id') or g.current_tenant_id
        contact = (request.form.get('contact') or '').strip().lower()
        if not school_id or not contact:
            flash('School ID and registered contact are required.', 'error')
            return render_template('portal/forgot_id.html'), 400
        query = User.query.filter(User.tenant_id == school_id)
        user = query.filter(
            or_(
                db.func.lower(User.email) == contact,
                db.func.lower(User.phone_number) == contact
            )
        ).first()
        if user:
            return render_template('portal/forgot_id.html', recovered_custom_id=user.custom_id)
        flash('No account matched that school and contact detail.', 'error')
    return render_template('portal/forgot_id.html')


@auth_bp.route('/reset_password_request', methods=['GET', 'POST'])
@auth_bp.route('/auth/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    """Handle password reset request by email."""
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if not email:
            flash('Please provide your email address.', 'error')
            return render_template('portal/reset_request.html'), 400
        
        from flask import current_app
        app = current_app._get_current_object()
        tenant = getattr(g, 'current_tenant', None)
        
        # Entry logging
        app.logger.info(f"[RESET LOG] Password reset requested for email: '{email}' on Tenant ID: {tenant.id if tenant else 'None'}")
        
        try:
            user = User.query.filter(db.func.lower(User.email) == email).first()
            if user:
                token = user.get_reset_token()
                reset_url = url_for('auth.reset_password', token=token, _external=True)
                
                from datetime import datetime
                import threading
                
                recipient = user.email
                tenant_data = tenant
                
                def send_reset_email():
                    """Send password reset email in background thread."""
                    try:
                        with app.app_context():
                            msg = Message(
                                subject='Password Reset Request',
                                recipients=[recipient],
                                sender=app.config.get('MAIL_DEFAULT_SENDER', 'admin@turnjoylms.com.ng')
                            )
                            msg.html = render_template(
                                'email/reset_password_email.html',
                                user=user,
                                reset_url=reset_url,
                                tenant=tenant_data,
                                current_year=datetime.now().year
                            )
                            mail.send(msg)
                            app.logger.info(f"[BREVO SMTP SUCCESS] Reset email successfully dispatched to {recipient}")
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        app.logger.error(f"[BREVO SMTP ERROR] Failed to send email to {recipient}: {e}")
                
                # Log thread spawning
                app.logger.info(f"[RESET LOG] Spawning background thread to send reset email to '{email}'...")
                
                # Start email sending in background thread
                email_thread = threading.Thread(target=send_reset_email)
                email_thread.daemon = True
                email_thread.start()
                
                flash('A password reset link has been sent to your email. Check your inbox.', 'success')
                return redirect(url_for('auth.login'))
            else:
                app.logger.warning(f"[RESET LOG] No user found matching email '{email}' for tenant '{tenant.name if tenant else 'Unknown'}'. Skipping email send.")
                flash('If an account with that email exists, a reset link has been sent.', 'info')
        except Exception as e:
            import traceback
            traceback.print_exc()
            current_app.logger.error(f'Password reset request failed: {str(e)}')
            flash('An error occurred. Please try again later.', 'error')
    
    return render_template('portal/reset_request.html')


@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
@auth_bp.route('/auth/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Handle password reset with valid token."""
    try:
        user = User.verify_reset_token(token)
        if not user:
            flash('Invalid or expired reset link. Please request a new one.', 'error')
            return redirect(url_for('auth.reset_password_request'))
        
        if request.method == 'POST':
            password = request.form.get('password') or ''
            confirm_password = request.form.get('confirm_password') or ''
            
            if len(password) < 8:
                flash('Password must be at least 8 characters long.', 'error')
                return render_template('portal/reset_password.html', token=token), 400
            
            if password != confirm_password:
                flash('Passwords do not match.', 'error')
                return render_template('portal/reset_password.html', token=token), 400
            
            user.set_password(password)
            user.is_first_login = False
            db.session.commit()
            
            flash('Your password has been reset successfully. Please sign in.', 'success')
            return redirect(url_for('auth.login'))
        
        return render_template('portal/reset_password.html', token=token)
    except Exception as e:
        import traceback
        traceback.print_exc()
        current_app.logger.error(f'Password reset failed: {str(e)}')
        flash('An error occurred while resetting your password. Please try again.', 'error')
        return redirect(url_for('auth.reset_password_request'))


def _role_redirect(user):
    if user.role in LOCAL_ADMIN_ROLES:
        return url_for('admin.dashboard')
    if user.role == 'teacher':
        return url_for('results.dashboard')
    if user.role == 'student':
        return url_for('auth.student_dashboard')
    if user.role == 'attendant':
        return url_for('attendance.dashboard')
    if user.role == 'parent':
        return url_for('auth.parent_dashboard')
    return url_for('auth.login')

@auth_bp.route('/logout')
@login_required
def logout():
    """Log out the current user and redirect to login page."""
    logout_user()
    return redirect(url_for('auth.login'))



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

    return User.query.filter(
        User.tenant_id == g.current_tenant_id,
        User.role.in_(LOCAL_ADMIN_ROLES)
    ).first() is not None


def _student_has_course_access(course_id):
    if not current_user.is_authenticated:
        return False
    if current_user.role in LOCAL_ADMIN_ROLES or current_user.role == 'teacher':
        return True
    if getattr(g.current_tenant, 'tenant_type', 'formal_school') == 'formal_school' and current_user.role == 'student':
        return True
    return CoursePurchase.query.filter_by(
        tenant_id=g.current_tenant_id,
        course_id=course_id,
        student_id=current_user.id,
        status='completed'
    ).first() is not None


@auth_bp.route('/admission/apply', methods=['GET', 'POST'])
def apply_admission():
    """Public self-service application for students, teachers, and parents."""
    profile = TenantPublicProfile.query.filter_by(tenant_id=g.current_tenant_id).first()

    if profile and not profile.admission_open:
        flash('Admission application is currently closed.', 'error')
        return redirect(url_for('auth.login'))

    classes = Class.query.filter_by(tenant_id=g.current_tenant_id).order_by(Class.name).all()
    subjects = Subject.query.filter_by(tenant_id=g.current_tenant_id).order_by(Subject.name).all()
    
    # Build class-to-subject mapping for teacher applications
    class_subjects = ClassSubject.query.filter_by(tenant_id=g.current_tenant_id).all()
    class_subject_map = {}
    for item in class_subjects:
        class_subject_map.setdefault(str(item.class_id), []).append(item.subject_id)
    
    # Build class level to arms mapping for teacher applications
    from app.models import ClassArm
    class_arms = ClassArm.query.filter_by(tenant_id=g.current_tenant_id).all()
    class_level_arm_map = {}
    for arm in class_arms:
        class_level_arm_map.setdefault(str(arm.class_level_id), []).append({
            'id': arm.id,
            'name': arm.name
        })

    if request.method == 'POST':
        applicant_role = (request.form.get('applicant_role') or 'student').strip().lower()
        applicant_name = (request.form.get('applicant_name') or '').strip()
        applicant_email = (request.form.get('applicant_email') or '').strip().lower()
        applicant_phone = (request.form.get('applicant_phone') or '').strip()
        requested_subject_ids = [
            int(subject_id)
            for subject_id in request.form.getlist('subject_ids')
            if subject_id.isdigit()
        ]

        if applicant_role not in ('student', 'teacher', 'parent'):
            flash('Choose Student, Teacher, or Parent before submitting.', 'error')
            return render_template('portal/admission_apply.html', classes=classes, subjects=subjects, class_subject_map=class_subject_map, class_level_arm_map=class_level_arm_map), 400

        required_ok = bool(applicant_name)
        if applicant_role == 'student':
            required_ok = required_ok and bool(request.form.get('requested_class_id')) and bool(request.form.get('parent_phone'))
        elif applicant_role == 'teacher':
            teacher_section = request.form.get('teacher_section')
            teacher_class = request.form.get('teacher_class')
            required_ok = required_ok and bool(applicant_email) and bool(applicant_phone) and bool(teacher_section) and bool(teacher_class) and bool(requested_subject_ids)
        elif applicant_role == 'parent':
            required_ok = required_ok and bool(applicant_phone) and bool(request.form.get('child_lookup'))

        if not required_ok:
            flash('Please complete all required fields.', 'error')
            return render_template('portal/admission_apply.html', classes=classes, subjects=subjects, class_subject_map=class_subject_map, class_level_arm_map=class_level_arm_map), 400

        if applicant_email and User.query.filter_by(tenant_id=g.current_tenant_id, email=applicant_email).first():
            flash('That email is already registered for this school.', 'error')
            return render_template('portal/admission_apply.html', classes=classes, subjects=subjects, class_subject_map=class_subject_map, class_level_arm_map=class_level_arm_map), 400

        valid_subject_ids = {subject.id for subject in subjects}
        requested_subject_ids = [subject_id for subject_id in requested_subject_ids if subject_id in valid_subject_ids]
        if applicant_role == 'teacher' and not requested_subject_ids:
            flash('Choose at least one registered school subject.', 'error')
            return render_template('portal/admission_apply.html', classes=classes, subjects=subjects, class_subject_map=class_subject_map, class_level_arm_map=class_level_arm_map), 400

        user = User(
            tenant_id=g.current_tenant_id,
            name=applicant_name,
            email=applicant_email or None,
            phone_number=applicant_phone or request.form.get('parent_phone') or None,
            role=applicant_role,
            is_approved=False,
            is_first_login=True,
            payment_status='unpaid' if applicant_role in ('student', 'parent') else 'paid',
        )
        ensure_custom_id(user, g.current_tenant, datetime.utcnow())
        db.session.add(user)
        db.session.flush()

        application = AdmissionApplication(
            tenant_id=g.current_tenant_id,
            applicant_role=applicant_role,
            applicant_name=applicant_name,
            applicant_email=applicant_email or None,
            applicant_phone=applicant_phone or None,
            parent_name=(request.form.get('parent_name') or applicant_name).strip(),
            parent_email=(request.form.get('parent_email') or applicant_email or '').strip().lower(),
            parent_phone=(request.form.get('parent_phone') or applicant_phone).strip(),
            requested_class_id=request.form.get('requested_class_id') or (request.form.get('teacher_class') or None),
            teacher_section=request.form.get('teacher_section') or None,
            teacher_arm=request.form.get('teacher_arm') or None,
            requested_subject_ids=requested_subject_ids or None,
            child_lookup=(request.form.get('child_lookup') or '').strip() or None,
            previous_school=request.form.get('previous_school') or None,
            notes=request.form.get('notes') or None,
            created_user_id=user.id,
            created_student_id=user.id if applicant_role == 'student' else None,
        )
        db.session.add(application)
        db.session.commit()

        flash('Application submitted. The school admin will review it from the Application Desk.', 'success')
        return redirect(url_for('public.index'))

    return render_template('portal/admission_apply.html', classes=classes, subjects=subjects, class_subject_map=class_subject_map, class_level_arm_map=class_level_arm_map)


@auth_bp.route('/courses')
@login_required
def course_library():
    courses = Course.query.filter_by(tenant_id=g.current_tenant_id, is_active=True).order_by(Course.created_at.desc()).all()
    purchases = CoursePurchase.query.filter_by(
        tenant_id=g.current_tenant_id,
        student_id=current_user.id,
        status='completed'
    ).all() if current_user.role == 'student' else []
    purchased_course_ids = {purchase.course_id for purchase in purchases}
    if getattr(g.current_tenant, 'tenant_type', 'formal_school') == 'formal_school':
        purchased_course_ids = {course.id for course in courses}
    return render_template('portal/course_library.html', courses=courses, purchased_course_ids=purchased_course_ids)


@auth_bp.route('/courses/<int:course_id>')
@login_required
def course_detail(course_id):
    course = Course.query.filter_by(id=course_id, tenant_id=g.current_tenant_id, is_active=True).first_or_404()
    if not _student_has_course_access(course.id):
        flash('Buy this course to unlock the lesson studio.', 'error')
        return redirect(url_for('auth.course_library'))
    lessons = LessonVideo.query.filter_by(tenant_id=g.current_tenant_id, course_id=course.id).order_by(
        LessonVideo.sort_order,
        LessonVideo.created_at
    ).all()
    return render_template('portal/course_detail.html', course=course, lessons=lessons)


@auth_bp.route('/portal-locked')
@login_required
def portal_locked():
    payment_settings = PaymentGatewaySetting.query.filter_by(tenant_id=current_user.tenant_id).first()
    active_term = Term.query.filter_by(tenant_id=current_user.tenant_id, is_active=True).first()
    return render_template('portal/portal_locked.html', payment_settings=payment_settings, active_term=active_term)


@auth_bp.route('/student/register-term', methods=['GET', 'POST'])
@login_required
def student_term_registration():
    """Returning student term registration with subject selection."""
    if current_user.role != 'student':
        flash('Only students can complete term registration.', 'error')
        return redirect(url_for('auth.login'))

    active_term = Term.query.filter_by(tenant_id=current_user.tenant_id, is_active=True).first()
    if not active_term:
        flash('No active term is available for registration.', 'error')
        return redirect(url_for('auth.login'))

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
            'portal/student_term_registration.html',
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
        'portal/student_term_registration.html',
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
    enrollments = StudentClass.query.filter_by(
        tenant_id=current_user.tenant_id,
        student_id=current_user.id
    ).all()
    return render_template('portal/dashboard.html', student_enrollments=enrollments)


@auth_bp.route('/parent/dashboard')
@login_required
def parent_dashboard():
    """Parent dashboard route."""
    if current_user.role != 'parent':
        flash('Only parents or guardians can access the parent dashboard.', 'error')
        return redirect(url_for('auth.login'))

    return render_template('portal/dashboard.html')


@auth_bp.route('/class/<int:class_id>/live')
@login_required
def live_classroom(class_id):
    """Embed a private Jitsi classroom for validated teachers and students."""
    if current_user.role not in ['teacher', 'student']:
        abort(403)

    class_obj = Class.query.filter_by(id=class_id, tenant_id=g.current_tenant_id).first_or_404()
    if current_user.role == 'teacher':
        allowed = TeacherAssignment.query.filter_by(
            tenant_id=g.current_tenant_id,
            teacher_id=current_user.id,
            class_id=class_id
        ).first()
    else:
        allowed = StudentClass.query.filter_by(
            tenant_id=g.current_tenant_id,
            student_id=current_user.id,
            class_id=class_id
        ).first()

    if not allowed:
        abort(403)

    return render_template(
        'portal/live_classroom.html',
        class_obj=class_obj,
        room_name=live_room_name(g.current_tenant_id, class_id),
        display_name=current_user.name
    )


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    """Handle user registration with role selection."""
    admin_exists = _admin_exists()

    if request.method == 'GET':
        return render_template('portal/login.html', admin_exists=admin_exists)

    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')
    
    if not all([name, email, password, role]):
        flash('All fields are required', 'error')
        return render_template('portal/login.html', admin_exists=admin_exists)
    
    if role not in ['admin', 'primary_admin', 'secondary_admin', 'teacher', 'attendant', 'parent']:
        flash('Invalid role selected', 'error')
        return render_template('portal/login.html', admin_exists=admin_exists)
    
    # Check if tenant context is set
    if not hasattr(g, 'current_tenant_id') or g.current_tenant_id is None:
        flash('System error: Tenant not found. Please contact administrator.', 'error')
        return render_template('portal/login.html', admin_exists=admin_exists)
    existing = User.query.filter_by(
        tenant_id=g.current_tenant_id,
        email=email
    ).first()
    
    if existing:
        flash('Email already registered', 'error')
        return render_template('portal/login.html', admin_exists=admin_exists)
    
    # Create new user
    user = User(
        tenant_id=g.current_tenant_id,
        name=name,
        email=email,
        phone_number=request.form.get('phone') or None,
        role=role,
        section='primary' if role == 'primary_admin' else ('secondary' if role == 'secondary_admin' else None),
        is_approved=role not in LOCAL_ADMIN_ROLES,
        is_first_login=False,
        payment_status='paid' if role not in ['student', 'parent'] else 'unpaid'
    )
    ensure_custom_id(user, g.current_tenant, datetime.utcnow())
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
    
    if role in LOCAL_ADMIN_ROLES:
        flash(f'School admin account created. Your ID is {user.custom_id}. It is pending Turnjoy owner approval before login.', 'success')
    else:
        flash(f'Account created successfully. Your ID is {user.custom_id}. Please sign in.', 'success')
    return redirect(url_for('auth.login'))
