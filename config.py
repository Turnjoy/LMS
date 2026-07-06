import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from dotenv import load_dotenv

load_dotenv()


def _database_url(env_var, default):
    """Return a SQLAlchemy-compatible database URL."""
    url = os.environ.get(env_var) or default
    if not url:
        return default

    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)

    if url.startswith('postgresql://') and 'sslmode=' not in url:
        parsed = urlparse(url)
        if parsed.hostname and 'supabase.co' in parsed.hostname:
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query['sslmode'] = 'require'
            parsed = parsed._replace(query=urlencode(query))
            url = urlunparse(parsed)

    return url


class Config:
    """Base configuration class."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    MASTER_OWNER_EMAIL = os.environ.get('MASTER_OWNER_EMAIL')
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    GEMINI_MODEL = os.environ.get('GEMINI_MODEL') or 'gemini-1.5-flash'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    @staticmethod
    def init_app(app):
        pass


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = _database_url('DATABASE_URL', _database_url('DEV_DATABASE_URL', 'sqlite:///school_lms_dev.db'))


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = _database_url('DATABASE_URL', 'postgresql://user:password@localhost/school_lms')


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
