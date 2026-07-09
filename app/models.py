from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy.ext.hybrid import hybrid_property
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Tenant(db.Model):
    """Represents a school/tenant in the multi-tenant system."""
    __tablename__ = 'tenants'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subdomain = db.Column(db.String(50), unique=True, nullable=False, index=True)
    custom_domain = db.Column(db.String(255), unique=True, index=True)
    logo_url = db.Column(db.String(255))
    primary_color = db.Column(db.String(7), default='#3498db')
    secondary_color = db.Column(db.String(7), default='#2ecc71')
    sections = db.Column(db.String(20), default='both')  # primary, secondary, both
    sss_tracks = db.Column(db.String(120), default='Science,Humanities,Commercial')
    school_prefix = db.Column(db.String(12), nullable=False, default='SCH')
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    application_website = db.Column(db.String(255))
    application_contact_name = db.Column(db.String(120))
    application_contact_email = db.Column(db.String(120), index=True)
    application_contact_phone = db.Column(db.String(30))
    application_note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    billing_type = db.Column(db.String(20), default='school_pay', nullable=False)
    setup_completed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def structured_code(self):
        year = self.created_at.year if self.created_at else datetime.utcnow().year
        prefix = self.name.split()[0].upper() if self.name else 'SCH'
        return f'{prefix}/{year}/{self.id:03d}'
    
    # Relationships
    users = db.relationship('User', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')
    classes = db.relationship('Class', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')
    subjects = db.relationship('Subject', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')
    terms = db.relationship('Term', backref='tenant', lazy='dynamic', cascade='all, delete-orphan')
    ai_settings = db.relationship('TenantAISetting', backref='tenant', uselist=False, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Tenant {self.name}>'


class TenantAISetting(db.Model):
    """Stores school-specific AI configuration for a tenant."""
    __tablename__ = 'tenant_ai_settings'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, unique=True, index=True)
    provider = db.Column(db.String(50), default='openai')
    model_name = db.Column(db.String(100), default='gpt-4o-mini')
    assistant_name = db.Column(db.String(100), default='School AI Assistant')
    system_prompt = db.Column(db.Text)
    enabled_for_teachers = db.Column(db.Boolean, default=True)
    enabled_for_students = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<TenantAISetting {self.tenant_id} {self.provider}:{self.model_name}>'


class TenantPublicProfile(db.Model):
    """Public homepage content for each school."""
    __tablename__ = 'tenant_public_profiles'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, unique=True, index=True)
    headline = db.Column(db.String(160), default='Welcome to our school')
    about = db.Column(db.Text)
    admission_message = db.Column(db.Text)
    admission_open = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('Tenant', backref=db.backref('public_profile', uselist=False, cascade='all, delete-orphan'))


class PaymentGatewaySetting(db.Model):
    """School-specific payment gateway configuration."""
    __tablename__ = 'payment_gateway_settings'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, unique=True, index=True)
    provider = db.Column(db.String(50), default='manual')
    public_key = db.Column(db.String(255))
    secret_key = db.Column(db.String(255))
    currency = db.Column(db.String(10), default='NGN')
    payment_instructions = db.Column(db.Text)
    require_payment_for_portal = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('Tenant', backref=db.backref('payment_settings', uselist=False, cascade='all, delete-orphan'))


class AdmissionApplication(db.Model):
    """Public admission request reviewed by a school admin."""
    __tablename__ = 'admission_applications'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    applicant_name = db.Column(db.String(120), nullable=False)
    parent_name = db.Column(db.String(120), nullable=False)
    parent_email = db.Column(db.String(120), nullable=False, index=True)
    parent_phone = db.Column(db.String(30), nullable=False)
    requested_class_id = db.Column(db.Integer, db.ForeignKey('classes.id'))
    previous_school = db.Column(db.String(160))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending', index=True)
    admin_note = db.Column(db.Text)
    created_student_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)

    tenant = db.relationship('Tenant', backref='admission_applications')
    requested_class = db.relationship('Class')
    created_student = db.relationship('User', foreign_keys=[created_student_id])


