# src/backend/blueprints/lab.py
import io
import logging
import re
import uuid
from datetime import datetime

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from flask import Blueprint, render_template, request, jsonify, session

from core import (
    login_required, lab_analyzer,
    save_lab_result, get_user_profile, get_user_lab_history,
    get_historical_lab_data, analyze_lab_trends, prepare_chart_data,
    calculate_baseline, analyze_baseline_comparison, create_test_reminder,
)

logger = logging.getLogger(__name__)

lab_bp = Blueprint('lab', __name__)


# ---------------------------------------------------------------------------
# PDF / image text extraction
# ---------------------------------------------------------------------------
def extract_text_from_pdf(pdf_document):
    text = ""
    for page in pdf_document:
        text += page.get_text()
    if not text.strip():
        for page in pdf_document:
            text += page.get_text("text")
            text += page.get_text("blocks")
    if not text.strip():
        for page_num in range(len(pdf_document)):
            pix = pdf_document[page_num].get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text += pytesseract.image_to_string(img)
    return text


_KEYWORD_ALIASES = {
    # Glucose — longer aliases checked first (sorted by length later)
    'fasting plasma glucose': 'blood_glucose_fasting',
    'fasting blood glucose': 'blood_glucose_fasting',
    'fasting glucose': 'blood_glucose_fasting',
    'mean plasma glucose': '_skip',   # prevent plain "glucose" grabbing this
    'glucose': 'blood_glucose_fasting',
    # HbA1c
    'hba1c': 'hba1c', 'hba1': 'hba1c',
    # CBC
    'haemoglobin': 'hemoglobin', 'hemoglobin': 'hemoglobin',
    'wbc': 'wbc_count', 'tlc': 'wbc_count',
    'rbc': 'rbc_count',
    'platelet': 'platelet_count',
    'hematocrit': 'hematocrit', 'pcv': 'hematocrit',
    'mcv': 'mcv',
    'mchc': 'mchc',   # MCHC before MCH so substring match doesn't occur
    'mch': 'mch',
    # Lipids
    'total cholesterol': 'total_cholesterol',  # phrase before plain 'cholesterol'
    'cholesterol': 'total_cholesterol',
    'ldl': 'ldl_cholesterol',
    'hdl': 'hdl_cholesterol',
    'triglycerides': 'triglycerides',   # with 's' to match the full word
    'triglyceride': 'triglycerides',
    # Kidney
    'creatinine': 'creatinine',
    'blood urea nitrogen': 'bun_nitrogen',   # BUN ≠ blood urea; keep separate
    'bun': 'bun_nitrogen',
    'blood urea': 'urea', 'urea': 'urea',
    'uric acid': 'uric_acid',
    # Electrolytes
    'sodium': 'sodium',
    'potassium': 'potassium',
    'chloride': 'chloride',
    # Liver
    'sgot': 'ast_sgot', 'ast': 'ast_sgot',
    'sgpt': 'alt_sgpt', 'alt': 'alt_sgpt',
    'bilirubin total': 'bilirubin', 'bilirubin': 'bilirubin',
    'alkaline phosphatase': 'alkaline_phosphatase', 'alp': 'alkaline_phosphatase',
    'ggt': 'ggt',
    # Thyroid
    'tsh': 'thyroid_tsh',
    't3': 't3', 't4': 't4',
    # Vitamins / Iron
    'vitamin d': 'vitamin_d',
    'vitamin b12': 'vitamin_b12', 'b12': 'vitamin_b12',
    'ferritin': 'ferritin',
    'iron': 'serum_iron',
}

# Reasonable max values per test to reject phone numbers / zip codes as false positives
_MAX_PLAUSIBLE = {
    'hemoglobin': 25, 'blood_glucose_fasting': 800, 'hba1c': 20,
    'total_cholesterol': 800, 'ldl_cholesterol': 600, 'hdl_cholesterol': 300,
    'triglycerides': 3000, 'wbc_count': 100, 'rbc_count': 10,
    'platelet_count': 3000, 'hematocrit': 65, 'mcv': 150, 'mch': 60, 'mchc': 50,
    'creatinine': 30, 'urea': 300, 'uric_acid': 30,
    'sodium': 200, 'potassium': 15, 'chloride': 200,
    'alt_sgpt': 5000, 'ast_sgot': 5000, 'bilirubin': 50, 'alkaline_phosphatase': 2000,
    'ggt': 2000, 'thyroid_tsh': 200, 't3': 500, 't4': 30,
    'vitamin_d': 200, 'vitamin_b12': 5000, 'serum_iron': 500, 'ferritin': 5000,
}


