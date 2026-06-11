# src/backend/app.py
# Application factory — registers all blueprints.
# Run from this directory: python app.py

import os
import secrets
import logging
from datetime import timedelta
from flask import Flask, jsonify, request, render_template, session
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Must import TEMPLATES_DIR / STATIC_DIR before creating app
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend/templates')
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend/static')

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(24))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=60)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
CORS(app)


def _generate_csrf():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

logger = logging.getLogger(__name__)


@app.before_request
def log_request():
    """Log request method and path for debug."""
    logger.info(f"{request.method} {request.path}")


@app.before_request
def _check_csrf():
    if app.config.get('TESTING'):
        return
    if request.method in ('POST', 'PUT', 'DELETE') and not request.path.startswith('/api/'):
        token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
        if not token or token != session.get('csrf_token'):
            try:
                from security_log import log_security
                log_security('csrf_rejected', path=request.path)
            except Exception:
                pass
            return render_template('errors/403.html'), 403


@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    # Add security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    if request.path.startswith('/api/'):
        return jsonify({"error": "Resource not found"}), 404
    return render_template('errors/404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {error}", exc_info=True)
    if request.path.startswith('/api/'):
        return jsonify({"error": "Internal server error"}), 500
    return render_template('errors/500.html'), 500


@app.errorhandler(403)
def forbidden(error):
    """Handle 403 errors."""
    if request.path.startswith('/api/'):
        return jsonify({"error": "Forbidden"}), 403
    return render_template('errors/403.html'), 403


# ---------------------------------------------------------------------------
# Register blueprints
# ---------------------------------------------------------------------------
from blueprints.auth import auth_bp
from blueprints.diagnosis import diagnosis_bp
from blueprints.treatment import treatment_bp
from blueprints.lab import lab_bp
from blueprints.doctors import doctors_bp
from blueprints.medication import medication_bp
from blueprints.appointments import appointments_bp
from blueprints.imaging import imaging_bp

app.register_blueprint(auth_bp)
app.register_blueprint(diagnosis_bp)
app.register_blueprint(treatment_bp)
app.register_blueprint(lab_bp)
app.register_blueprint(doctors_bp)
app.register_blueprint(medication_bp)
app.register_blueprint(appointments_bp)
app.register_blueprint(imaging_bp)

app.jinja_env.globals['csrf_token'] = _generate_csrf


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    # Werkzeug debugger allows code execution — never enable it by default
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes')
    app.run(debug=debug, host='127.0.0.1', port=port)