class StudentTermAccess(db.Model):
    """Controls whether a student can open the portal for a term."""
    __tablename__ = 'student_term_access'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey('terms.id'), nullable=False)
    amount_due = db.Column(db.Float, default=0.0)
    amount_paid = db.Column(db.Float, default=0.0)
    is_paid = db.Column(db.Boolean, default=False)
    portal_unlocked = db.Column(db.Boolean, default=False)
    payment_reference = db.Column(db.String(120))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = db.relationship('User', foreign_keys=[student_id])
    term = db.relationship('Term')

    __table_args__ = (
        db.UniqueConstraint('student_id', 'term_id', name='unique_student_term_access'),
    )


class FeeCategory(db.Model):
    """School-owned fee categories, never configured by the platform owner."""
    __tablename__ = 'fee_categories'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='fee_categories')
    installment_plans = db.relationship('FeeInstallmentPlan', backref='fee_category', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'name', name='unique_tenant_fee_category'),
    )


class FeeInstallmentPlan(db.Model):
    """Class/tier fee plan controlled by local school admins."""
    __tablename__ = 'fee_installment_plans'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    fee_category_id = db.Column(db.Integer, db.ForeignKey('fee_categories.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'))
    term_id = db.Column(db.Integer, db.ForeignKey('terms.id'))
    amount = db.Column(db.Float, default=0.0)
    installments_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='fee_installment_plans')
    class_obj = db.relationship('Class')
    term = db.relationship('Term')
    milestones = db.relationship('FeeInstallmentMilestone', backref='plan', lazy='dynamic', cascade='all, delete-orphan')


class FeeInstallmentMilestone(db.Model):
    """Percentage and deadline milestone for installment billing."""
    __tablename__ = 'fee_installment_milestones'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('fee_installment_plans.id'), nullable=False)
    label = db.Column(db.String(80), nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PaymentTransaction(db.Model):
    """Webhook-backed payment ledger for live balances."""
    __tablename__ = 'payment_transactions'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey('terms.id'))
    provider = db.Column(db.String(40), nullable=False)
    reference = db.Column(db.String(120), nullable=False, index=True)
    amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(30), default='pending')
    raw_payload = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='payment_transactions')
    student = db.relationship('User', foreign_keys=[student_id])
    term = db.relationship('Term')

    __table_args__ = (
        db.UniqueConstraint('provider', 'reference', name='unique_payment_provider_reference'),
    )


class SchoolSetupPreference(db.Model):
    """Stores guided setup choices for a tenant."""
    __tablename__ = 'school_setup_preferences'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, unique=True, index=True)
    setup_mode = db.Column(db.String(20), default='hybrid')  # automatic or hybrid
    school_type = db.Column(db.String(30), default='combined')
    sections = db.Column(db.JSON)
    arms = db.Column(db.JSON)
    sss_tracks = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('Tenant', backref=db.backref('setup_preference', uselist=False, cascade='all, delete-orphan'))


class ClassSubject(db.Model):
    """Subjects offered by a class for student term registration."""
    __tablename__ = 'class_subjects'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    is_required = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    class_obj = db.relationship('Class')
    subject = db.relationship('Subject')

    __table_args__ = (
        db.UniqueConstraint('class_id', 'subject_id', name='unique_class_subject'),
    )


