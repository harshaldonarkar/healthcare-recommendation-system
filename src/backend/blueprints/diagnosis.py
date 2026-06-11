# src/backend/blueprints/diagnosis.py
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify, session

from core import (
    medical_data, diseases_list, label_map,
    llm, medical_llm, symptom_analyzer, questionnaire,
    predict_disease_with_confidence, predict_with_svc, direct_symptom_matching,
    predict_with_ddxplus,
    get_recommendations, get_symptoms, get_disease_info,
    get_specialists_for_disease, get_prevention_tips,
    svc_model, validate_symptoms,
)

from security_log import log_security

logger = logging.getLogger(__name__)

diagnosis_bp = Blueprint('diagnosis', __name__)

MAX_SYMPTOM_LENGTH = 2000
_DISALLOWED_PATTERN = re.compile(r'<[^>]+>', re.IGNORECASE)

# Persistent JSON-backed rate limiting
RATE_LIMIT_WINDOW = 60          # seconds
RATE_LIMIT_MAX_REQUESTS = 10    # requests per window
_rl_lock = threading.Lock()
_RL_FILE = os.path.join(os.path.dirname(__file__), '../../data/rate_limits.json')


def _sanitize_input(text):
    """Strip HTML tags and enforce length limit."""
    text = _DISALLOWED_PATTERN.sub('', text)
    return text[:MAX_SYMPTOM_LENGTH].strip()


def _load_rl():
    try:
        with open(_RL_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_rl(data):
    os.makedirs(os.path.dirname(_RL_FILE), exist_ok=True)
    tmp = _RL_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, _RL_FILE)


def _check_rate_limit(session_id):
    """Check if session exceeds rate limit. Returns (allowed, remaining_requests)."""
    now = datetime.now()
    cutoff = (now - timedelta(seconds=RATE_LIMIT_WINDOW)).isoformat()
    with _rl_lock:
        data = _load_rl()
        timestamps = [ts for ts in data.get(session_id, []) if ts > cutoff]
        if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
            data[session_id] = timestamps
            _save_rl(data)
            return False, 0
        timestamps.append(now.isoformat())
        data[session_id] = timestamps
        _save_rl(data)
    return True, RATE_LIMIT_MAX_REQUESTS - len(timestamps)


@diagnosis_bp.route('/')
def home():
    return render_template('index.html')


