from hashlib import sha256
import secrets
import string
from flask import current_app
from werkzeug.security import check_password_hash

from app.models import User


LOCAL_ADMIN_ROLES = {'school_admin', 'admin', 'primary_admin', 'secondary_admin'}
STAFF_ROLES = LOCAL_ADMIN_ROLES | {'teacher', 'attendant'}
LEARNER_ROLES = {'student', 'parent'}


def normalize_identifier(value):
    return (value or '').strip().upper()


def first_name_password_matches(user, password):
    return bool(
        user
        and user.role in LOCAL_ADMIN_ROLES
        and user.is_first_login
        and password == user.first_name.lower()
    )


def password_matches(user, password):
    if not user:
        return False
    if first_name_password_matches(user, password):
        return True
    return bool(user.password_hash and check_password_hash(user.password_hash, password))


def tenant_prefix(tenant):
    raw_prefix = (getattr(tenant, 'school_prefix', None) or '').strip().upper()
    if raw_prefix:
        return raw_prefix[:12]
    name = (tenant.name or 'SCH').strip()
    return ''.join(part[0] for part in name.split()[:3]).upper() or 'SCH'


def custom_id_bucket(role):
    if role == 'student':
        return 'STU'
    if role in LOCAL_ADMIN_ROLES:
        return 'ADM'
    return 'STF'


def generate_custom_id(tenant, role, now):
    year = now.year
    bucket = custom_id_bucket(role)
    prefix = tenant_prefix(tenant)
    existing_count = User.query.filter(
        User.tenant_id == tenant.id,
        User.custom_id.like(f'{prefix}/{bucket}/{year}/%')
    ).count()
    return f'{prefix}/{bucket}/{year}/{existing_count + 1:03d}'


def ensure_custom_id(user, tenant, now):
    generated_id = user.school_generated_id or user.custom_id
    if generated_id or not tenant or user.role == 'super_admin':
        if generated_id:
            user.school_generated_id = generated_id
            user.custom_id = generated_id
        return generated_id
    generated_id = generate_custom_id(tenant, user.role, now)
    user.school_generated_id = generated_id
    user.custom_id = generated_id
    return generated_id


def generate_temporary_password(length=12):
    """Generate a temporary password suitable for imported school users."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def user_payment_locked(user, tenant):
    if not user or not tenant:
        return False
    if tenant.billing_type != 'student_pay':
        return False
    return user.role in LEARNER_ROLES and user.payment_status != 'paid'


def live_room_name(school_id, class_id):
    secret = current_app.config.get('SECRET_KEY', 'turnjoy-live-class')
    digest = sha256(f'{school_id}:{class_id}:{secret}'.encode('utf-8')).hexdigest()
    return f'turnjoy-{digest[:32]}'
