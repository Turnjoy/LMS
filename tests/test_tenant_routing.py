import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import _is_school_lockout_required, _normalize_host, create_app, db
from app.models import Tenant


def test_normalize_host_strips_www_and_port():
    assert _normalize_host('www.portal.brightacademy.edu:5000') == 'portal.brightacademy.edu'
    assert _normalize_host('PORTAL.BRIGHTACADEMY.EDU') == 'portal.brightacademy.edu'


def test_inactive_school_pay_is_lockout_required():
    tenant = Tenant(name='Bright Academy', subdomain='bright', custom_domain='portal.brightacademy.edu', is_active=False, billing_type='school_pay')
    assert _is_school_lockout_required(tenant) is True


def test_active_student_pay_is_not_lockout_required():
    tenant = Tenant(name='Bright Academy', subdomain='bright', custom_domain='portal.brightacademy.edu', is_active=True, billing_type='student_pay')
    assert _is_school_lockout_required(tenant) is False


def test_pending_school_is_lockout_required_before_admin_accepts():
    tenant = Tenant(name='Bright Academy', subdomain='bright', custom_domain='portal.brightacademy.edu', status='pending', is_active=False, billing_type='school_pay')
    assert _is_school_lockout_required(tenant) is True


def test_approved_school_domain_can_render_login():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        db.session.add(Tenant(
            name='Bright Academy',
            subdomain='bright',
            custom_domain='bright.localhost',
            status='approved',
            is_active=True,
            billing_type='school_pay',
        ))
        db.session.commit()

    response = app.test_client().get('/login', base_url='http://bright.localhost')

    assert response.status_code == 200
    assert b'Sign In' in response.data
