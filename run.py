import os
from app import create_app, db
from app.models import Tenant, User, Class, Subject, Term
from werkzeug.security import generate_password_hash

# Create Flask app
app = create_app(os.getenv('FLASK_CONFIG', 'development'))


@app.cli.command()
def init_db():
    """Initialize the database with sample data."""
    db.create_all()
    
    # Create a sample tenant
    tenant = Tenant(
        name='demo.localhost',
        subdomain='demo',
        custom_domain='demo.localhost',
        primary_color='#3498db',
        secondary_color='#2ecc71'
    )
    db.session.add(tenant)
    db.session.commit()
    
    # Create sample users
    admin = User(
        tenant_id=tenant.id,
        name='Admin User',
        email='admin@demo.com',
        password_hash=generate_password_hash('admin123'),
        role='admin',
        is_approved=True
    )
    
    teacher = User(
        tenant_id=tenant.id,
        name='John Teacher',
        email='teacher@demo.com',
        password_hash=generate_password_hash('teacher123'),
        role='teacher',
        is_approved=True
    )
    
    student = User(
        tenant_id=tenant.id,
        name='Jane Student',
        email='student@demo.com',
        password_hash=generate_password_hash('student123'),
        role='student',
        is_approved=True
    )
    
    attendant = User(
        tenant_id=tenant.id,
        name='Bob Attendant',
        email='attendant@demo.com',
        password_hash=generate_password_hash('attendant123'),
        role='attendant',
        is_approved=True
    )
    
    db.session.add_all([admin, teacher, student, attendant])
    
    # Create sample classes
    class1 = Class(tenant_id=tenant.id, name='JSS 1A', section='secondary', arm='A')
    class2 = Class(tenant_id=tenant.id, name='JSS 2A', section='secondary', arm='A')
    db.session.add_all([class1, class2])
    
    # Create sample subjects
    math = Subject(tenant_id=tenant.id, name='Mathematics')
    english = Subject(tenant_id=tenant.id, name='English')
    science = Subject(tenant_id=tenant.id, name='Integrated Science')
    db.session.add_all([math, english, science])
    
    # Create sample term
    term = Term(
        tenant_id=tenant.id,
        name='First Term',
        session='2024/2025'
    )
    db.session.add(term)
    
    db.session.commit()
    
    print('Database initialized with sample data!')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