class StudentTermRegistration(db.Model):
    """Subjects selected by a returning student for a term."""
    __tablename__ = 'student_term_registrations'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey('terms.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    status = db.Column(db.String(20), default='submitted')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('User', foreign_keys=[student_id])
    term = db.relationship('Term')
    class_obj = db.relationship('Class')
    subject = db.relationship('Subject')

    __table_args__ = (
        db.UniqueConstraint('student_id', 'term_id', 'subject_id', name='unique_student_term_subject'),
    )


class User(UserMixin, db.Model):
    """Represents a user in the system with role-based access."""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    custom_id = db.Column(db.String(40), unique=True, index=True)
    school_generated_id = db.Column(db.String(40), unique=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=True, index=True)
    phone_number = db.Column(db.String(30), index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    is_first_login = db.Column(db.Boolean, default=True, nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'super_admin', 'school_admin', 'admin', 'primary_admin', 'secondary_admin', 'teacher', 'student', 'attendant', 'parent'
    payment_status = db.Column(db.String(20), default='unpaid', nullable=False)
    section = db.Column(db.String(20), default=None)  # 'primary', 'secondary', or None for global roles
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    teacher_assignments = db.relationship('TeacherAssignment', backref='teacher', lazy='dynamic', cascade='all, delete-orphan')
    student_classes = db.relationship('StudentClass', backref='student', lazy='dynamic', cascade='all, delete-orphan')
    attendance_records = db.relationship('Attendance', foreign_keys='Attendance.marked_by', backref='marker', lazy='dynamic')
    student_attendance = db.relationship('Attendance', foreign_keys='Attendance.student_id', backref='student_attendance', lazy='dynamic')
    results_inputted = db.relationship('Result', foreign_keys='Result.inputted_by', backref='inputter', lazy='dynamic')
    student_results = db.relationship('Result', foreign_keys='Result.student_id', backref='student_result', lazy='dynamic')
    
    # Parent relationship (if user is a parent)
    children_associations = db.relationship('StudentParent', backref='parent', lazy='dynamic', cascade='all, delete-orphan')
    
    def set_password(self, password):
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify the user's password."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def first_name(self):
        return (self.name or '').strip().split()[0] if (self.name or '').strip() else ''
    
    def __repr__(self):
        return f'<User {self.name} ({self.role})>'


class ClassLevel(db.Model):
    """Base class/grade level owned by one tenant, e.g. Primary 1 or JSS 1."""
    __tablename__ = 'class_levels'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)
    category = db.Column(db.String(20), nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='class_levels')
    arms = db.relationship('ClassArm', backref='class_level', lazy='dynamic', cascade='all, delete-orphan')
    classes = db.relationship('Class', backref='class_level', lazy='dynamic')
    subjects = db.relationship('Subject', backref='class_level', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'name', name='unique_tenant_class_level'),
    )

    def __repr__(self):
        return f'<ClassLevel {self.name}>'


class ClassArm(db.Model):
    """A class stream/section under a base level, e.g. A, Gold, or Diamond."""
    __tablename__ = 'class_arms'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    class_level_id = db.Column(db.Integer, db.ForeignKey('class_levels.id'), nullable=False, index=True)
    name = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='class_arms')
    classes = db.relationship('Class', backref='class_arm', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'class_level_id', 'name', name='unique_tenant_class_arm'),
    )

    def __repr__(self):
        return f'<ClassArm {self.name}>'


