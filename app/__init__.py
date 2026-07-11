from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from flask_login import LoginManager
from werkzeug.exceptions import HTTPException
from config import config
from app.models import db, Tenant
from urllib.parse import urlparse


def _normalize_host(host):
    """Normalize a request host into a domain string used for tenant lookup."""
    host = (host or '').strip().lower()
    if not host:
        return ''

    parsed = urlparse(f"//{host}")
    host = parsed.netloc or parsed.path or host
    host = host.rstrip('.')
    if host.startswith('www.'):
        host = host[4:]
    if host.count(':') == 1:
        host = host.rsplit(':', 1)[0]
    return host


def _school_session_payload(tenant):
    return {
        'id': tenant.id,
        'name': tenant.name,
        'custom_domain': tenant.custom_domain,
        'subdomain': tenant.subdomain,
        'status': tenant.status,
        'is_active': bool(tenant.is_active),
        'billing_type': tenant.billing_type,
    }


def _tenant_is_active(tenant):
    """Return True for live tenant domains, accepting legacy approved rows."""
    if not tenant:
        return False
    status = (tenant.status or '').lower()
    return bool(tenant.is_active) and status in ('active', 'approved')


def _is_school_lockout_required(tenant):
    """Return True when a matched school is suspended for school-pay billing."""
    if not tenant:
        return False
    if getattr(tenant, 'status', None) in ('pending', 'rejected'):
        return str(getattr(tenant, 'billing_type', 'school_pay')) == 'school_pay' or not bool(getattr(tenant, 'is_active', True))
    return not bool(getattr(tenant, 'is_active', True)) and str(getattr(tenant, 'billing_type', 'school_pay')) == 'school_pay'


def _subdomain_from_host(host):
    """Return a tenant subdomain candidate for multi-label hosts."""
    if not host or host in ['localhost', '127.0.0.1', '0.0.0.0']:
        return None
    if host.endswith('.localhost'):
        return host.split('.')[0]
    parts = host.split('.')
    if len(parts) >= 3:
        return parts[0]
    return None


def _marketing_domains(app):
    configured = app.config.get('MARKETING_DOMAINS')
    if configured:
        if isinstance(configured, str):
            domains = configured.split(',')
        else:
            domains = configured
    else:
        domains = ['turnjoy.com', 'www.turnjoy.com', 'turnjoy-lms.onrender.com', 'turnjoy-lms.up.railway.app']
    normalized = {_normalize_host(domain) for domain in domains if domain}
    return normalized | {f'www.{domain}' for domain in normalized if not domain.startswith('www.')}


def _local_dev_domains():
    return {'localhost', '127.0.0.1', '0.0.0.0'}


def _is_marketing_host(app, host):
    return host in _marketing_domains(app) or host in _local_dev_domains()


def _scope_tenant_query(query, tenant_id=None):
    """Append a tenant/school filter when a school context is active."""
    current_tenant_id = tenant_id if tenant_id is not None else getattr(g, 'current_tenant_id', None)
    if current_tenant_id is None:
        return query
    return query.filter_by(tenant_id=current_tenant_id)