@diagnosis_bp.route('/analyze', methods=['POST'])
def analyze():
    """Process symptom form and render results page."""
    predictions = []
    primary_prediction = "Unknown"
    recommendations = {
        'causes': 'Not available', 'medicines': [],
        'diet': 'Not available', 'workout': 'Not available', 'precautions': [],
    }
    simplified_explanation = None
    symptoms_text = ""
    ddx_predictions = None

    try:
        # Check rate limit
        session_id = session.get('user_id') or request.remote_addr
        allowed, remaining = _check_rate_limit(session_id)
        if not allowed:
            log_security('rate_limit_triggered', session_id=str(session_id))
            return render_template('index.html', error="Too many requests. Please wait a moment before analyzing more symptoms."), 429

        raw_symptoms = request.form.get('symptoms', '')
        symptoms_text = _sanitize_input(raw_symptoms)
        use_llm = request.form.get('use_llm') == 'on'

        # Optional vitals context
        _vitals = {k: request.form.get(f'vitals_{k}', '') for k in ('age', 'weight', 'height', 'temp')}
        _vitals_ctx = ', '.join(f"{k}: {v}" for k, v in _vitals.items() if v)
        vitals_context = f"\nPatient vitals — {_vitals_ctx}." if _vitals_ctx else ""

        if not symptoms_text:
            return render_template('index.html', error="Please describe your symptoms")

        logger.info(f"Prediction request: {symptoms_text[:100]}...")

        # Malaria fast-path
        normalized = symptoms_text.lower()
        malaria_keywords = ["high fever", "chills", "sweating", "muscle pain"]
        if all(k in normalized for k in malaria_keywords):
            malaria_data = medical_data[medical_data['Disease'] == 'Malaria']
            if not malaria_data.empty:
                predictions = [{'disease': 'Malaria', 'confidence': 95.0,
                                 'symptoms': [str(malaria_data.iloc[0][f'Symptom{i}']) for i in range(1, 5)]}]
        else:
            symptom_list = [s.strip() for s in symptoms_text.split(',')]
            svc_pred = predict_with_svc(symptom_list) if svc_model else None
            direct_matches = direct_symptom_matching(symptoms_text)
            bert_preds = predict_disease_with_confidence(symptoms_text, 3)

            if svc_pred and svc_pred['disease'] == 'Malaria' and all(k in normalized for k in malaria_keywords):
                predictions = [svc_pred]
            elif direct_matches and direct_matches[0]['confidence'] > 40:
                predictions = direct_matches
            elif bert_preds and bert_preds[0]['confidence'] > 5:
                predictions = bert_preds
            else:
                seen = set()
                for pred in ([svc_pred] if svc_pred else []) + direct_matches[:1] + bert_preds[:1]:
                    if pred and pred['disease'] not in seen and len(predictions) < 3:
                        seen.add(pred['disease'])
                        predictions.append(pred)

        if not predictions:
            predictions = [{'disease': 'Prediction Error', 'confidence': 0.0,
                            'symptoms': ['Unable to match symptoms to any known condition']}]

        primary_prediction = predictions[0]['disease']
        recommendations = get_recommendations(primary_prediction)

        # DDXPlus differential diagnosis (49-disease clinical model)
        ddx_predictions = predict_with_ddxplus(symptoms_text, top_k=5)

        if use_llm:
            try:
                disease_info = get_disease_info(primary_prediction)
                syms = ', '.join(get_symptoms(primary_prediction)) or "various symptoms"
                if primary_prediction != 'Prediction Error':
                    medical_info = f"{disease_info.get('causes', 'Various factors')}. Common symptoms include {syms}.{vitals_context}"
                    simplified_explanation = llm.explain_in_simple_terms(primary_prediction, medical_info)
                else:
                    simplified_explanation = "I'm having difficulty analyzing your symptoms. Please provide more details or consult a healthcare professional."
            except Exception as exp_error:
                logger.error(f"LLM explanation error: {exp_error}")
                simplified_explanation = f"Based on your symptoms, {primary_prediction} appears to be the most likely condition."

        for pred in predictions:
            if 'symptoms' not in pred or not pred['symptoms']:
                pred['symptoms'] = get_symptoms(pred['disease'])

    except Exception as e:
        logger.error(f"Error in analyze: {e}", exc_info=True)
        if not predictions:
            predictions = [{'disease': 'System Error', 'confidence': 0.0,
                            'symptoms': ['Error analyzing symptoms, please try again']}]
        primary_prediction = predictions[0]['disease']
        ddx_predictions = None

    result_id = uuid.uuid4().hex[:10]
    session[f'result_{result_id}'] = {
        'disease': primary_prediction,
        'confidence': round(predictions[0].get('confidence', 0)) if predictions else 0,
        'symptoms': symptoms_text[:200],
    }

    return render_template(
        'results.html',
        predictions=predictions,
        primary_prediction=primary_prediction,
        recommendations=recommendations,
        simplified_explanation=simplified_explanation,
        symptoms=symptoms_text,
        result_id=result_id,
        ddx_predictions=ddx_predictions,
    )


@diagnosis_bp.route('/results/<result_id>')
def shared_result(result_id):
    data = session.get(f'result_{result_id}')
    if not data:
        return render_template('errors/404.html'), 404
    return render_template('shared_result.html', **data)


