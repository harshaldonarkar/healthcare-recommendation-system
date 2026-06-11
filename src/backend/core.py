# src/backend/core.py
# Shared state, models, and helper functions used across all blueprints

import os
import re
import json
import math
import uuid
import pickle
import logging
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from datetime import datetime, timedelta
from functools import wraps, lru_cache
import threading

from flask import session, redirect, url_for, request
from dotenv import load_dotenv
from transformers import (
    BertTokenizer, BertForSequenceClassification,
    DistilBertTokenizerFast, DistilBertForSequenceClassification,
)

from utils import parse_medicine_list
from llm_integration import LLMIntegration
from medical_llm_integration import MedicalLLMIntegration
from symptom_analysis import SymptomAnalyzer
from symptom_questionnaire import SymptomQuestionnaire
from progress_tracker import ProgressTracker
from medication_reminder import MedicationReminder
from lab_analysis import PathlabAnalyzer
from doctor_search import DoctorSearch

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, 'data')
MODELS_DIR = os.path.join(ROOT_DIR, 'models')
FINE_TUNED_MODEL_DIR = os.path.join(MODELS_DIR, 'fine_tuned_model')
DDXPLUS_MODEL_DIR    = os.path.join(MODELS_DIR, 'ddxplus_model')

# ---------------------------------------------------------------------------
# LLM integrations
# ---------------------------------------------------------------------------
llm_provider = os.environ.get('LLM_PROVIDER', 'huggingface')
llm = LLMIntegration(llm_provider=llm_provider)
medical_llm = MedicalLLMIntegration(provider=llm_provider)

# ---------------------------------------------------------------------------
# Service objects
# ---------------------------------------------------------------------------
medication_reminder = MedicationReminder(os.path.join(DATA_DIR, 'medication_reminders.json'))
lab_analyzer = PathlabAnalyzer(os.path.join(DATA_DIR, 'medical_data_complete.csv'))
doctor_search = DoctorSearch()
progress_tracker = ProgressTracker(os.path.join(DATA_DIR, 'progress_data.json'))
questionnaire = SymptomQuestionnaire(os.path.join(DATA_DIR, 'medical_data_complete.csv'))
symptom_analyzer = SymptomAnalyzer(
    os.path.join(DATA_DIR, 'medical_data_complete.csv'),
    llm_integration=medical_llm
)

# ---------------------------------------------------------------------------
# Medical dataset and label map
# ---------------------------------------------------------------------------
try:
    medical_data = pd.read_csv(os.path.join(DATA_DIR, 'medical_data_complete.csv'))
    logger.info(f"Medical dataset loaded with {len(medical_data)} diseases")

    with open(os.path.join(FINE_TUNED_MODEL_DIR, 'label_map.json'), 'r') as f:
        label_map = json.load(f)

    disease_to_label = {v: k for k, v in label_map.items()}
    diseases_list = list(disease_to_label.keys())
except Exception as e:
    logger.error(f"Failed to load medical dataset: {str(e)}")
    medical_data = None
    diseases_list = []
    label_map = {}
    disease_to_label = {}

# ---------------------------------------------------------------------------
# TF-IDF + LogisticRegression model
# ---------------------------------------------------------------------------
TFIDF_DIR = os.path.join(MODELS_DIR, 'tfidf_model')

try:
    _tfidf_vec = pickle.load(open(os.path.join(TFIDF_DIR, 'tfidf_vectorizer.pkl'), 'rb'))
    _tfidf_lr  = pickle.load(open(os.path.join(TFIDF_DIR, 'lr_classifier.pkl'), 'rb'))
    logger.info("TF-IDF model loaded successfully")
except Exception as e:
    logger.warning(f"TF-IDF model not found (run training first): {e}")
    _tfidf_vec = None
    _tfidf_lr  = None