def _ensure_runtime_schema():
    """Small SQLite-friendly schema guard for development without migrations."""
    engine = db.engine
    if engine.dialect.name != 'sqlite':
        return

    with engine.connect() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS class_levels (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id),
                name VARCHAR(50) NOT NULL,
                category VARCHAR(20) NOT NULL,
                sort_order INTEGER DEFAULT 0,
                created_at DATETIME,
                CONSTRAINT unique_tenant_class_level UNIQUE (tenant_id, name)
            )
        """)
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_class_levels_tenant_id ON class_levels (tenant_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_class_levels_category ON class_levels (category)")
        connection.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS class_arms (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id),
                class_level_id INTEGER NOT NULL REFERENCES class_levels(id),
                name VARCHAR(40) NOT NULL,
                created_at DATETIME,
                CONSTRAINT unique_tenant_class_arm UNIQUE (tenant_id, class_level_id, name)
            )
        """)
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_class_arms_tenant_id ON class_arms (tenant_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_class_arms_class_level_id ON class_arms (class_level_id)")

        tenant_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(tenants)").fetchall()]
        if 'custom_domain' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN custom_domain VARCHAR(255)")
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_custom_domain ON tenants (custom_domain)")
        if 'school_prefix' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN school_prefix VARCHAR(12) NOT NULL DEFAULT 'SCH'")
        if 'status' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending'")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_tenants_status ON tenants (status)")
        if 'application_website' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN application_website VARCHAR(255)")
        if 'application_contact_name' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN application_contact_name VARCHAR(120)")
        if 'application_contact_email' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN application_contact_email VARCHAR(120)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_tenants_application_contact_email ON tenants (application_contact_email)")
        if 'application_contact_phone' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN application_contact_phone VARCHAR(30)")
        if 'application_note' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN application_note TEXT")
        if 'is_active' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1")
        if 'billing_type' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN billing_type VARCHAR(20) NOT NULL DEFAULT 'school_pay'")
        if 'setup_completed' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN setup_completed BOOLEAN NOT NULL DEFAULT 0")
        if 'sections' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN sections VARCHAR(20)")
        if 'sss_tracks' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN sss_tracks VARCHAR(100)")
        if 'structured_code' not in tenant_columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN structured_code VARCHAR(40)")

        user_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)").fetchall()]
        if 'is_approved' not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN is_approved BOOLEAN NOT NULL DEFAULT 0")
        if 'custom_id' not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN custom_id VARCHAR(40)")
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_custom_id ON users (custom_id)")
        if 'school_generated_id' not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN school_generated_id VARCHAR(40)")
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_school_generated_id ON users (school_generated_id)")
        if 'phone_number' not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN phone_number VARCHAR(30)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_users_phone_number ON users (phone_number)")
        if 'is_first_login' not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN is_first_login BOOLEAN NOT NULL DEFAULT 0")
        if 'payment_status' not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN payment_status VARCHAR(20) NOT NULL DEFAULT 'unpaid'")
        if 'section' not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN section VARCHAR(20)")
        if 'is_active' not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1")

        class_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(classes)").fetchall()]
        if 'class_level_id' not in class_columns:
            connection.exec_driver_sql("ALTER TABLE classes ADD COLUMN class_level_id INTEGER REFERENCES class_levels(id)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_classes_class_level_id ON classes (class_level_id)")
        if 'class_arm_id' not in class_columns:
            connection.exec_driver_sql("ALTER TABLE classes ADD COLUMN class_arm_id INTEGER REFERENCES class_arms(id)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_classes_class_arm_id ON classes (class_arm_id)")
        if 'section' not in class_columns:
            connection.exec_driver_sql("ALTER TABLE classes ADD COLUMN section VARCHAR(20)")
        if 'arm' not in class_columns:
            connection.exec_driver_sql("ALTER TABLE classes ADD COLUMN arm VARCHAR(40)")
        if 'track' not in class_columns:
            connection.exec_driver_sql("ALTER TABLE classes ADD COLUMN track VARCHAR(30)")

        submission_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(assignment_submissions)").fetchall()]
        if submission_columns and 'client_sync_id' not in submission_columns:
            connection.exec_driver_sql("ALTER TABLE assignment_submissions ADD COLUMN client_sync_id VARCHAR(120)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_assignment_submissions_client_sync_id ON assignment_submissions (client_sync_id)")

        subject_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(subjects)").fetchall()]
        if 'class_level_id' not in subject_columns:
            connection.exec_driver_sql("ALTER TABLE subjects ADD COLUMN class_level_id INTEGER REFERENCES class_levels(id)")
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_subjects_class_level_id ON subjects (class_level_id)")

        connection.commit()


