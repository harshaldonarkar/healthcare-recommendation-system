"""
src/backend/blueprints/imaging.py

Routes for chest X-ray analysis.

Routes:
    GET  /xray-analysis          → render upload page
    POST /api/xray/analyze       → upload image, return JSON analysis
    POST /api/xray/gradcam       → return Grad-CAM heatmap as PNG base64
"""

import base64
import io
import logging
import os

import numpy as np
from flask import Blueprint, jsonify, render_template, request, session

from core import login_required

logger = logging.getLogger(__name__)

imaging_bp = Blueprint('imaging', __name__)

# Lazy-load analyzer (avoids loading 85 MB model at startup)
_analyzer = None

def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        from xray_analysis import XRayAnalyzer
        _analyzer = XRayAnalyzer()
    return _analyzer


ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
MAX_FILE_BYTES     = 20 * 1024 * 1024   # 20 MB


# ── Pages ──────────────────────────────────────────────────────────────────────

@imaging_bp.route('/xray-analysis')
def xray_analysis_page():
    return render_template('xray_analysis.html')


# ── API ────────────────────────────────────────────────────────────────────────

@imaging_bp.route('/api/xray/analyze', methods=['POST'])
def analyze_xray():
    """Upload a chest X-ray image and return pathology probabilities."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Empty filename'}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': f'Unsupported format "{ext}". Upload JPG or PNG.'}), 400

    image_bytes = f.read()
    if len(image_bytes) > MAX_FILE_BYTES:
        return jsonify({'error': 'File too large (max 20 MB)'}), 400

    try:
        analyzer = _get_analyzer()
        result   = analyzer.analyze(image_bytes)

        if 'error' in result:
            return jsonify({'error': result['error']}), 500

        return jsonify({'status': 'success', **result})

    except Exception as e:
        logger.exception(f"X-ray analysis failed: {e}")
        return jsonify({'error': 'Analysis failed', 'details': str(e)}), 500


@imaging_bp.route('/api/xray/gradcam', methods=['POST'])
def xray_gradcam():
    """
    Return a Grad-CAM heatmap overlaid on the uploaded X-ray as a base64 PNG.

    JSON body (multipart): file + target_pathology
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    target = request.form.get('target_pathology', '')
    if not target:
        return jsonify({'error': 'target_pathology required'}), 400

    f = request.files['file']
    image_bytes = f.read()

    try:
        analyzer  = _get_analyzer()
        cam_array = analyzer.generate_gradcam(image_bytes, target)

        if cam_array is None:
            return jsonify({'error': 'Grad-CAM generation failed or grad-cam not installed'}), 500

        # Convert (H,W) float32 to PNG base64
        from PIL import Image
        cam_uint8 = (cam_array * 255).clip(0, 255).astype(np.uint8)
        img       = Image.fromarray(cam_uint8, mode='L')
        buf       = io.BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()

        return jsonify({
            'status':        'success',
            'target':        target,
            'heatmap_b64':   b64,
        })

    except Exception as e:
        logger.exception(f"Grad-CAM failed: {e}")
        return jsonify({'error': str(e)}), 500
