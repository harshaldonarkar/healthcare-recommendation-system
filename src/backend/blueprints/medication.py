# src/backend/blueprints/medication.py
import logging
from itertools import combinations

from flask import Blueprint, request, jsonify, render_template, session

from core import medication_reminder, login_required

logger = logging.getLogger(__name__)

medication_bp = Blueprint('medication', __name__)


@medication_bp.route('/medication-schedule/create/<user_id>/<plan_id>', methods=['POST'])
def create_medication_schedule(user_id, plan_id):
    try:
        data = request.get_json()
        if not data or 'medications' not in data:
            return jsonify({"error": "Missing medications data"}), 400
        schedule_id = medication_reminder.create_medication_schedule(user_id, plan_id, data['medications'])
        response = jsonify({"message": "Medication schedule created successfully", "schedule_id": schedule_id})
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error creating medication schedule: {e}")
        return jsonify({"error": "Failed to create medication schedule"}), 500


@medication_bp.route('/medication-schedule/<user_id>/<schedule_id>', methods=['GET'])
def get_medication_schedule(user_id, schedule_id):
    try:
        schedule = medication_reminder.get_medication_schedule(user_id, schedule_id)
        if not schedule:
            return jsonify({"error": "Medication schedule not found"}), 404
        response = jsonify(schedule)
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error retrieving medication schedule: {e}")
        return jsonify({"error": "Failed to retrieve medication schedule"}), 500


@medication_bp.route('/medication-schedules/<user_id>', methods=['GET'])
def get_user_medication_schedules(user_id):
    try:
        schedules = medication_reminder.get_user_schedules(user_id)
        response = jsonify(schedules)
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error retrieving user medication schedules: {e}")
        return jsonify({"error": "Failed to retrieve medication schedules"}), 500