def create_app(config_name='default'):
    """Application factory pattern for creating Flask app instances."""
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)
    
    # Initialize extensions
    db.init_app(app)
    
    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login' # type: ignore
    login_manager.login_message = 'Please log in to access this page.'
    
    @login_manager.user_loader
    def load_user(user_id):
        """Load a user by their ID for Flask-Login session management."""
        from app.models import User
        return User.query.filter_by(id=int(user_id)).first()
    
    # Register blueprints
    from app.routes.public import public_bp
    from app.routes.portal import auth_bp as portal_auth_bp
    from app.routes.admin import admin_bp
    from app.routes.results import results_bp
    from app.routes.attendance import attendance_bp
    from app.routes.api_subjects import api_subjects_bp
    from app.routes.cbt import cbt_bp
    from app.routes.sync import sync_bp
    
    app.register_blueprint(public_bp)
    app.register_blueprint(portal_auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(api_subjects_bp)
    app.register_blueprint(cbt_bp)
    app.register_blueprint(sync_bp)

    @app.cli.command('seed-global-subjects')
    def seed_global_subjects_command():
        """Seed the Nigerian national subject repository."""
        from app.seed import seed_global_subject_repository

        created_count = seed_global_subject_repository()
        print(f'Seeded global subject repository. Created {created_count} new subjects.')
    
    # Global before_request middleware for multi-tenant isolation
    @app.before_request
    def set_tenant_context():
        """Resolve hostnames into marketing or isolated tenant contexts."""
        g.current_tenant_id = None
        g.current_tenant = None
        g.current_school = None

        if request.path.startswith('/static') or request.path in ['/favicon.ico', '/healthz']:
            return

        try:
            host = _normalize_host(request.headers.get('Host') or request.host)
            g.current_domain = host
            tenant = None
            is_marketing_host = _is_marketing_host(app, host)
            is_master_path = request.path.startswith('/turnjoy-master-admin') or request.path.startswith('/_master_hq_2026')
            marketing_only_paths = {'/', '/about', '/pricing', '/contact', '/apply', '/admin'}

            if is_master_path and not is_marketing_host:
                abort(404)

            if is_marketing_host:
                session.pop('current_tenant', None)
                return

            if host not in _local_dev_domains():
                tenant = Tenant.query.filter_by(custom_domain=host).first()

                subdomain = _subdomain_from_host(host)
                if not tenant and subdomain:
                    tenant = Tenant.query.filter_by(subdomain=subdomain).first()

            if not tenant and request.path in marketing_only_paths:
                abort(404)

            if tenant:
                if not _tenant_is_active(tenant):
                    return render_template('public/lockout.html', tenant=tenant), 403

                g.current_tenant_id = tenant.id
                g.current_tenant = tenant
                g.current_school = tenant
                g.current_domain = tenant.custom_domain or host
                session['current_tenant'] = _school_session_payload(tenant)

                from flask_login import current_user, logout_user
                if (
                    current_user.is_authenticated
                    and current_user.role != 'super_admin'
                    and getattr(current_user, 'tenant_id', None) != tenant.id
                ):
                    logout_user()
                    return render_template('public/lockout.html', tenant=tenant), 403

                if (
                    current_user.is_authenticated
                    and current_user.role in ('school_admin', 'admin', 'primary_admin', 'secondary_admin')
                    and _tenant_is_active(tenant)
                    and not bool(getattr(tenant, 'setup_completed', False))
                    and request.endpoint not in ('auth.logout', 'auth.change_password', 'auth.setup_wizard_redirect')
                    and not request.path.startswith('/admin/setup-wizard')
                ):
                    return redirect(url_for('auth.setup_wizard_redirect'))

                if request.path == '/':
                    from app.models import User
                    local_admin_roles = ('school_admin', 'admin', 'primary_admin', 'secondary_admin')
                    admin_exists = User.query.filter(
                        User.tenant_id == tenant.id,
                        User.role.in_(local_admin_roles)
                    ).first() is not None
                    return render_template('portal/login.html', admin_exists=admin_exists, tenant=tenant)
            else:
                session.pop('current_tenant', None)

                if request.path == '/':
                    abort(404)
        except HTTPException:
            raise
        except Exception:
            if request.path.startswith('/turnjoy-master-admin') or request.path.startswith('/_master_hq_2026'):
                abort(404)
            g.current_tenant_id = None
            g.current_tenant = None
            g.current_school = None
            g.current_domain = _normalize_host(request.host)
    
    # Context processor to make tenant data available in templates
    @app.context_processor
    def inject_tenant():
        """Inject tenant data into all templates for dynamic styling."""
        if hasattr(g, 'current_tenant') and g.current_tenant:
            return dict(
                tenant=g.current_tenant,
                school=g.current_tenant,
                tenant_domain=g.current_tenant.custom_domain or getattr(g, 'current_domain', None),
                primary_color=g.current_tenant.primary_color,
                secondary_color=g.current_tenant.secondary_color
            )
        return dict(
            tenant=None,
            school=None,
            tenant_domain=getattr(g, 'current_domain', None),
            primary_color='#3498db',
            secondary_color='#2ecc71'
        )

    @app.route('/healthz')
    def healthz():
        """Render health check endpoint."""
        return {'status': 'ok'}, 200
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return render_template('base.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('base.html'), 500
    
    # Create database tables in development or testing only.
    # Avoid creating tables automatically in production during app import/startup
    # (platforms like Render should run migrations instead).
    if app.config.get('DEBUG') or app.config.get('TESTING'):
        with app.app_context():
            db.create_all()
            _ensure_runtime_schema()
    
    return app