@diagnosis_bp.route('/predict-enhanced', methods=['POST'])
def predict_enhanced():
    """LLM-enhanced disease prediction API."""
    try:
        data = request.get_json()
        if not data or 'symptoms' not in data:
            return jsonify({"error": "Missing symptoms in request"}), 400

        is_valid, symptoms, validation_error = validate_symptoms(data['symptoms'])
        if not is_valid:
            return jsonify({"error": validation_error}), 400

        user_id = data.get('user_id')
        user_profile = session.get(f'user_{user_id}') if user_id else None
        top_k = data.get('top_k', 3)

        predictions = predict_disease_with_confidence(symptoms, top_k)
        if not predictions:
            return jsonify({"error": "Unable to analyze symptoms. Please provide more detailed information."}), 400

        primary_prediction = predictions[0]['disease']
        basic_recommendations = get_recommendations(primary_prediction, user_profile)

        enhanced_predictions = medical_llm.analyze_symptoms_with_confidence(symptoms, predictions)
        disease_info = get_disease_info(primary_prediction)
        simplified_explanation = medical_llm.generate_patient_friendly_explanation(primary_prediction, symptoms, disease_info)
        enhanced_recommendations = medical_llm.generate_personalized_recommendations(primary_prediction, basic_recommendations, user_profile)

        for pred in enhanced_predictions:
            if 'symptoms' not in pred:
                pred['symptoms'] = get_symptoms(pred['disease'])

        return jsonify({
            'predictions': enhanced_predictions,
            'primary_prediction': primary_prediction,
            'recommendations': enhanced_recommendations,
            'simplified_explanation': simplified_explanation,
        })

    except Exception as e:
        logger.error(f"Error in predict_enhanced: {e}", exc_info=True)
        return jsonify({"error": "An error occurred during prediction. Please try again."}), 500


@diagnosis_bp.route('/diseases-list')
def diseases_list_page():
    return render_template('diseases_list.html', diseases=diseases_list)


@diagnosis_bp.route('/diseases', methods=['GET'])
def get_all_diseases():
    response = jsonify({"diseases": diseases_list})
    response.headers['Content-Type'] = 'application/json'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


@diagnosis_bp.route('/api/symptoms', methods=['GET'])
def get_symptoms_api():
    """Return all known symptoms for autocomplete, optionally filtered by ?q=query."""
    q = request.args.get('q', '').lower().strip()
    all_symptoms = list(questionnaire.all_symptoms) if hasattr(questionnaire, 'all_symptoms') else []
    if not all_symptoms and medical_data is not None:
        seen = set()
        for col in ['Symptom1', 'Symptom2', 'Symptom3', 'Symptom4']:
            if col in medical_data.columns:
                for s in medical_data[col].dropna().unique():
                    seen.add(str(s).strip())
        all_symptoms = sorted(seen)
    if q:
        all_symptoms = [s for s in all_symptoms if q in s.lower()]
    response = jsonify({"symptoms": all_symptoms[:50]})
    response.headers['Content-Type'] = 'application/json'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


@diagnosis_bp.route('/disease/<name>', methods=['GET'])
def get_disease_info_route(name):
    info = get_disease_info(name)
    if 'error' in info:
        return jsonify(info), 404
    return jsonify(info)


@diagnosis_bp.route('/disease-dashboard/<disease_name>')
def disease_dashboard(disease_name):
    return render_template('disease_dashboard.html', disease_name=disease_name)