# ---------------------------------------------------------------------------
# Legacy SVC model (kept for backwards compatibility; ignored if file missing)
# ---------------------------------------------------------------------------
try:
    svc_model = pickle.load(open(os.path.join(MODELS_DIR, 'svc.pkl'), 'rb'))
    symptoms_dict = {}
    diseases_list_svc = {}
except Exception:
    svc_model = None
    symptoms_dict = {}
    diseases_list_svc = {}

# ---------------------------------------------------------------------------
# BERT model (lazy-loaded and thread-safe)
# ---------------------------------------------------------------------------
_model_instance = None
_tokenizer_instance = None
_model_lock = threading.Lock()


def get_model():
    global _model_instance, _tokenizer_instance
    if _model_instance is None:
        with _model_lock:
            # Double-check pattern to avoid redundant loading
            if _model_instance is None:
                logger.info("Loading BERT model...")
                _tokenizer_instance = BertTokenizer.from_pretrained(FINE_TUNED_MODEL_DIR)
                _model_instance = BertForSequenceClassification.from_pretrained(FINE_TUNED_MODEL_DIR)
                _model_instance.eval()
                logger.info("BERT model loaded successfully")
    return _model_instance, _tokenizer_instance


# ---------------------------------------------------------------------------
# DDXPlus DistilBERT+KL model (lazy-loaded, thread-safe)
# ---------------------------------------------------------------------------
_ddx_model_instance    = None
_ddx_tokenizer_instance = None
_ddx_model_lock        = threading.Lock()

# Load DDXPlus label map once at import time (small JSON, always present)
try:
    with open(os.path.join(DDXPLUS_MODEL_DIR, 'ddxplus_label_map.json')) as _f:
        _ddx_label_map = json.load(_f)   # {"0": "Acute COPD ...", ...}
    logger.info(f"DDXPlus label map loaded: {len(_ddx_label_map)} diseases")
except Exception as _e:
    logger.warning(f"DDXPlus label map not found: {_e}")
    _ddx_label_map = {}


def _get_ddx_model():
    """Lazy-load the DDXPlus DistilBERT+KL model (thread-safe double-check locking)."""
    global _ddx_model_instance, _ddx_tokenizer_instance
    if _ddx_model_instance is None:
        with _ddx_model_lock:
            if _ddx_model_instance is None:
                logger.info("Loading DDXPlus DistilBERT+KL model…")
                _ddx_tokenizer_instance = DistilBertTokenizerFast.from_pretrained(DDXPLUS_MODEL_DIR)
                _ddx_model_instance = DistilBertForSequenceClassification.from_pretrained(DDXPLUS_MODEL_DIR)
                _ddx_model_instance.eval()
                logger.info("DDXPlus model loaded successfully")
    return _ddx_model_instance, _ddx_tokenizer_instance


def predict_with_ddxplus(symptoms_text: str, top_k: int = 5):
    """Return a ranked differential diagnosis using the DDXPlus DistilBERT+KL model.

    The model was fine-tuned on human-readable symptom text in the format:
        "35 year old male. chest pain, shortness of breath, cough."
    Plain free-text symptom descriptions work well because the model was trained
    on decoded, natural-language symptom sentences from the DDXPlus dataset.

    Returns a list of dicts sorted by probability (descending):
        [{"disease": str, "confidence": float (0-100), "rank": int}, ...]
    or None if the model is unavailable or inference fails.
    """
    if not _ddx_label_map:
        return None
    try:
        model, tokenizer = _get_ddx_model()
        cleaned = re.sub(r'\s+', ' ', symptoms_text.strip())
        inputs = tokenizer(
            cleaned,
            max_length=128,
            padding='max_length',
            truncation=True,
            return_tensors='pt',
        )
        with torch.no_grad():
            logits = model(**inputs).logits
        probs = F.softmax(logits, dim=1)[0]
        top_probs, top_indices = torch.topk(probs, min(top_k, len(_ddx_label_map)))
        results = []
        for rank, (prob, idx) in enumerate(zip(top_probs, top_indices), start=1):
            disease = _ddx_label_map.get(str(idx.item()))
            if disease:
                results.append({
                    'disease':    disease,
                    'confidence': round(float(prob) * 100, 1),
                    'rank':       rank,
                })
        return results if results else None
    except Exception as e:
        logger.error(f"DDXPlus prediction error: {e}")
        return None


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
SESSION_TIMEOUT = timedelta(minutes=60)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login', next=request.path))
        last = session.get('last_active')
        if last and datetime.now() - datetime.fromisoformat(last) > SESSION_TIMEOUT:
            session.clear()
            return redirect(url_for('auth.login', next=request.path))
        session['last_active'] = datetime.now().isoformat()
        return f(*args, **kwargs)
    return decorated_function