class Class(db.Model):
    """Represents a class/grade in a school."""
    __tablename__ = 'classes'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    class_level_id = db.Column(db.Integer, db.ForeignKey('class_levels.id'), index=True)
    class_arm_id = db.Column(db.Integer, db.ForeignKey('class_arms.id'), index=True)
    name = db.Column(db.String(50), nullable=False)
    section = db.Column(db.String(20), index=True)
    arm = db.Column(db.String(40), index=True)
    track = db.Column(db.String(30), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    student_classes = db.relationship('StudentClass', backref='class_obj', lazy='dynamic', cascade='all, delete-orphan')
    teacher_assignments = db.relationship('TeacherAssignment', backref='class_obj', lazy='dynamic', cascade='all, delete-orphan')
    attendance_records = db.relationship('Attendance', backref='class_obj', lazy='dynamic', cascade='all, delete-orphan')
    results = db.relationship('Result', backref='class_obj', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Class {self.name}>'


class Subject(db.Model):
    """Represents a subject taught in the school."""
    __tablename__ = 'subjects'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    class_level_id = db.Column(db.Integer, db.ForeignKey('class_levels.id'), index=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    teacher_assignments = db.relationship('TeacherAssignment', backref='subject', lazy='dynamic', cascade='all, delete-orphan')
    results = db.relationship('Result', backref='subject', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Subject {self.name}>'


class Term(db.Model):
    """Represents an academic term/session."""
    __tablename__ = 'terms'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)
    session = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    student_classes = db.relationship('StudentClass', backref='term', lazy='dynamic', cascade='all, delete-orphan')
    teacher_assignments = db.relationship('TeacherAssignment', backref='term', lazy='dynamic', cascade='all, delete-orphan')
    results = db.relationship('Result', backref='term', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Term {self.name} - {self.session}>'


class StudentClass(db.Model):
    """Many-to-many relationship between students and classes for a specific term."""
    __tablename__ = 'student_classes'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey('terms.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint to prevent duplicate enrollments
    __table_args__ = (
        db.UniqueConstraint('student_id', 'class_id', 'term_id', name='unique_student_class_term'),
    )
    
    def __repr__(self):
        return f'<StudentClass Student:{self.student_id} Class:{self.class_id} Term:{self.term_id}>'


class TeacherAssignment(db.Model):
    """Assigns teachers to teach specific subjects in specific classes for a term."""
    __tablename__ = 'teacher_assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey('terms.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint to prevent duplicate assignments
    __table_args__ = (
        db.UniqueConstraint('teacher_id', 'class_id', 'subject_id', 'term_id', name='unique_teacher_assignment'),
    )
    
    def __repr__(self):
        return f'<TeacherAssignment Teacher:{self.teacher_id} Class:{self.class_id} Subject:{self.subject_id}>'


class Parent(db.Model):
    """Represents a parent/guardian."""
    __tablename__ = 'parents'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='parent_profile', foreign_keys=[user_id])
    student_associations = db.relationship('StudentParent', backref='parent_user', lazy='dynamic', cascade='all, delete-orphan')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', name='unique_parent_user'),
    )
    
    def __repr__(self):
        return f'<Parent {self.user_id}>'


class StudentParent(db.Model):
    """Many-to-many relationship between students and parents."""
    __tablename__ = 'student_parents'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('parents.id'), nullable=False)
    relationship = db.Column(db.String(20), default='parent')  # 'father', 'mother', 'guardian'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint to prevent duplicate relationships
    __table_args__ = (
        db.UniqueConstraint('student_id', 'parent_id', name='unique_student_parent'),
    )
    
    def __repr__(self):
        return f'<StudentParent Student:{self.student_id} Parent:{self.parent_id}>'


class Attendance(db.Model):
    """Records student attendance."""
    __tablename__ = 'attendance'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False)  # 'present', 'absent', 'late', 'excused'
    marked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint to prevent duplicate attendance records
    __table_args__ = (
        db.UniqueConstraint('student_id', 'class_id', 'date', name='unique_attendance_record'),
        db.Index('idx_attendance_date_tenant', 'date', 'tenant_id'),
    )
    
    def __repr__(self):
        return f'<Attendance Student:{self.student_id} {self.status} on {self.date}>'


class Result(db.Model):
    """Stores student academic results."""
    __tablename__ = 'results'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey('terms.id'), nullable=False)
    ca_score = db.Column(db.Float, default=0.0)
    exam_score = db.Column(db.Float, default=0.0)
    is_published = db.Column(db.Boolean, default=False)
    inputted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint to prevent duplicate results
    __table_args__ = (
        db.UniqueConstraint('student_id', 'subject_id', 'class_id', 'term_id', name='unique_result_record'),
    )
    
    @hybrid_property
    def total_score(self):
        """Dynamic property to calculate total score (CA + Exam)."""
        return self.ca_score + self.exam_score
    
    @total_score.expression
    def total_score(cls):
        """SQL expression for total score."""
        return cls.ca_score + cls.exam_score
    
    def __repr__(self):
        return f'<Result Student:{self.student_id} Subject:{self.subject_id} Total:{self.total_score}>'


class Assignment(db.Model):
    """Represents an assignment created by a teacher."""
    __tablename__ = 'assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    assignment_type = db.Column(db.String(20), nullable=False)  # 'written', 'quiz'
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey('terms.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    due_date = db.Column(db.DateTime)
    total_marks = db.Column(db.Float, default=100.0)
    is_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    questions = db.relationship('QuizQuestion', backref='assignment', lazy='dynamic', cascade='all, delete-orphan')
    submissions = db.relationship('AssignmentSubmission', backref='assignment', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Assignment {self.title}>'


class QuizQuestion(db.Model):
    """Represents a question in a quiz assignment."""
    __tablename__ = 'quiz_questions'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), default='multiple_choice')  # 'multiple_choice', 'true_false', 'short_answer'
    options = db.Column(db.JSON)  # Store options for multiple choice questions
    correct_answer = db.Column(db.String(500))
    marks = db.Column(db.Float, default=1.0)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<QuizQuestion {self.id}>'