@diagnosis_bp.route('/api/disease-dashboard/<disease_name>')
def disease_dashboard_api(disease_name):
    try:
        disease_info = get_disease_info(disease_name)
        if 'error' in disease_info:
            return jsonify(disease_info), 404

        disease_symptoms = set(disease_info['symptoms'])
        all_diseases = medical_data['Disease'].unique().tolist()
        related_diseases = []
        for other in all_diseases:
            if other == disease_name:
                continue
            other_syms = set(get_symptoms(other))
            if other_syms:
                sim = len(disease_symptoms & other_syms) / len(disease_symptoms | other_syms)
                if sim > 0.2:
                    related_diseases.append({'name': other, 'similarity': round(sim * 100, 1),
                                             'common_symptoms': list(disease_symptoms & other_syms)})
        related_diseases.sort(key=lambda x: x['similarity'], reverse=True)

        recovery_timeline = {
            'mild': {'duration': '5-7 days', 'stages': [
                {'name': 'Early symptoms', 'duration': '1-2 days', 'description': 'Initial symptoms appear'},
                {'name': 'Peak symptoms', 'duration': '2-3 days', 'description': 'Symptoms reach their highest intensity'},
                {'name': 'Recovery', 'duration': '2-3 days', 'description': 'Symptoms gradually subside'},
            ]},
            'moderate': {'duration': '7-14 days', 'stages': [
                {'name': 'Early symptoms', 'duration': '1-3 days', 'description': 'Initial symptoms appear'},
                {'name': 'Peak symptoms', 'duration': '3-5 days', 'description': 'Symptoms reach their highest intensity'},
                {'name': 'Recovery', 'duration': '3-6 days', 'description': 'Symptoms gradually subside'},
            ]},
            'severe': {'duration': '14+ days', 'stages': [
                {'name': 'Early symptoms', 'duration': '1-3 days', 'description': 'Initial symptoms appear'},
                {'name': 'Peak symptoms', 'duration': '4-7 days', 'description': 'Symptoms reach their highest intensity'},
                {'name': 'Medical intervention', 'duration': '5-10 days', 'description': 'Professional treatment required'},
                {'name': 'Recovery', 'duration': '7-14 days', 'description': 'Gradual recovery with potential lingering symptoms'},
            ]},
        }

        complications = []
        if 'chronic' in disease_name.lower() or disease_name in ['Diabetes', 'Hypertension', 'Asthma']:
            complications.append({'name': 'Long-term Management Required',
                                   'description': 'This condition may require ongoing medical management', 'likelihood': 'High'})
        if disease_name in ['Pneumonia', 'COVID-19', 'Tuberculosis']:
            complications.append({'name': 'Respiratory Complications',
                                   'description': 'May lead to breathing difficulties in severe cases', 'likelihood': 'Medium'})

        return jsonify({
            'basic_info': disease_info,
            'related_diseases': related_diseases[:5],
            'recovery_timeline': recovery_timeline,
            'complications': complications,
            'specialist_types': get_specialists_for_disease(disease_name),
            'prevention_tips': get_prevention_tips(disease_name),
        })

    except Exception as e:
        logger.error(f"Error in disease dashboard: {e}", exc_info=True)
        return jsonify({"error": "Failed to generate disease dashboard"}), 500


@diagnosis_bp.route('/analyze-symptoms', methods=['POST'])
def analyze_symptoms():
    try:
        data = request.get_json()
        if not data or 'symptoms' not in data:
            return jsonify({"error": "Missing symptoms in request"}), 400

        is_valid, symptoms, validation_error = validate_symptoms(data['symptoms'])
        if not is_valid:
            return jsonify({"error": validation_error}), 400

        response = jsonify(symptom_analyzer.analyze_symptom_patterns(symptoms))
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.error(f"Error in analyze_symptoms: {e}", exc_info=True)
        return jsonify({"error": "An error occurred during symptom analysis. Please try again."}), 500


@diagnosis_bp.route('/detailed-analysis', methods=['POST'])
def get_detailed_analysis():
    try:
        data = request.get_json()
        if not data or 'symptoms' not in data:
            return jsonify({"error": "Missing symptoms in request"}), 400

        is_valid, symptoms, validation_error = validate_symptoms(data['symptoms'])
        if not is_valid:
            return jsonify({"error": validation_error}), 400

        top_k = data.get('top_k', 3)
        predictions = predict_disease_with_confidence(symptoms, top_k)
        detailed_analysis = symptom_analyzer.generate_detailed_analysis(symptoms, predictions)

        response = jsonify({"predictions": predictions, "analysis": detailed_analysis})
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.error(f"Error in detailed_analysis: {e}", exc_info=True)
        return jsonify({"error": "An error occurred during detailed analysis. Please try again."}), 500


@diagnosis_bp.route('/interactive-analyzer')
def interactive_analyzer():
    return render_template('interactive_analyzer.html')


@diagnosis_bp.route('/questionnaire')
def questionnaire_page():
    return render_template('questionnaire.html')


