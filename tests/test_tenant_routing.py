import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import _is_school_lockout_required, _normalize_host
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