def _is_value_line(line_stripped):
    """Return (value, flag) if line is a lab result value, else None.

    Handles both plain values ("14.90") and H/L-flagged values ("78.50 L",
    "235.00 H") in either case — lines are lowercased before reaching here.
    """
    m = re.match(r'^(\d+\.?\d*)\s*([HhLl])?\s*$', line_stripped)
    if m:
        return float(m.group(1)), (m.group(2) or '').upper()
    return None


def _is_ref_range(line_stripped):
    """Return True if line looks like a reference range: "13.00 - 17.00"."""
    return bool(re.match(r'^\d+\.?\d*\s*[-–]\s*\d+\.?\d*', line_stripped))


def _is_unit_line(line_stripped):
    """Return unit string if line is purely a unit, else None."""
    m = re.match(r'^([a-zA-Z/%×³µ]+(?:/[a-zA-Z³µ]+)?)\s*$', line_stripped)
    return m.group(1) if m else None


def parse_lab_results_from_text(text):
    """
    Extract lab test name/value/unit tuples from raw OCR/PDF text.

    Handles two common formats:
      A. Vertical (multi-line): each field on its own line
            Haemoglobin (Hb)
            14.90
            13.00 - 17.00
            gm/dL
      B. Inline: value on the same line as the test name
            Glucose : 95 mg/dL
    Strategy: run the vertical pass first (handles most PDFs), then fall back
    to the inline regex pass for values still not found.
    """
    results = []
    seen = set()
    now_iso = datetime.now().isoformat()

    # ------------------------------------------------------------------
    # Step 1 — Fix common PDF/OCR artefacts BEFORE parsing
    #   • Merge digits split by spaces: "1 4 . 9 0" → "14.90"
    #   • Merge digits around a decimal point: "14 . 90" → "14.90"
    # ------------------------------------------------------------------
    clean = text
    # Collapse spaces/tabs between digits (NOT newlines — those separate fields)
    for _ in range(4):
        clean = re.sub(r'(\d)[ \t]+(\d)', r'\1\2', clean)
    clean = re.sub(r'(\d)[ \t]*\.[ \t]*(\d)', r'\1.\2', clean)

    lines_orig = clean.splitlines()
    lines_lower = [ln.strip().lower() for ln in lines_orig]

    # Build a regex that matches any known alias as a whole word (or phrase)
    # Sort longest-first so multi-word phrases ("vitamin b12") match before
    # their substrings ("b12").
    _sorted_aliases = sorted(_KEYWORD_ALIASES.keys(), key=len, reverse=True)

    # ------------------------------------------------------------------
    # Step 2 — Vertical / multi-line pass
    # ------------------------------------------------------------------
    for i, line_l in enumerate(lines_lower):
        for alias in _sorted_aliases:
            norm_name = _KEYWORD_ALIASES[alias]
            if norm_name in seen:
                continue

            # Match alias as a whole word (or phrase) inside the line
            pat = r'\b' + re.escape(alias) + r'\b' if ' ' not in alias else re.escape(alias)
            if not re.search(pat, line_l):
                continue

            # '_skip' aliases mark lines that should not be processed at all
            # (e.g. "Mean Plasma Glucose" so plain "glucose" doesn't grab it).
            # Break out of the alias loop so no other alias re-matches this line.
            if norm_name.startswith('_'):
                break

            # Found the keyword on line i. Scan the next few lines for a value.
            value = None
            unit = ''
            max_v = _MAX_PLAUSIBLE.get(norm_name, 10000)

            for j in range(i + 1, min(i + 7, len(lines_lower))):
                candidate = lines_lower[j]
                if not candidate:
                    continue
                # Descriptor lines (Method / Sample / Reference) often contain
                # test-related keywords — skip them without breaking the scan.
                if re.match(r'^(method|sample|reference)\s*[:.]', candidate):
                    continue
                # Stop if we've run into another test-name line
                if any(re.search(r'\b' + re.escape(a) + r'\b' if ' ' not in a
                                 else re.escape(a), candidate)
                       for a in _sorted_aliases):
                    break
                vt = _is_value_line(candidate)
                if vt is not None:
                    val_candidate, _flag = vt
                    if 0 < val_candidate <= max_v:
                        value = val_candidate
                        # Look ahead past any ref-range / descriptor line for a unit line
                        for k in range(j + 1, min(j + 6, len(lines_lower))):
                            uk = lines_lower[k]
                            if not uk:
                                continue
                            if _is_ref_range(uk):
                                continue
                            if re.match(r'^(method|sample|reference)\s*[:.]', uk):
                                continue
                            # Stop if it looks like descriptive text (long sentence)
                            if len(uk.split()) > 5:
                                break
                            u = _is_unit_line(uk)
                            if u:
                                unit = u
                            break
                    break  # stop scanning regardless (plausibility rejected or ok)

            if value is not None:
                results.append({'test_name': norm_name, 'value': value,
                                 'unit': unit, 'test_date': now_iso})
                seen.add(norm_name)
                break  # stop alias loop for this line

    # ------------------------------------------------------------------
    # Step 3 — Inline regex pass (fallback for horizontal-format reports)
    # ------------------------------------------------------------------
    text_lower = clean.lower()
    NUM = r'(\d+\.?\d*)'
    UNIT_PAT = r'([a-zA-Z/%×³µ]+(?:/[a-zA-Z³µ]+)?)?'
    SEP = r'[\s:=\-]+\s*'

    inline_patterns = [
        # Blood sugar
        ('blood_glucose_fasting', r'(?:blood\s+)?glucose' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('hba1c',                 r'hba?1c' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('hba1c',                 r'glycated\s+h[ae]moglobin' + SEP + NUM + r'\s*' + UNIT_PAT),
        # Lipids
        ('total_cholesterol',     r'(?:total\s+)?cholesterol' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('ldl_cholesterol',       r'ldl(?:[\s\-]+cholesterol)?' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('hdl_cholesterol',       r'hdl(?:[\s\-]+cholesterol)?' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('triglycerides',         r'triglyceride[s]?' + SEP + NUM + r'\s*' + UNIT_PAT),
        # CBC
        ('hemoglobin',            r'h[ae]moglobin' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('wbc_count',             r'(?:wbc|white\s+blood\s+(?:cell|count))' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('wbc_count',             r'\btlc\b' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('rbc_count',             r'(?:rbc|red\s+blood\s+(?:cell|count))' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('platelet_count',        r'platelet[s]?(?:\s+count)?' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('hematocrit',            r'(?:hct|hematocrit|packed\s+cell|pcv)' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('mcv',                   r'\bmcv\b' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('mch',                   r'\bmch\b(?!c)' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('mchc',                  r'\bmchc\b' + SEP + NUM + r'\s*' + UNIT_PAT),
        # Kidney
        ('creatinine',            r'(?:serum\s+)?creatinine' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('urea',                  r'(?:blood\s+urea(?:\s+nitrogen)?|bun|urea)' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('uric_acid',             r'uric\s+acid' + SEP + NUM + r'\s*' + UNIT_PAT),
        # Electrolytes
        ('sodium',                r'sodium' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('potassium',             r'potassium' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('chloride',              r'chloride' + SEP + NUM + r'\s*' + UNIT_PAT),
        # Liver
        ('alt_sgpt',              r'(?:alt|sgpt|alanine(?:\s+amino)?\s*transf\w*)' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('ast_sgot',              r'(?:ast|sgot|aspartate(?:\s+amino)?\s*transf\w*)' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('bilirubin',             r'(?:total\s+)?bilirubin' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('alkaline_phosphatase',  r'(?:alp|alkaline\s+phosphatase)' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('ggt',                   r'\bggt\b' + SEP + NUM + r'\s*' + UNIT_PAT),
        # Thyroid
        ('thyroid_tsh',           r'(?:tsh|thyroid\s+stimul\w*)' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('t3',                    r'\bt3\b' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('t4',                    r'\bt4\b' + SEP + NUM + r'\s*' + UNIT_PAT),
        # Vitamins / Iron
        ('vitamin_d',             r'(?:vitamin\s*d[23]?|25-?oh\s*d)' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('vitamin_b12',           r'(?:vitamin\s*b\s*12?|cobalamin)' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('serum_iron',            r'(?:serum\s+)?iron' + SEP + NUM + r'\s*' + UNIT_PAT),
        ('ferritin',              r'ferritin' + SEP + NUM + r'\s*' + UNIT_PAT),
    ]

    for test_name, pattern in inline_patterns:
        if test_name in seen:
            continue
        m = re.search(pattern, text_lower)
        if m:
            try:
                value = float(m.group(1))
                max_v = _MAX_PLAUSIBLE.get(test_name, 10000)
                if value <= 0 or value > max_v:
                    continue
                unit = (m.group(2) or '').strip()
                results.append({'test_name': test_name, 'value': value,
                                 'unit': unit, 'test_date': now_iso})
                seen.add(test_name)
            except (ValueError, IndexError):
                pass

    return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@lab_bp.route('/lab-analysis')
def lab_analysis():
    return render_template('lab_analysis.html')


@lab_bp.route('/lab-analysis/upload', methods=['POST'])
def upload_lab_report():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        file_type = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        file_content = file.read()

        if file_type == 'pdf':
            try:
                pdf_document = fitz.open(stream=io.BytesIO(file_content), filetype="pdf")
                text = extract_text_from_pdf(pdf_document)
                pdf_document.close()
            except Exception as pdf_error:
                logger.error(f"PDF processing error: {pdf_error}")
                return jsonify({"error": "Error processing PDF file: " + str(pdf_error)}), 500

        elif file_type in ['jpg', 'jpeg', 'png']:
            try:
                image = Image.open(io.BytesIO(file_content))
                text = pytesseract.image_to_string(image)
            except Exception as img_error:
                logger.error(f"Image processing error: {img_error}")
                return jsonify({"error": "Error processing image file: " + str(img_error)}), 500
        else:
            return jsonify({"error": f"Unsupported file format: {file_type}. Please upload PDF, JPG, or PNG."}), 400

        lab_results = parse_lab_results_from_text(text)
        if not lab_results:
            response = jsonify({
                "status": "warning",
                "message": "Could not detect any lab test results. Please try a clearer scan or manual entry.",
                "extracted_text": text[:300] + "..." if len(text) > 300 else text,
            })
            response.headers['Content-Type'] = 'application/json'
            return response, 200

        user_id = session.get('user_id', f'anonymous_{uuid.uuid4().hex[:8]}')
        gender = None
        if 'user_id' in session:
            profile = get_user_profile(user_id)
            gender = profile.get('gender') if profile else None
        analysis = lab_analyzer.analyze_lab_results(user_id, lab_results, gender=gender)

        if 'user_id' in session:
            for result in lab_results:
                save_lab_result(user_id, result)

        response = jsonify({
            "status": "success",
            "message": "Lab report processed successfully",
            "extracted_text_sample": text[:200] + "..." if len(text) > 200 else text,
            "detected_tests": len(lab_results),
            "analysis": analysis,
        })
        response.headers['Content-Type'] = 'application/json'
        return response

    except Exception as e:
        logger.exception(f"Error processing lab report: {e}")
        return jsonify({"error": "Failed to process lab report", "details": str(e)}), 500


@lab_bp.route('/lab-analysis/parse-text', methods=['POST'])
def parse_lab_text():
    """Parse pasted lab report text and return structured analysis."""
    try:
        data = request.get_json() or {}
        text = data.get('text', '').strip()
        if not text:
            return jsonify({"error": "No text provided"}), 400

        lab_results = parse_lab_results_from_text(text)
        if not lab_results:
            response = jsonify({
                "status": "warning",
                "message": "Could not detect any standard lab values. Try the manual entry tab.",
            })
            response.headers['Content-Type'] = 'application/json'
            return response, 200

        user_id = session.get('user_id', f'anonymous_{uuid.uuid4().hex[:8]}')
        gender = None
        if 'user_id' in session:
            profile = get_user_profile(user_id)
            gender = profile.get('gender') if profile else None
        analysis = lab_analyzer.analyze_lab_results(user_id, lab_results, gender=gender)

        if 'user_id' in session:
            for result in lab_results:
                save_lab_result(user_id, result)

        response = jsonify({
            "status": "success",
            "detected_tests": len(lab_results),
            "analysis": analysis,
        })
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.exception(f"Error parsing lab text: {e}")
        return jsonify({"error": "Failed to parse lab text"}), 500


@lab_bp.route('/lab-analysis/manual-entry', methods=['POST'])
@login_required
def manual_lab_entry():
    try:
        user_id = session.get('user_id')
        data = request.get_json()
        if not data or 'lab_results' not in data:
            return jsonify({"error": "Missing lab results data"}), 400

        formatted_results = []
        for result in data['lab_results']:
            if 'test_name' in result and 'value' in result:
                formatted_results.append({
                    'test_name': result['test_name'],
                    'value': float(result['value']),
                    'unit': result.get('unit'),
                    'test_date': result.get('test_date', datetime.now().isoformat()),
                })

        profile = get_user_profile(user_id)
        gender = profile.get('gender') if profile else None
        analysis = lab_analyzer.analyze_lab_results(user_id, formatted_results, gender=gender)
        for result in formatted_results:
            save_lab_result(user_id, result)

        response = jsonify({"status": "success", "analysis": analysis})
        response.headers['Content-Type'] = 'application/json'
        return response

    except Exception as e:
        logger.exception(f"Error entering lab results: {e}")
        return jsonify({"error": "Failed to enter lab results"}), 500


@lab_bp.route('/lab-analysis/recommendations/<disease>', methods=['GET'])
@login_required
def get_lab_recommendations(disease):
    try:
        user_id = session.get('user_id')
        user_profile = get_user_profile(user_id)
        recommendations = lab_analyzer.suggest_lab_tests(disease, user_profile)
        return jsonify({"disease": disease, "recommended_tests": recommendations})
    except Exception as e:
        logger.exception(f"Error getting lab recommendations: {e}")
        return jsonify({"error": "Failed to get recommendations"}), 500


@lab_bp.route('/lab-analysis/history/<user_id>', methods=['GET'])
@login_required
def get_lab_history(user_id):
    try:
        lab_history = get_user_lab_history(
            user_id,
            request.args.get('start_date'),
            request.args.get('end_date'),
            request.args.get('test_name'),
        )
        return jsonify({"user_id": user_id, "lab_history": lab_history})
    except Exception as e:
        logger.exception(f"Error getting lab history: {e}")
        return jsonify({"error": "Failed to retrieve lab history"}), 500


@lab_bp.route('/lab-analysis/trends/<user_id>/<test_name>', methods=['GET'])
@login_required
def get_lab_trends(user_id, test_name):
    try:
        historical_data = get_historical_lab_data(user_id, test_name)
        trends = analyze_lab_trends(historical_data)
        return jsonify({"test_name": test_name, "trend_analysis": trends,
                        "chart_data": prepare_chart_data(historical_data)})
    except Exception as e:
        logger.exception(f"Error analyzing lab trends: {e}")
        return jsonify({"error": "Failed to analyze trends"}), 500


@lab_bp.route('/lab-analysis/reference-ranges', methods=['GET'])
def get_reference_ranges():
    try:
        reference_ranges = {
            name: {
                'normal_range': info.get('normal_range'),
                'unit': info.get('unit'),
                'interpretation_ranges': info.get('interpretation'),
            }
            for name, info in lab_analyzer.lab_tests.items()
        }
        return jsonify(reference_ranges)
    except Exception as e:
        logger.exception(f"Error getting reference ranges: {e}")
        return jsonify({"error": "Failed to get reference ranges"}), 500


@lab_bp.route('/lab-analysis/create-test-reminder', methods=['POST'])
@login_required
def create_lab_test_reminder():
    try:
        data = request.get_json()
        if not data or 'test_name' not in data or 'reminder_date' not in data:
            return jsonify({"error": "Missing required fields"}), 400
        reminder_id = create_test_reminder(
            user_id=session.get('user_id'),
            test_name=data['test_name'],
            reminder_date=data['reminder_date'],
            notes=data.get('notes', ''),
            associated_plan_id=data.get('plan_id'),
        )
        return jsonify({"status": "success", "reminder_id": reminder_id,
                        "message": "Lab test reminder created successfully"})
    except Exception as e:
        logger.exception(f"Error creating lab test reminder: {e}")
        return jsonify({"error": "Failed to create reminder"}), 500


@lab_bp.route('/lab-analysis/compare-with-baseline/<user_id>/<test_name>', methods=['GET'])
@login_required
def compare_with_baseline(user_id, test_name):
    try:
        history = get_historical_lab_data(user_id, test_name)
        if not history:
            return jsonify({"error": "No historical data found"}), 404
        baseline = calculate_baseline(history)
        latest_result = history[-1]
        comparison = analyze_baseline_comparison(baseline, latest_result)
        return jsonify({"test_name": test_name, "baseline_value": baseline,
                        "latest_value": latest_result['value'], **comparison})
    except Exception as e:
        logger.exception(f"Error comparing with baseline: {e}")
        return jsonify({"error": "Failed to compare with baseline"}), 500
