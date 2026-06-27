from flask import Blueprint, request, jsonify, g, render_template
from flask_login import login_required, current_user
from datetime import date
from app.models import Attendance, User, Class
from app.decorators import role_required
from app import db

attendance_bp = Blueprint('attendance', __name__, url_prefix='/attendance')


@attendance_bp.route('/dashboard')
@login_required
@role_required('attendant')
def dashboard():
    """Attendant dashboard for attendance management."""
    return render_template('dashboard.html')


@attendance_bp.route('/', methods=['POST'])
@login_required
@role_required('attendant')
def submit_attendance():
    """
    Submit daily roll-call logs in a batch transaction.
    Accepts an array of attendance records for multiple students.
    """
    data = request.get_json()
    attendance_records = data.get('attendance', [])
    class_id = data.get('class_id')
    attendance_date = data.get('date')
    
    if not attendance_records or not class_id:
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Parse date
    try:
        if attendance_date:
            attendance_date = date.fromisoformat(attendance_date)
        else:
            attendance_date = date.today()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    
    # Verify class belongs to current tenant
    class_obj = Class.query.filter_by(
        id=class_id,
        tenant_id=g.current_tenant_id
    ).first()
    
    if not class_obj:
        return jsonify({'error': 'Class not found'}), 404
    
    # Batch transaction context for atomic operation
    try:
        for record in attendance_records:
            student_id = record.get('student_id')
            status = record.get('status')
            remarks = record.get('remarks')
            
            # Validate status
            if status not in ['present', 'absent', 'late', 'excused']:
                return jsonify({'error': f'Invalid status: {status}'}), 400
            
            # Check if attendance record already exists
            existing = Attendance.query.filter_by(
                tenant_id=g.current_tenant_id,
                student_id=student_id,
                class_id=class_id,
                date=attendance_date
            ).first()
            
            if existing:
                # Update existing record
                existing.status = status
                existing.marked_by = current_user.id
                existing.remarks = remarks
            else:
                # Create new record
                attendance = Attendance(
                    tenant_id=g.current_tenant_id,
                    student_id=student_id,
                    class_id=class_id,
                    date=attendance_date,
                    status=status,
                    marked_by=current_user.id,
                    remarks=remarks
                )
                db.session.add(attendance)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Submitted {len(attendance_records)} attendance records'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@attendance_bp.route('/class/<int:class_id>')
@login_required
@role_required('attendant', 'teacher', 'admin')
def get_class_attendance(class_id):
    """Get attendance records for a specific class."""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = Attendance.query.filter_by(
        tenant_id=g.current_tenant_id,
        class_id=class_id
    )
    
    if start_date:
        try:
            start_date = date.fromisoformat(start_date)
            query = query.filter(Attendance.date >= start_date)
        except ValueError:
            return jsonify({'error': 'Invalid start_date format'}), 400
    
    if end_date:
        try:
            end_date = date.fromisoformat(end_date)
            query = query.filter(Attendance.date <= end_date)
        except ValueError:
            return jsonify({'error': 'Invalid end_date format'}), 400
    
    records = query.all()
    
    attendance_data = [{
        'id': r.id,
        'student_id': r.student_id,
        'student_name': r.student_attendance.name if r.student_attendance else None,
        'date': r.date.isoformat(),
        'status': r.status,
        'marked_by': r.marked_by,
        'marker_name': r.marker.name if r.marker else None,
        'remarks': r.remarks
    } for r in records]
    
    return jsonify({'attendance': attendance_data}), 200


@attendance_bp.route('/student/<int:student_id>')
@login_required
@role_required('attendant', 'teacher', 'admin', 'student')
def get_student_attendance(student_id):
    """Get attendance records for a specific student."""
    # If student, only allow viewing own attendance
    if current_user.role == 'student' and current_user.id != student_id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = Attendance.query.filter_by(
        tenant_id=g.current_tenant_id,
        student_id=student_id
    )
    
    if start_date:
        try:
            start_date = date.fromisoformat(start_date)
            query = query.filter(Attendance.date >= start_date)
        except ValueError:
            return jsonify({'error': 'Invalid start_date format'}), 400
    
    if end_date:
        try:
            end_date = date.fromisoformat(end_date)
            query = query.filter(Attendance.date <= end_date)
        except ValueError:
            return jsonify({'error': 'Invalid end_date format'}), 400
    
    records = query.all()
    
    attendance_data = [{
        'id': r.id,
        'class_id': r.class_id,
        'class_name': r.class_obj.name if r.class_obj else None,
        'date': r.date.isoformat(),
        'status': r.status,
        'remarks': r.remarks
    } for r in records]
    
    return jsonify({'attendance': attendance_data}), 200