def get_status_color(status):
    return {'active': 'primary', 'completed': 'success', 'archived': 'secondary', 'on_hold': 'warning'}.get(status, 'primary')


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def validate_symptoms(text, max_length=2000):
    """Validate and sanitize symptom text input.

    Args:
        text: symptom text to validate
        max_length: maximum allowed length

    Returns:
        tuple: (is_valid, sanitized_text, error_message)
    """
    if not text or not isinstance(text, str):
        return False, "", "Symptoms text is required"

    stripped = text.strip()
    if len(stripped) == 0:
        return False, "", "Symptoms text cannot be empty"

    if len(stripped) > max_length:
        return False, "", f"Symptoms text exceeds maximum length of {max_length} characters"

    # Remove HTML tags
    sanitized = re.sub(r'<[^>]+>', '', stripped)
    sanitized = sanitized.strip()

    if len(sanitized) == 0:
        return False, "", "Symptoms text cannot contain only HTML tags"

    return True, sanitized, None


@lru_cache(maxsize=128)
def _get_diseases_list_cached():
    """Cache the sorted list of diseases."""
    try:
        if medical_data is not None:
            return sorted(medical_data['Disease'].unique().tolist())
    except Exception as e:
        logger.error(f"Error caching disease list: {e}")
    return []


def get_disease_list_cached():
    """Get cached disease list."""
    return _get_diseases_list_cached()


# ---------------------------------------------------------------------------
# Disease / symptom helpers
# ---------------------------------------------------------------------------

# The BERT label map spells several diseases differently than the CSV
# (e.g. 'Aids' vs 'AIDS', 'Chicken Pox' vs 'Chickenpox'), so model
# predictions would otherwise fail the info/recommendation lookups.
_DISEASE_NAME_ALIASES = {
    '(vertigo) paroymsal positional vertigo': 'Vertigo (Paroxysmal Positional Vertigo)',
    'dimorphic hemmorhoids(piles)': 'Dimorphic Hemorrhoids (Piles)',
    'chicken pox': 'Chickenpox',
    'osteoarthristis': 'Osteoarthritis',
    'peptic ulcer diseae': 'Peptic Ulcer Disease',
}

try:
    _DISEASE_BY_KEY = {str(d).strip().lower(): str(d) for d in medical_data['Disease'].unique()}
except Exception:
    _DISEASE_BY_KEY = {}
_DISEASE_BY_KEY.update(_DISEASE_NAME_ALIASES)


def resolve_disease_name(disease_name):
    """Map a model label or user-supplied spelling to the canonical CSV name."""
    return _DISEASE_BY_KEY.get(str(disease_name).strip().lower(), disease_name)


def get_symptoms(disease_name):
    try:
        if disease_name == 'Prediction Error':
            return ['Unable to determine symptoms due to prediction error']
        disease_name = resolve_disease_name(disease_name)
        disease_data = medical_data[medical_data['Disease'] == disease_name]
        if disease_data.empty:
            return []
        row = disease_data.iloc[0]
        return [row['Symptom1'], row['Symptom2'], row['Symptom3'], row['Symptom4']]
    except Exception as e:
        logger.error(f"Error retrieving symptoms: {e}")
        return []


