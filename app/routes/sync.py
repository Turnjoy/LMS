from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db
from app.decorators import role_required
from app.models import Assignment, AssignmentSubmission

sync_bp = Blueprint('sync', __name__, url_prefix='/api/offline-sync')


@sync_bp.route('/assignments', methods=['POST'])
@sync_bp.route('/quiz-submissions', methods=['POST'])
@login_required
@role_required('student')
def offline_sync_assignments():
    """Accept queued assignment/quiz payloads from low-bandwidth clients."""
    payload = request.get_json(silent=True) or {}
    items = payload.get('items') or []
    if not isinstance(items, list):
        return jsonify({'error': 'items must be an array'}), 400

    synced = []
    for item in items:
        assignment_id = item.get('assignment_id')
        client_sync_id = item.get('client_sync_id')
        if not assignment_id or not client_sync_id:
            synced.append({'client_sync_id': client_sync_id, 'status': 'rejected'})
            continue

        assignment = Assignment.query.filter_by(
            id=assignment_id,
            tenant_id=current_user.tenant_id,
            is_published=True
        ).first()
        if not assignment:
            synced.append({'client_sync_id': client_sync_id, 'status': 'missing_assignment'})
            continue

        submission = AssignmentSubmission.query.filter_by(
            tenant_id=current_user.tenant_id,
            client_sync_id=client_sync_id
        ).first()
        if not submission:
            submission = AssignmentSubmission.query.filter_by(
                tenant_id=current_user.tenant_id,
                assignment_id=assignment.id,
                student_id=current_user.id
            ).first()

        if not submission:
            submission = AssignmentSubmission(
                tenant_id=current_user.tenant_id,
                assignment_id=assignment.id,
                student_id=current_user.id,
                client_sync_id=client_sync_id
            )
            db.session.add(submission)

        submission.submission_text = item.get('submission_text') or submission.submission_text
        submission.quiz_answers = item.get('quiz_answers') or submission.quiz_answers
        submission.submitted_at = datetime.utcnow()
        synced.append({'client_sync_id': client_sync_id, 'status': 'synced'})

    db.session.commit()
    return jsonify({'success': True, 'items': synced}), 200
