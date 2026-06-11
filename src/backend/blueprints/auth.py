# src/backend/blueprints/auth.py
import logging
import re
import time
from datetime import datetime

from flask import Blueprint, render_template, request, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

from core import login_required, get_status_color, progress_tracker
import db
from security_log import log_security

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)


def _validate_username(username):
    """Validate username. Returns (is_valid, error_message)."""
    if not username or not isinstance(username, str):
        return False, "Username is required"

    stripped = username.strip()
    if len(stripped) < 3 or len(stripped) > 50:
        return False, "Username must be between 3 and 50 characters"

    if not re.match(r'^[a-zA-Z0-9_]+$', stripped):
        return False, "Username can only contain letters, numbers, and underscores"

    return True, None


def _validate_password(password):
    """Validate password strength. Returns (is_valid, error_message)."""
    if not password or not isinstance(password, str):
        return False, "Password is required"

    if len(password) < 8:
        return False, "Password must be at least 8 characters long"

    has_digit = any(c.isdigit() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_special = any(not c.isalnum() for c in password)

    # Encourage (but don't require) strong passwords
    strength_warnings = []
    if not has_digit:
        strength_warnings.append("password should contain at least one number")
    if not has_upper:
        strength_warnings.append("password should contain at least one uppercase letter")
    if not has_special:
        strength_warnings.append("password should contain at least one special character")

    if strength_warnings:
        logger.info(f"Weak password: {', '.join(strength_warnings)}")

    return True, None

# ---------------------------------------------------------------------------
# Account lockout state (in-memory)
# ---------------------------------------------------------------------------
_login_attempts = {}  # {username: {'count': int, 'first_fail': float, 'locked_until': float}}
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = 900  # 15 minutes in seconds


def _check_lockout(username):
    """Returns (is_locked, seconds_remaining)."""
    rec = _login_attempts.get(username)
    if not rec:
        return False, 0
    if rec.get('locked_until') and time.time() < rec['locked_until']:
        return True, int(rec['locked_until'] - time.time())
    if time.time() - rec.get('first_fail', 0) > LOCKOUT_DURATION:
        _login_attempts.pop(username, None)
    return False, 0


def _record_failure(username):
    rec = _login_attempts.setdefault(username, {'count': 0, 'first_fail': time.time()})
    rec['count'] += 1
    if rec['count'] >= LOCKOUT_THRESHOLD:
        rec['locked_until'] = time.time() + LOCKOUT_DURATION


def _clear_attempts(username):
    _login_attempts.pop(username, None)


# ---------------------------------------------------------------------------
# Fallback in-memory store used when PostgreSQL is unavailable.
# Keys are usernames, values contain password_hash and name.
# ---------------------------------------------------------------------------
_fallback_users = {}


def _authenticate(username, password):
    """Return display name on success, None on failure. Tries DB first."""
    try:
        row = db.get_user_by_username(username)
        if row and check_password_hash(row['password_hash'], password):
            db.update_last_login(username)
            first = row.get('first_name', '') or ''
            last = row.get('last_name', '') or ''
            return (first + ' ' + last).strip() or username
    except Exception as e:
        logger.warning(f"DB auth failed, falling back to in-memory: {e}")

    # Fallback
    user = _fallback_users.get(username)
    if user and check_password_hash(user['password'], password):
        return user['name']
    return None


def _register(username, password, email, name):
    """Register user. Returns None on success, error string on failure."""
    try:
        if db.get_user_by_username(username):
            return 'Username already exists'
        db.create_user(username, generate_password_hash(password), email, name)
        return None
    except Exception as e:
        logger.warning(f"DB register failed, falling back to in-memory: {e}")

    if username in _fallback_users:
        return 'Username already exists'
    _fallback_users[username] = {
        'password': generate_password_hash(password),
        'name': name,
        'email': email,
        'created_at': datetime.now().isoformat(),
    }
    return None


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            return render_template('login.html', error='Username and password are required')

        is_locked, locked_for = _check_lockout(username)
        if is_locked:
            logger.warning(f"Locked-out login attempt for username: {username}")
            log_security('login_locked', username=username)
            return render_template('login.html', locked_for=locked_for)

        display_name = _authenticate(username, password)
        if display_name:
            _clear_attempts(username)
            session['user_id'] = username
            session['user_name'] = display_name
            log_security('login_success', username=username)
            logger.info(f"User {username} logged in successfully")
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('diagnosis.home'))

        _record_failure(username)
        log_security('login_failure', username=username)
        logger.warning(f"Failed login attempt for username: {username}")
        return render_template('login.html', error='Invalid username or password')
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    return redirect(url_for('diagnosis.home'))


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        email = request.form.get('email', '').strip()
        name = request.form.get('name', '').strip()

        # Validate username
        is_valid, error_msg = _validate_username(username)
        if not is_valid:
            return render_template('signup.html', error=error_msg)

        # Validate password
        is_valid, error_msg = _validate_password(password)
        if not is_valid:
            return render_template('signup.html', error=error_msg)

        if not email or '@' not in email:
            return render_template('signup.html', error='Valid email address is required')

        if not name:
            return render_template('signup.html', error='Full name is required')

        error = _register(username, password, email, name)
        if error:
            log_security('signup_failure', username=username)
            return render_template('signup.html', error=error)

        session['user_id'] = username
        session['user_name'] = name
        log_security('signup_success', username=username)
        try:
            from email_service import send_welcome_email
            send_welcome_email(email, username)
        except Exception as e:
            logger.warning(f"Could not send welcome email: {e}")
        return redirect(url_for('auth.my_treatment_plans'))
    return render_template('signup.html')


@auth_bp.route('/my-treatment-plans')
@login_required
def my_treatment_plans():
    user_id = session.get('user_id')
    plans = progress_tracker.get_user_plans(user_id) or []
    formatted_plans = []
    for plan in plans:
        try:
            summary = progress_tracker.get_progress_summary(user_id, plan.get('id'))
            formatted_plans.append({
                'id': plan.get('id', ''),
                'disease': plan.get('disease', 'Unknown Disease'),
                'created_at': plan.get('created_at', 'N/A'),
                'status': summary.get('overall_status', 'active') if summary else 'active',
                'progress': summary.get('progress_percentage', 0) if summary else 0,
                'days_since_start': summary.get('days_since_start', 0) if summary else 0,
                'status_color': get_status_color(summary.get('overall_status', 'active')) if summary else 'primary',
            })
        except Exception:
            continue
    return render_template('my_treatment_plans.html', plans=formatted_plans)
