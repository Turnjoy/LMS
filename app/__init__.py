from flask import Flask, g, render_template, request
from flask_login import LoginManager
from config import config
from app.models import db, Tenant
import os


def _normalize_host(host):
    """Normalize a request host into a domain string used for tenant lookup."""
    host = (host or '').split(':')[0].strip().lower()
    if host.startswith('www.'):
        host = host[4:]
    return host


def _ensure_runtime_schema():
    """Small SQLite-friendly schema guard for development without migrations."""
    engine = db.engine
    if engine.dialect.name != 'sqlite':
        return

    with engine.connect() as connection:
        columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(tenants)").fetchall()]
        if 'custom_domain' not in columns:
            connection.exec_driver_sql("ALTER TABLE tenants ADD COLUMN custom_domain VARCHAR(255)")
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_custom_domain ON tenants (custom_domain)")
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
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    
    @login_manager.user_loader
    def load_user(user_id):
        """Load a user by their ID for Flask-Login session management."""
        from app.models import User
        return User.query.filter_by(id=int(user_id)).first()
    
    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.results import results_bp
    from app.routes.attendance import attendance_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(attendance_bp)
    
    # Global before_request middleware for multi-tenant isolation
    @app.before_request
    def set_tenant_context():
        """
        Resolve the browser domain to fetch the active school
        from the Tenant table and store its ID in g.current_tenant_id.
        """
        # Skip for static files and favicon
        if request.path.startswith('/static') or request.path in ['/favicon.ico', '/healthz']:
            return
        
        try:
            host = _normalize_host(request.host)
            tenant = None

            if host not in ['localhost', '127.0.0.1', '0.0.0.0']:
                tenant = Tenant.query.filter_by(custom_domain=host).first()

                if not tenant and host.endswith('.localhost'):
                    tenant = Tenant.query.filter_by(subdomain=host.split('.')[0]).first()

                if not tenant and '.' in host:
                    tenant = Tenant.query.filter_by(subdomain=host.split('.')[0]).first()

            env_domain = os.environ.get('TENANT_DOMAIN')
            env_subdomain = os.environ.get('TENANT_SUBDOMAIN')
            if not tenant and env_domain:
                tenant = Tenant.query.filter_by(custom_domain=_normalize_host(env_domain)).first()
            if not tenant and env_subdomain:
                tenant = Tenant.query.filter_by(subdomain=env_subdomain).first()
            if not tenant:
                tenant = Tenant.query.first()

            if tenant:
                g.current_tenant_id = tenant.id
                g.current_tenant = tenant
                g.current_domain = tenant.custom_domain or host
            else:
                g.current_tenant_id = None
                g.current_tenant = None
                g.current_domain = host
        except Exception as e:
            # If database is not ready, set tenant to None
            g.current_tenant_id = None
            g.current_tenant = None
            g.current_domain = _normalize_host(request.host)
    
    # Context processor to make tenant data available in templates
    @app.context_processor
    def inject_tenant():
        """Inject tenant data into all templates for dynamic styling."""
        if hasattr(g, 'current_tenant') and g.current_tenant:
            return dict(
                tenant=g.current_tenant,
                tenant_domain=g.current_tenant.custom_domain or getattr(g, 'current_domain', None),
                primary_color=g.current_tenant.primary_color,
                secondary_color=g.current_tenant.secondary_color
            )
        return dict(
            tenant=None,
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
    
    # Create database tables
    with app.app_context():
        db.create_all()
        _ensure_runtime_schema()
    
    return app
