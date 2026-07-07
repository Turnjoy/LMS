from hashlib import sha256
from flask import current_app
from werkzeug.security import check_password_hash

from app.models import User


STAFF_ROLES = {'admin', 'primary_admin', 'secondary_admin', 'teacher', 'attendant'}
LEARNER_ROLES = {'student', 'parent'}


def normalize_identifier(value):
    return (value or '').strip().upper()


def first_name_password_matches(user, password):
    return bool(user and user.is_first_login and password == user.first_name.lower())


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
    return 'STU' if role == 'student' else 'STF'


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
    if user.custom_id or not tenant or user.role == 'super_admin':
        return user.custom_id
    user.custom_id = generate_custom_id(tenant, user.role, now)
    return user.custom_id


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