@lru_cache(maxsize=256)
def get_disease_info(disease_name):
    """Get disease information with caching.

    Note: lru_cache requires hashable arguments, so disease_name must be a string.
    """
    try:
        if disease_name == 'Prediction Error':
            return {
                'name': 'Prediction Error',
                'symptoms': ['Unable to determine symptoms due to prediction error'],
                'causes': 'Unable to determine causes due to prediction error',
                'medicines': ['Consult a healthcare professional'],
                'diet': 'Maintain a balanced diet and consult a healthcare professional',
                'workout': 'Regular gentle exercise as appropriate',
                'precautions': [
                    'Consult a healthcare professional', 'Monitor symptoms',
                    'Seek medical attention if symptoms worsen',
                    'Consider providing more detailed symptom information',
                ],
            }
        disease_name = resolve_disease_name(disease_name)
        disease_data = medical_data[medical_data['Disease'] == disease_name]
        if disease_data.empty:
            return {"error": f"Disease '{disease_name}' not found"}
        row = disease_data.iloc[0]
        try:
            medicines = parse_medicine_list(row['Medicines'])
        except Exception:
            medicines = []
        return {
            'name': disease_name,
            'symptoms': [row['Symptom1'], row['Symptom2'], row['Symptom3'], row['Symptom4']],
            'causes': row['Causes'],
            'medicines': medicines,
            'diet': row['Diets'],
            'workout': row['Workout'],
            'precautions': [row['Precaution1'], row['Precaution2'], row['Precaution3'], row['Precaution4']],
        }
    except Exception as e:
        logger.error(f"Error retrieving disease info: {e}")
        return {"error": "Failed to retrieve disease information"}


def get_recommendations(disease_name, user_profile=None):
    """Get disease recommendations, with caching for base data.

    Note: Not directly cached due to user_profile parameter, but calls get_disease_info
    which is cached.
    """
    try:
        if disease_name == 'Prediction Error':
            return {
                'causes': 'Unable to determine causes due to prediction error',
                'medicines': ['Consult a healthcare professional'],
                'diet': 'Maintain a balanced diet and consult a healthcare professional',
                'workout': 'Regular gentle exercise as appropriate',
                'precautions': ['Consult a healthcare professional', 'Monitor symptoms', 'Seek medical attention if symptoms worsen'],
            }
        disease_name = resolve_disease_name(disease_name)
        disease_data = medical_data[medical_data['Disease'] == disease_name]
        if disease_data.empty:
            return {"error": f"No data available for {disease_name}"}
        row = disease_data.iloc[0]
        try:
            medicines = parse_medicine_list(row['Medicines'])
        except Exception:
            medicines = []
        if user_profile and 'allergies' in user_profile:
            medicines = [m for m in medicines if m.lower() not in [a.lower() for a in user_profile['allergies']]]
        return {
            'causes': row['Causes'],
            'medicines': medicines,
            'diet': row['Diets'],
            'workout': row['Workout'],
            'precautions': [row['Precaution1'], row['Precaution2'], row['Precaution3'], row['Precaution4']],
        }
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        return {
            "error": "Failed to generate recommendations",
            'causes': 'Unable to determine causes',
            'medicines': ['Consult a healthcare professional'],
            'diet': 'Maintain a balanced diet and consult a healthcare professional',
            'workout': 'Regular gentle exercise as appropriate',
            'precautions': ['Consult a healthcare professional', 'Monitor symptoms', 'Seek medical attention if symptoms worsen'],
        }