@diagnosis_bp.route('/symptom-questionnaire', methods=['POST'])
def interactive_symptom_questionnaire():
    try:
        data = request.get_json()
        if not data or 'symptoms' not in data:
            return jsonify({"error": "Missing symptoms in request"}), 400

        is_valid, symptoms, validation_error = validate_symptoms(data['symptoms'])
        if not is_valid:
            return jsonify({"error": validation_error}), 400

        previous_answers = data.get('previous_answers', {})
        pattern_analysis = symptom_analyzer.analyze_symptom_patterns(symptoms)

        primary_prediction = None
        if pattern_analysis['potential_matches']:
            primary_prediction = pattern_analysis['potential_matches'][0]['disease']

        followup_questions = symptom_analyzer._generate_followup_questions(
            symptoms, pattern_analysis['detected_symptoms'], primary_prediction
        )

        assessment = None
        conversation_step = previous_answers.get('conversation_step', 0)
        if conversation_step >= 2:
            assessment = {
                'possibleConditions': [
                    {'name': m['disease'], 'probability': min(round(m['score']), 95)}
                    for m in pattern_analysis['potential_matches'][:3]
                ],
                'recommendedAction': 'Please consult with a healthcare professional for a proper diagnosis.',
            }

        response = {
            "detected_symptoms": pattern_analysis['detected_symptoms'],
            "potential_conditions": [m['disease'] for m in pattern_analysis['potential_matches'][:3]],
            "followup_questions": followup_questions,
        }
        if assessment:
            response['assessment'] = assessment
        if conversation_step == 0:
            response['message'] = "Based on your description, I've detected some symptoms. Please confirm if these are correct."
        return jsonify(response)

    except Exception as e:
        logger.error(f"Error in symptom_questionnaire: {e}", exc_info=True)
        return jsonify({"error": "An error occurred during questionnaire generation",
                        "message": "I'm sorry, I encountered an error. Please try again."}), 500


@diagnosis_bp.route('/second-opinion', methods=['GET', 'POST'])
def second_opinion():
    """Run symptoms through two independent analysis paths and compare results."""
    if request.method == 'GET':
        return render_template('second_opinion.html', results=None)

    raw = request.form.get('symptoms', '')
    symptoms_text = _sanitize_input(raw)
    if not symptoms_text:
        return render_template('second_opinion.html', results=None,
                               error="Please describe your symptoms")

    symptom_list = [s.strip() for s in symptoms_text.split(',')]

    # --- Opinion A: model-based (BERT + SVC + direct match) ---
    try:
        svc_pred = predict_with_svc(symptom_list) if svc_model else None
        direct_matches = direct_symptom_matching(symptoms_text)
        bert_preds = predict_disease_with_confidence(symptoms_text, 3)
        if direct_matches and direct_matches[0]['confidence'] > 40:
            opinion_a = direct_matches[:3]
        elif bert_preds and bert_preds[0]['confidence'] > 5:
            opinion_a = bert_preds[:3]
        else:
            seen = set()
            opinion_a = []
            for p in ([svc_pred] if svc_pred else []) + direct_matches[:1] + bert_preds[:1]:
                if p and p['disease'] not in seen:
                    seen.add(p['disease'])
                    opinion_a.append(p)
        for p in opinion_a:
            p.setdefault('symptoms', get_symptoms(p['disease']))
    except Exception as e:
        logger.error(f"Second opinion (A) error: {e}")
        opinion_a = [{'disease': 'Analysis Error', 'confidence': 0.0, 'symptoms': []}]

    # --- Opinion B: LLM skeptic prompt ---
    opinion_b_text = None
    opinion_b_diseases = []
    try:
        primary_a = opinion_a[0]['disease'] if opinion_a else 'unknown'
        prompt = (
            f"A patient reports these symptoms: \"{symptoms_text}\".\n"
            f"A first diagnostic model suggested: {primary_a}.\n"
            "As a skeptical second-opinion clinician, list up to 3 ALTERNATIVE diagnoses that "
            "should also be considered (different from the first suggestion). "
            "For each, give: Disease name, one-sentence reasoning, and likelihood (Low/Moderate/High). "
            "Format strictly as:\n"
            "1. <Disease>: <reasoning> [<likelihood>]\n"
            "2. ...\n"
            "3. ..."
        )
        raw_b = llm._get_llm_response(prompt).strip()
        opinion_b_text = raw_b
        # Parse structured lines
        for line in raw_b.splitlines():
            line = line.strip()
            if not line or not line[0].isdigit():
                continue
            # strip leading "1. "
            content = line.split('.', 1)[-1].strip()
            if ':' in content:
                disease_part, rest = content.split(':', 1)
                disease_name = disease_part.strip()
                # extract likelihood
                likelihood = 'Unknown'
                for lvl in ['High', 'Moderate', 'Low']:
                    if lvl.lower() in rest.lower():
                        likelihood = lvl
                        break
                reasoning = rest.replace(f'[{likelihood}]', '').strip().strip('[]')
                opinion_b_diseases.append({
                    'disease': disease_name,
                    'reasoning': reasoning,
                    'likelihood': likelihood,
                    'symptoms': get_symptoms(disease_name),
                })
    except Exception as e:
        logger.error(f"Second opinion (B) LLM error: {e}")
        opinion_b_text = "LLM provider not configured or unavailable."

    # Highlight diseases in common
    a_names = {p['disease'].lower() for p in opinion_a}
    b_names = {p['disease'].lower() for p in opinion_b_diseases}
    overlap = a_names & b_names

    return render_template(
        'second_opinion.html',
        symptoms=symptoms_text,
        opinion_a=opinion_a,
        opinion_b=opinion_b_diseases,
        opinion_b_raw=opinion_b_text,
        overlap=overlap,
        results=True,
    )


