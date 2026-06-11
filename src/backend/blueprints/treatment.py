# src/backend/blueprints/treatment.py
import logging
import uuid

from flask import Blueprint, abort, render_template, request, jsonify, session, send_file
import io

from core import login_required, progress_tracker, get_recommendations, medication_reminder
from security_log import log_security

logger = logging.getLogger(__name__)

treatment_bp = Blueprint('treatment', __name__)


def _session_identity(create=False):
    """Identity this session may act for: the logged-in user id, else a
    per-session anonymous id stored in the signed session cookie."""
    uid = session.get('user_id')
    if uid:
        return str(uid)
    anon = session.get('anon_id')
    if not anon and create:
        anon = f'user_{uuid.uuid4().hex[:8]}'
        session['anon_id'] = anon
    return anon


def _owner_guard(user_id):
    """Return a 403 response unless the current session owns `user_id`'s plans.

    The user_id in the URL is untrusted input — without this check any visitor
    could read or modify another user's treatment plans (IDOR)."""
    if user_id != _session_identity():
        try:
            log_security('plan_access_denied', requested_user=user_id, path=request.path)
        except Exception:
            pass
        return jsonify({"error": "Forbidden"}), 403
    return None


@treatment_bp.route('/create-treatment-plan', methods=['POST'])
def create_treatment_plan_api():
    try:
        data = request.get_json()
        # Identity comes from the session, never from the client payload
        user_id = _session_identity(create=True)
        disease = data.get('disease')
        if not disease:
            return jsonify({"error": "Missing disease information"}), 400

        recommendations = get_recommendations(disease)
        plan_id = progress_tracker.create_treatment_plan(user_id, disease, recommendations)
        response = jsonify({"message": "Treatment plan created successfully", "plan_id": plan_id, "user_id": user_id})
        response.headers['Content-Type'] = 'application/json'
        return response

    except Exception as e:
        logger.exception(f"Error creating treatment plan: {e}")
        return jsonify({"error": "Failed to create treatment plan"}), 500


@treatment_bp.route('/treatment-plan/<user_id>/<plan_id>', methods=['GET'])
def get_treatment_plan(user_id, plan_id):
    denied = _owner_guard(user_id)
    if denied:
        return denied
    try:
        plan = progress_tracker.get_treatment_plan(user_id, plan_id)
        if not plan:
            return jsonify({"error": "Treatment plan not found"}), 404
        response = jsonify(plan)
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error retrieving treatment plan: {e}")
        return jsonify({"error": "Failed to retrieve treatment plan"}), 500


@treatment_bp.route('/treatment-plans/<user_id>', methods=['GET'])
def get_user_plans(user_id):
    denied = _owner_guard(user_id)
    if denied:
        return denied
    try:
        plans = progress_tracker.get_user_plans(user_id)
        response = jsonify(plans)
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error retrieving user plans: {e}")
        return jsonify({"error": "Failed to retrieve treatment plans"}), 500


@treatment_bp.route('/treatment-plan/<user_id>/<plan_id>/step/<step_id>', methods=['PUT'])
def update_step_status(user_id, plan_id, step_id):
    denied = _owner_guard(user_id)
    if denied:
        return denied
    try:
        data = request.get_json()
        if not data or 'status' not in data:
            return jsonify({"error": "Missing status field"}), 400
        success = progress_tracker.update_step_status(user_id, plan_id, step_id, data['status'])
        if not success:
            return jsonify({"error": "Failed to update step status"}), 404
        return jsonify({"message": "Step status updated successfully"})
    except Exception as e:
        logger.exception(f"Error updating step status: {e}")
        return jsonify({"error": "Failed to update step status"}), 500


@treatment_bp.route('/treatment-plan/<user_id>/<plan_id>/symptom', methods=['POST'])
def log_symptom(user_id, plan_id):
    denied = _owner_guard(user_id)
    if denied:
        return denied
    try:
        data = request.get_json()
        if not data or 'symptom' not in data or 'severity' not in data:
            return jsonify({"error": "Missing required fields"}), 400
        success = progress_tracker.log_symptom(user_id, plan_id, data['symptom'], data['severity'], data.get('notes', ''))
        if not success:
            return jsonify({"error": "Failed to log symptom"}), 404
        return jsonify({"message": "Symptom logged successfully"})
    except Exception as e:
        logger.exception(f"Error logging symptom: {e}")
        return jsonify({"error": "Failed to log symptom"}), 500


@treatment_bp.route('/treatment-plan/<user_id>/<plan_id>/note', methods=['POST'])
def add_note(user_id, plan_id):
    denied = _owner_guard(user_id)
    if denied:
        return denied
    try:
        data = request.get_json()
        if not data or 'content' not in data:
            return jsonify({"error": "Missing note content"}), 400
        success = progress_tracker.add_note(user_id, plan_id, data['content'])
        if not success:
            return jsonify({"error": "Failed to add note"}), 404
        return jsonify({"message": "Note added successfully"})
    except Exception as e:
        logger.exception(f"Error adding note: {e}")
        return jsonify({"error": "Failed to add note"}), 500


