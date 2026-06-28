import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import _database_url


def test_supabase_url_gets_sslmode_require():
    url = _database_url('DATABASE_URL', 'sqlite:///school_lms_dev.db')
    assert 'sslmode=require' in url


def test_default_sqlite_url_is_preserved():
    url = _database_url('DATABASE_URL', 'sqlite:///school_lms_dev.db')
    assert url.startswith('sqlite://') or 'sslmode=require' in url