def direct_symptom_matching(symptoms_text, threshold=0.2):
    normalized_input = symptoms_text.lower().replace(',', ' ')
    input_symptoms = set(normalized_input.split())
    results = []
    for _, row in medical_data.iterrows():
        disease_symptoms = [str(row[f'Symptom{i}']).lower() for i in range(1, 5)]
        disease_words = set(w for s in disease_symptoms for w in s.split())
        word_score = len(input_symptoms.intersection(disease_words)) / len(input_symptoms) if input_symptoms else 0
        exact_score = sum(1 for s in disease_symptoms if s in normalized_input) / 4.0
        final_score = max(word_score, exact_score)
        if final_score >= threshold:
            results.append({'disease': row['Disease'], 'confidence': final_score * 100, 'symptoms': [s for s in disease_symptoms if s]})

    malaria_keywords = ["high fever", "chills", "sweating", "muscle pain"]
    if all(s in normalized_input for s in malaria_keywords):
        for result in results:
            if result['disease'] == 'Malaria':
                result['confidence'] = 95.0
                break
        else:
            malaria_record = medical_data[medical_data['Disease'] == 'Malaria']
            if not malaria_record.empty:
                results.append({
                    'disease': 'Malaria',
                    'confidence': 95.0,
                    'symptoms': [str(malaria_record.iloc[0][f'Symptom{i}']).lower() for i in range(1, 5)],
                })

    return sorted(results, key=lambda x: x['confidence'], reverse=True)


def predict_with_tfidf(symptoms_text, top_k=3):
    """Predict disease using the TF-IDF + LogisticRegression model."""
    if _tfidf_vec is None or _tfidf_lr is None:
        return None
    try:
        cleaned = re.sub(r'\s+', ' ', re.sub(r'[^\w\s,]', ' ', symptoms_text.lower())).strip()
        vec     = _tfidf_vec.transform([cleaned])
        probs   = _tfidf_lr.predict_proba(vec)[0]
        top_idx = np.argsort(probs)[::-1][:top_k]
        results = []
        for idx in top_idx:
            disease = label_map.get(str(idx))
            if disease and probs[idx] > 0.01:
                results.append({
                    'disease':    disease,
                    'confidence': float(probs[idx]) * 100,
                    'symptoms':   get_symptoms(disease),
                })
        return results if results else None
    except Exception as e:
        logger.error(f"TF-IDF prediction error: {e}")
        return None


def predict_with_svc(symptoms_list):
    try:
        if svc_model is None:
            return None
        input_vector = np.zeros(len(symptoms_dict))
        for symptom in symptoms_list:
            if symptom.strip() in symptoms_dict:
                input_vector[symptoms_dict[symptom.strip()]] = 1
        prediction = svc_model.predict([input_vector])[0]
        # New model stores disease names in classes_; old model stores integer indices
        if hasattr(svc_model, 'classes_') and isinstance(svc_model.classes_[0], str):
            predicted_disease = prediction
        else:
            predicted_disease = diseases_list_svc.get(prediction, "Unknown Disease")
        return {'disease': predicted_disease, 'confidence': 90.0, 'symptoms': get_symptoms(predicted_disease)}
    except Exception as e:
        logger.error(f"Error in SVC prediction: {e}")
        return None