@diagnosis_bp.route('/questionnaire/start', methods=['GET'])
def start_questionnaire():
    try:
        initial_questions = [
            "Fever", "Headache", "Cough", "Fatigue", "Shortness of breath",
            "Nausea", "Chest pain", "Abdominal pain", "Muscle pain",
            "Joint pain", "Skin rash", "Sore throat", "Sneezing", "Runny nose",
        ]
        if hasattr(questionnaire, 'get_initial_questions'):
            try:
                initial_questions = questionnaire.get_initial_questions()
            except Exception as e:
                logger.error(f"Error getting initial questions: {e}")

        session_id = str(uuid.uuid4())
        session[f'questionnaire_{session_id}'] = {
            'confirmed_symptoms': [], 'excluded_symptoms': [], 'current_step': 1
        }
        return jsonify({'session_id': session_id, 'questions': initial_questions,
                        'step': 1, 'total_steps': 5,
                        'message': 'Please select any symptoms that apply to you:'})
    except Exception as e:
        logger.error(f"Error starting questionnaire: {e}", exc_info=True)
        return jsonify({"error": "Failed to start questionnaire"}), 500


@diagnosis_bp.route('/questionnaire/respond', methods=['POST'])
def questionnaire_respond():
    data = request.get_json()
    if not data or 'session_id' not in data:
        return jsonify({"error": "Missing session ID"}), 400

    session_id = data['session_id']
    session_key = f'questionnaire_{session_id}'
    if session_key not in session:
        return jsonify({"error": "Invalid session ID"}), 400

    state = session[session_key]
    confirmed = state['confirmed_symptoms']
    excluded = state['excluded_symptoms']
    step = state['current_step']

    confirmed += [s for s in data.get('confirmed', []) if s not in confirmed]
    excluded += [s for s in data.get('excluded', []) if s not in excluded]
    step += 1
    session[session_key] = {'confirmed_symptoms': confirmed, 'excluded_symptoms': excluded, 'current_step': step}

    if step >= 5 or len(confirmed) >= 4:
        probable_diseases = questionnaire.get_probable_diseases(confirmed)
        if probable_diseases:
            for disease in probable_diseases:
                disease['symptoms'] = get_symptoms(disease['disease'])
            primary = probable_diseases[0]['disease']
            return jsonify({
                'session_id': session_id, 'status': 'complete',
                'confirmed_symptoms': confirmed, 'predictions': probable_diseases,
                'recommendations': get_recommendations(primary),
                'message': 'Based on your symptoms, we have the following assessment:',
            })

    next_questions = questionnaire.get_next_questions(confirmed, excluded)
    return jsonify({
        'session_id': session_id, 'questions': next_questions,
        'step': step, 'total_steps': 5, 'confirmed_symptoms': confirmed,
        'message': 'Please select any additional symptoms:',
        'probable_diseases': questionnaire.get_probable_diseases(confirmed, min_symptoms=1),
    })