class AssignmentSubmission(db.Model):
    """Represents a student's submission for an assignment."""
    __tablename__ = 'assignment_submissions'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignments.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    submission_text = db.Column(db.Text)
    quiz_answers = db.Column(db.JSON)  # Store answers for quiz submissions
    client_sync_id = db.Column(db.String(120), index=True)
    score = db.Column(db.Float)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    graded_at = db.Column(db.DateTime)
    graded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    feedback = db.Column(db.Text)
    
    # Unique constraint to prevent duplicate submissions
    __table_args__ = (
        db.UniqueConstraint('assignment_id', 'student_id', name='unique_assignment_submission'),
        db.UniqueConstraint('tenant_id', 'client_sync_id', name='unique_assignment_client_sync_id'),
    )
    
    def __repr__(self):
        return f'<AssignmentSubmission Student:{self.student_id} Assignment:{self.assignment_id}>'


class GlobalSubjectRepository(db.Model):
    """Read-only national curriculum subject list shared by every tenant."""
    __tablename__ = 'global_subject_repository'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True, index=True)
    category = db.Column(db.String(40), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant_subjects = db.relationship('TenantSubject', backref='global_subject', lazy='dynamic')

    def __repr__(self):
        return f'<GlobalSubjectRepository {self.name}>'


class TenantSubject(db.Model):
    """A national subject enabled for a tenant and assigned to a class level."""
    __tablename__ = 'tenant_subjects'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    global_subject_id = db.Column(db.Integer, db.ForeignKey('global_subject_repository.id'), nullable=False)
    class_level_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    assigned_teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='tenant_subjects')
    class_level = db.relationship('Class')
    assigned_teacher = db.relationship('User', foreign_keys=[assigned_teacher_id])
    student_registrations = db.relationship(
        'StudentSubjectRegistration',
        backref='tenant_subject',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    __table_args__ = (
        db.UniqueConstraint(
            'tenant_id',
            'global_subject_id',
            'class_level_id',
            name='unique_tenant_global_subject_class'
        ),
    )

    def __repr__(self):
        return f'<TenantSubject Tenant:{self.tenant_id} Subject:{self.global_subject_id} Class:{self.class_level_id}>'


class StudentSubjectRegistration(db.Model):
    """Subjects selected by a student from the tenant national-subject catalog."""
    __tablename__ = 'student_subject_registrations'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tenant_subject_id = db.Column(db.Integer, db.ForeignKey('tenant_subjects.id'), nullable=False)
    registration_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    tenant = db.relationship('Tenant', backref='student_subject_registrations')
    student = db.relationship('User', foreign_keys=[student_id])

    __table_args__ = (
        db.UniqueConstraint('student_id', 'tenant_subject_id', name='unique_student_tenant_subject'),
    )

    def __repr__(self):
        return f'<StudentSubjectRegistration Student:{self.student_id} TenantSubject:{self.tenant_subject_id}>'


class CBTExam(db.Model):
    """Computer-based test exam container for generated or manual questions."""
    __tablename__ = 'cbt_exams'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'))
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'))
    term_id = db.Column(db.Integer, db.ForeignKey('terms.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='cbt_exams')
    questions = db.relationship('CBTQuestion', backref='exam', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<CBTExam {self.title}>'


class CBTQuestion(db.Model):
    """Multiple-choice CBT question."""
    __tablename__ = 'cbt_questions'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('cbt_exams.id'), nullable=False, index=True)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(500), nullable=False)
    option_b = db.Column(db.String(500), nullable=False)
    option_c = db.Column(db.String(500), nullable=False)
    option_d = db.Column(db.String(500), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('Tenant', backref='cbt_questions')

    def __repr__(self):
        return f'<CBTQuestion Exam:{self.exam_id} Question:{self.id}>'