@treatment_bp.route('/treatment-plan/<user_id>/<plan_id>/progress', methods=['GET'])
def get_progress_summary(user_id, plan_id):
    denied = _owner_guard(user_id)
    if denied:
        return denied
    try:
        summary = progress_tracker.get_progress_summary(user_id, plan_id)
        if not summary:
            return jsonify({"error": "Treatment plan not found"}), 404
        response = jsonify(summary)
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error getting progress summary: {e}")
        return jsonify({"error": "Failed to get progress summary"}), 500


@treatment_bp.route('/treatment-tracker/<user_id>/<plan_id>')
def treatment_tracker_page(user_id, plan_id):
    if user_id != _session_identity():
        abort(403)
    plan = progress_tracker.get_treatment_plan(user_id, plan_id)
    if not plan:
        abort(404)
    return render_template('treatment_tracker.html', user_id=user_id, plan_id=plan_id, plan=plan)


@treatment_bp.route('/treatment-tracker/<user_id>/<plan_id>/lab-recommendations')
@login_required
def get_treatment_lab_recommendations(user_id, plan_id):
    denied = _owner_guard(user_id)
    if denied:
        return denied
    try:
        from core import lab_analyzer, get_historical_lab_data, analyze_lab_trends, generate_monitoring_schedule
        from datetime import datetime, timedelta

        plan = progress_tracker.get_treatment_plan(user_id, plan_id)
        if not plan:
            return jsonify({"error": "Treatment plan not found"}), 404

        disease = plan.get('disease')
        recommendations = lab_analyzer.suggest_lab_tests(disease)
        recent_tests = []
        for rec in recommendations:
            history = get_historical_lab_data(user_id, rec['test_name'])
            if history:
                recent_cutoff = datetime.now() - timedelta(days=30)
                recent = [h for h in history if datetime.fromisoformat(h['test_date']) > recent_cutoff]
                if recent:
                    recent_tests.append({'test_name': rec['test_name'],
                                         'last_done': recent[-1]['test_date'], 'last_value': recent[-1]['value']})

        return jsonify({"recommendations": recommendations, "recent_tests": recent_tests,
                        "monitoring_schedule": generate_monitoring_schedule(disease, recommendations)})

    except Exception as e:
        logger.exception(f"Error getting treatment lab recommendations: {e}")
        return jsonify({"error": "Failed to get recommendations"}), 500


@treatment_bp.route('/symptom-trends/<user_id>/<plan_id>')
@login_required
def symptom_trends_page(user_id, plan_id):
    if user_id != _session_identity():
        abort(403)
    plan = progress_tracker.get_treatment_plan(user_id, plan_id)
    if not plan:
        return jsonify({"error": "Treatment plan not found"}), 404
    logs = plan.get('symptom_logs', [])
    # Group logs by symptom name for Chart.js
    from collections import defaultdict
    grouped = defaultdict(list)
    for log in sorted(logs, key=lambda x: x.get('date', '')):
        grouped[log['symptom']].append({
            'date': log['date'][:10],  # YYYY-MM-DD
            'severity': log['severity'],
        })
    return render_template('symptom_trends.html',
                           user_id=user_id, plan_id=plan_id,
                           disease=plan.get('disease', ''),
                           symptom_data=dict(grouped))


@treatment_bp.route('/treatment-plans/recommend-labs/<user_id>/<plan_id>', methods=['GET'])
@login_required
def recommend_labs_for_treatment(user_id, plan_id):
    denied = _owner_guard(user_id)
    if denied:
        return denied
    try:
        from core import lab_analyzer, get_user_profile, get_historical_lab_data, analyze_lab_trends

        plan = progress_tracker.get_treatment_plan(user_id, plan_id)
        if not plan:
            return jsonify({"error": "Treatment plan not found"}), 404

        disease = plan.get('disease')
        user_profile = get_user_profile(user_id)
        recommendations = lab_analyzer.suggest_lab_tests(disease, user_profile)
        relevant_history = []
        for rec in recommendations:
            history = get_historical_lab_data(user_id, rec['test_name'])
            if history:
                relevant_history.append({'test_name': rec['test_name'],
                                         'last_result': history[-1],
                                         'trend': analyze_lab_trends(history)})

        return jsonify({"disease": disease, "recommended_tests": recommendations, "relevant_history": relevant_history})

    except Exception as e:
        logger.exception(f"Error recommending labs: {e}")
        return jsonify({"error": "Failed to get recommendations"}), 500

# ---------------------------------------------------------------------------
# Exportable Health Report (PDF)
# ---------------------------------------------------------------------------

@treatment_bp.route('/treatment-plan/<user_id>/<plan_id>/report.pdf', methods=['GET'])
@login_required
def download_health_report(user_id, plan_id):
    """Generate and stream a PDF health report for a treatment plan."""
    denied = _owner_guard(user_id)
    if denied:
        return denied
    try:
        from report_generator import generate_health_report

        plan = progress_tracker.get_treatment_plan(user_id, plan_id)
        if not plan:
            return "Treatment plan not found", 404

        meds = medication_reminder.get_today_medication_schedule(user_id)
        logs = plan.get('symptom_logs', [])

        pdf_bytes = generate_health_report(
            plan=plan,
            medications=meds,
            symptom_logs=logs,
            username=session.get('user_name', user_id),
        )

        filename = f"health_report_{plan.get('disease', 'plan').replace(' ', '_')}.pdf"
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        logger.exception(f"Error generating PDF report: {e}")
        return jsonify({"error": "Failed to generate report"}), 500