@medication_bp.route('/medication-schedule/<user_id>/<schedule_id>/<medication_id>', methods=['PUT'])
def update_medication(user_id, schedule_id, medication_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing update data"}), 400
        success = medication_reminder.update_medication_schedule(user_id, schedule_id, medication_id, data)
        if not success:
            return jsonify({"error": "Failed to update medication"}), 404
        return jsonify({"message": "Medication updated successfully"})
    except Exception as e:
        logger.exception(f"Error updating medication: {e}")
        return jsonify({"error": "Failed to update medication"}), 500


@medication_bp.route('/medication-schedule/<user_id>/<schedule_id>/<medication_id>/taken', methods=['POST'])
def log_medication_taken(user_id, schedule_id, medication_id):
    try:
        data = request.get_json()
        timestamp = data.get('timestamp') if data else None
        success = medication_reminder.log_medication_taken(user_id, schedule_id, medication_id, timestamp)
        if not success:
            return jsonify({"error": "Failed to log medication"}), 404
        return jsonify({"message": "Medication logged successfully"})
    except Exception as e:
        logger.exception(f"Error logging medication: {e}")
        return jsonify({"error": "Failed to log medication"}), 500


@medication_bp.route('/medication-schedule/<user_id>/today', methods=['GET'])
def get_today_medications(user_id):
    try:
        meds = medication_reminder.get_today_medication_schedule(user_id)
        response = jsonify(meds)
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error getting today's medications: {e}")
        return jsonify({"error": "Failed to retrieve today's medications"}), 500


@medication_bp.route('/medication-schedule/<user_id>/upcoming', methods=['GET'])
def get_upcoming_medications(user_id):
    try:
        hours = request.args.get('hours', default=2, type=int)
        meds = medication_reminder.get_upcoming_doses(user_id, hours)
        response = jsonify(meds)
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error getting upcoming medications: {e}")
        return jsonify({"error": "Failed to retrieve upcoming medications"}), 500


@medication_bp.route('/medication-schedule/<user_id>/adherence', methods=['GET'])
def get_medication_adherence(user_id):
    try:
        days = request.args.get('days', default=7, type=int)
        stats = medication_reminder.get_adherence_stats(user_id, days)
        response = jsonify(stats)
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error getting medication adherence: {e}")
        return jsonify({"error": "Failed to retrieve adherence statistics"}), 500


# ---------------------------------------------------------------------------
# Drug Interaction Checker
# ---------------------------------------------------------------------------

# Known interactions database (drug_a, drug_b) → severity + description
_INTERACTIONS = {
    frozenset({'warfarin', 'aspirin'}): {
        'severity': 'high',
        'description': 'Increased risk of bleeding. Both drugs inhibit clotting by different mechanisms.',
    },
    frozenset({'warfarin', 'ibuprofen'}): {
        'severity': 'high',
        'description': 'Ibuprofen can increase warfarin levels and enhance its anticoagulant effect.',
    },
    frozenset({'metformin', 'alcohol'}): {
        'severity': 'moderate',
        'description': 'Alcohol increases the risk of lactic acidosis when combined with metformin.',
    },
    frozenset({'simvastatin', 'amiodarone'}): {
        'severity': 'high',
        'description': 'Amiodarone inhibits simvastatin metabolism, raising risk of myopathy.',
    },
    frozenset({'ssri', 'tramadol'}): {
        'severity': 'high',
        'description': 'Risk of serotonin syndrome — potentially life-threatening.',
    },
    frozenset({'ciprofloxacin', 'antacid'}): {
        'severity': 'moderate',
        'description': 'Antacids reduce ciprofloxacin absorption. Take 2 hours apart.',
    },
    frozenset({'lisinopril', 'potassium'}): {
        'severity': 'moderate',
        'description': 'ACE inhibitors like lisinopril increase potassium levels; supplements can cause hyperkalemia.',
    },
    frozenset({'methotrexate', 'ibuprofen'}): {
        'severity': 'high',
        'description': 'NSAIDs reduce methotrexate excretion, raising toxicity risk.',
    },
    frozenset({'digoxin', 'amiodarone'}): {
        'severity': 'high',
        'description': 'Amiodarone increases digoxin levels significantly — risk of toxicity.',
    },
    frozenset({'paracetamol', 'alcohol'}): {
        'severity': 'moderate',
        'description': 'Regular alcohol use with paracetamol increases liver damage risk.',
    },
    frozenset({'clopidogrel', 'omeprazole'}): {
        'severity': 'moderate',
        'description': 'Omeprazole reduces the antiplatelet effect of clopidogrel.',
    },
    frozenset({'sildenafil', 'nitrate'}): {
        'severity': 'high',
        'description': 'Combination causes severe hypotension — potentially fatal.',
    },
}


def _check_interactions(drug_list):
    """Return list of interactions found among the given drugs."""
    results = []
    normalised = [d.strip().lower() for d in drug_list if d.strip()]
    for a, b in combinations(normalised, 2):
        key = frozenset({a, b})
        # Exact match
        if key in _INTERACTIONS:
            info = _INTERACTIONS[key]
            results.append({'drug_a': a, 'drug_b': b, **info})
            continue
        # Partial match (e.g. "aspirin 100mg" still matches "aspirin")
        for known_pair, info in _INTERACTIONS.items():
            kp = list(known_pair)
            if (any(kp[0] in a or a in kp[0] for _ in [1])
                    and any(kp[1] in b or b in kp[1] for _ in [1])):
                results.append({'drug_a': a, 'drug_b': b, **info})
                break
    return results


@medication_bp.route('/drug-interactions', methods=['GET'])
def drug_interactions_page():
    return render_template('drug_interactions.html')


@medication_bp.route('/medication-schedules', methods=['GET'])
@login_required
def medication_schedules_page():
    user_id = session.get('user_id')
    try:
        schedules = medication_reminder.get_user_schedules(user_id) or []
        today_meds = medication_reminder.get_today_medication_schedule(user_id) or []
    except Exception:
        schedules = []
        today_meds = []
    return render_template('medication_schedules.html', schedules=schedules, today_meds=today_meds, user_id=user_id)


@medication_bp.route('/api/send-reminders', methods=['POST'])
@login_required
def send_medication_reminders():
    """Send a medication reminder email to the logged-in user for today's medications."""
    try:
        from email_service import send_medication_reminder
        user_id = session.get('user_id')
        data = request.get_json() or {}
        email = data.get('email', '')
        if not email:
            return jsonify({'error': 'email is required'}), 400
        medications = medication_reminder.get_today_medication_schedule(user_id)
        sent = send_medication_reminder(email, user_id, medications)
        if sent:
            return jsonify({'message': f'Reminder sent to {email}', 'medications_count': len(medications)})
        return jsonify({'message': 'SMTP not configured — email not sent', 'medications_count': len(medications)})
    except Exception as e:
        logger.exception(f"Error sending medication reminders: {e}")
        return jsonify({'error': 'Failed to send reminder'}), 500


@medication_bp.route('/api/drug-interactions', methods=['POST'])
def check_drug_interactions():
    try:
        data = request.get_json() or {}
        drugs = data.get('drugs', [])
        if not isinstance(drugs, list) or len(drugs) < 2:
            return jsonify({'error': 'Provide at least 2 drug names in a "drugs" list.'}), 400
        interactions = _check_interactions(drugs)
        response = jsonify({
            'drugs_checked': drugs,
            'interactions_found': len(interactions),
            'interactions': interactions,
            'safe': len(interactions) == 0,
        })
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error checking drug interactions: {e}")
        return jsonify({'error': 'Failed to check drug interactions'}), 500
