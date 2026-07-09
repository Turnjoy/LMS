from functools import wraps
from flask import abort, g, render_template, session
from flask_login import current_user
from app.auth_utils import user_payment_locked

LOCAL_ADMIN_ROLES = ('school_admin', 'admin', 'primary_admin', 'secondary_admin')


def user_has_role(user, roles):
    expanded_roles = set()
    for role in roles:
        if role == 'local_admin':
            expanded_roles.update(LOCAL_ADMIN_ROLES)
        else:
            expanded_roles.add(role)
    return user.role in expanded_roles


def role_required(*roles):
    """
    Decorator factory to restrict route access based on user roles.
    
    Args:
        *roles: Variable number of role strings (e.g., 'admin', 'teacher', 'student', 'attendant')
    
    Returns:
        Decorator function that checks if current user has one of the required roles
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            
            if not user_has_role(current_user, roles):
                abort(403)

            if user_payment_locked(current_user, getattr(g, 'current_tenant', None)):
                return render_template(
                    'portal/payment_required.html',
                    payload={'status': 'payment_required', 'message': 'Payment Required'}
                ), 402
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