def predict_disease_with_confidence(symptoms, top_k=3):
    try:
        normalized = symptoms.lower()
        malaria_keywords = ["high fever", "chills", "sweating", "muscle pain"]
        if all(s in normalized for s in malaria_keywords):
            malaria_data = medical_data[medical_data['Disease'] == 'Malaria']
            if not malaria_data.empty:
                return [{'disease': 'Malaria', 'confidence': 95.0,
                         'symptoms': [str(malaria_data.iloc[0][f'Symptom{i}']) for i in range(1, 5)]}]

        model, tokenizer = get_model()
        processed = re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', normalized)).strip()
        inputs = tokenizer(processed, padding=True, truncation=True, max_length=128, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
        probabilities = F.softmax(outputs.logits, dim=1)[0]
        top_probs, top_indices = torch.topk(probabilities, min(top_k, len(label_map)))

        results = []
        for prob, idx in zip(top_probs, top_indices):
            label_key = str(idx.item())
            disease_name = label_map.get(label_key)
            if disease_name is None:
                for k, v in label_map.items():
                    try:
                        if int(k) == idx.item():
                            disease_name = v
                            break
                    except Exception:
                        continue
            if disease_name:
                results.append({'disease': disease_name, 'confidence': float(prob) * 100})

        # If BERT confidence is low, try TF-IDF then direct matching
        if not results or results[0]['confidence'] < 15.0:
            tfidf_results = predict_with_tfidf(symptoms, top_k)
            if tfidf_results and tfidf_results[0]['confidence'] > (results[0]['confidence'] if results else 0):
                return tfidf_results
            direct_matches = direct_symptom_matching(symptoms)
            if direct_matches and (not results or direct_matches[0]['confidence'] > results[0]['confidence']):
                return direct_matches[:top_k]

        for pred in results:
            if 'symptoms' not in pred:
                pred['symptoms'] = get_symptoms(pred['disease'])

        return results or [{'disease': 'Prediction Error', 'confidence': 0.0,
                            'symptoms': ['Unable to match prediction to a known disease']}]

    except Exception as e:
        logger.error(f"Error in predict_disease_with_confidence: {e}")
        try:
            tfidf_results = predict_with_tfidf(symptoms, top_k)
            if tfidf_results:
                return tfidf_results
        except Exception:
            pass
        try:
            direct_matches = direct_symptom_matching(symptoms)
            if direct_matches:
                return direct_matches[:top_k]
        except Exception:
            pass
        return [{'disease': 'Prediction Error', 'confidence': 0.0, 'symptoms': ['Error processing symptoms']}]


# ---------------------------------------------------------------------------
# Lab helpers — delegate to DB module, fall back to empty results if DB is down
# ---------------------------------------------------------------------------
def save_lab_result(user_id, result):
    """user_id here is the username string."""
    try:
        import db
        db.save_lab_result(
            username=user_id,
            test_name=result.get('test_name', ''),
            value=result.get('value', 0),
            unit=result.get('unit', ''),
            test_date=result.get('test_date'),
        )
    except Exception as e:
        logger.warning(f"save_lab_result: {e}")


def get_user_profile(user_id):
    """user_id here is the username string."""
    try:
        import db
        return db.get_user_profile(user_id)
    except Exception as e:
        logger.warning(f"get_user_profile: {e}")
        return {'conditions': [], 'allergies': [], 'age': None, 'gender': None}


def get_user_lab_history(user_id, start_date=None, end_date=None, test_name=None):
    try:
        import db
        return db.get_lab_history(user_id, start_date, end_date, test_name)
    except Exception as e:
        logger.warning(f"get_user_lab_history: {e}")
        return []


def get_historical_lab_data(user_id, test_name):
    try:
        import db
        return db.get_lab_history(user_id, test_name=test_name)
    except Exception as e:
        logger.warning(f"get_historical_lab_data: {e}")
        return []


def analyze_lab_trends(historical_data):
    if not historical_data:
        return None
    values = [d['value'] for d in historical_data]
    change_rate = (values[-1] - values[0]) / len(values) if len(values) > 1 else 0
    return {
        'mean': np.mean(values),
        'latest': values[-1],
        'trend': 'increasing' if change_rate > 0 else 'decreasing' if change_rate < 0 else 'stable',
        'change_rate': change_rate,
    }


def prepare_chart_data(historical_data):
    return [{'date': d['test_date'], 'value': d['value']} for d in historical_data] if historical_data else []


def calculate_baseline(history):
    sample = history[:3] if len(history) >= 3 else history
    return sum(h['value'] for h in sample) / len(sample)


def analyze_baseline_comparison(baseline, latest_result):
    pct = ((latest_result['value'] - baseline) / baseline) * 100
    if abs(pct) <= 10:
        classification, recommendation = "Within normal variation", "Monitor regularly"
    elif pct > 10:
        classification = "Elevated from baseline"
        recommendation = "Significant increase - consult healthcare provider" if abs(pct) > 30 else "Mild increase - monitor closely"
    else:
        classification = "Decreased from baseline"
        recommendation = "Significant decrease - consult healthcare provider" if abs(pct) > 30 else "Mild decrease - monitor closely"
    return {'percentage_change': pct, 'classification': classification, 'recommendation': recommendation}


def create_test_reminder(user_id, test_name, reminder_date, notes='', associated_plan_id=None):
    return str(uuid.uuid4())


def generate_monitoring_schedule(disease, recommendations):
    frequency_map = {5: "Monthly", 4: "Quarterly", 3: "Semi-annually", 2: "Annually", 1: "As needed"}
    return [
        {
            'test_name': rec['test_name'],
            'frequency': frequency_map.get(rec.get('priority', 3), "As needed"),
            'next_recommended': calculate_next_test_date(frequency_map.get(rec.get('priority', 3), "As needed")),
        }
        for rec in recommendations
    ]


def calculate_next_test_date(frequency):
    offsets = {"Monthly": 30, "Quarterly": 90, "Semi-annually": 180, "Annually": 365}
    days = offsets.get(frequency)
    return (datetime.now() + timedelta(days=days)).isoformat() if days else None


# ---------------------------------------------------------------------------
# Disease dashboard helpers
# ---------------------------------------------------------------------------
def get_specialists_for_disease(disease):
    specialists = []
    checks = [
        (['heart', 'coronary', 'hypertension'], 'Cardiologist', 'Specializes in heart and cardiovascular disorders'),
        (['lung', 'respiratory', 'asthma', 'pneumonia', 'bronchitis'], 'Pulmonologist', 'Specializes in lung and respiratory disorders'),
        (['skin', 'rash', 'eczema', 'dermatitis'], 'Dermatologist', 'Specializes in skin disorders'),
        (['joint', 'arthritis', 'rheumatoid'], 'Rheumatologist', 'Specializes in joint and autoimmune disorders'),
        (['nerve', 'brain', 'migraine', 'epilepsy'], 'Neurologist', 'Specializes in nervous system disorders'),
    ]
    for keywords, specialist_type, description in checks:
        if any(k in disease.lower() for k in keywords):
            specialists.append({'type': specialist_type, 'description': description})
    specialists.append({'type': 'General Practitioner', 'description': 'For initial diagnosis and treatment'})
    return specialists


def get_prevention_tips(disease):
    generic = [
        "Maintain a balanced diet rich in fruits and vegetables",
        "Exercise regularly as appropriate for your condition",
        "Ensure adequate sleep and stress management",
        "Wash hands frequently and maintain good hygiene",
    ]
    specific = []
    if any(t in disease.lower() for t in ['flu', 'cold', 'covid', 'respiratory']):
        specific += ["Avoid close contact with sick individuals", "Use a tissue or elbow when coughing or sneezing", "Consider appropriate vaccinations when available"]
    if any(t in disease.lower() for t in ['diabetes', 'hypertension', 'heart']):
        specific += ["Monitor your blood pressure and/or blood sugar regularly", "Limit intake of processed foods, sugar, and salt", "Maintain a healthy weight through diet and exercise"]
    if any(t in disease.lower() for t in ['allergy', 'asthma']):
        specific += ["Identify and avoid known allergens or triggers", "Keep living spaces clean and free of dust and mold", "Use air purifiers in your home if appropriate"]
    return generic + specific


# ---------------------------------------------------------------------------
# Geolocation helper
# ---------------------------------------------------------------------------
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1r, lon1r = math.radians(lat1), math.radians(lon1)
    lat2r, lon2r = math.radians(lat2), math.radians(lon2)
    dlat, dlon = lat2r - lat1r, lon2r - lon1r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
