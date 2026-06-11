# src/backend/db.py
# Database connection and query helpers.
# All direct psycopg2 access lives here — never call psycopg2 from blueprints.

import os
import logging
from contextlib import contextmanager
from datetime import datetime

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_DB_PARAMS = {
    'dbname': os.environ.get('DB_NAME', 'healthcare_system'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', 'password'),
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': os.environ.get('DB_PORT', '5432'),
}


@contextmanager
def get_db():
    """Yield a psycopg2 connection, auto-commit on success, rollback on error."""
    conn = psycopg2.connect(**_DB_PARAMS)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_available():
    """Return True if PostgreSQL is reachable."""
    try:
        with get_db():
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def get_user_by_username(username):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            return cur.fetchone()


def create_user(username, password_hash, email, name):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO users (username, email, password_hash)
                   VALUES (%s, %s, %s) RETURNING user_id""",
                (username, email, password_hash),
            )
            user_id = cur.fetchone()[0]
            # Create a minimal profile with the display name
            first, *rest = name.split(' ', 1)
            last = rest[0] if rest else ''
            cur.execute(
                "INSERT INTO user_profiles (user_id, first_name, last_name) VALUES (%s, %s, %s)",
                (user_id, first, last),
            )
            return user_id


def update_last_login(username):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET last_login = %s WHERE username = %s",
                (datetime.now(), username),
            )


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------
def get_user_profile(username):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT up.*, u.email,
                          array_agg(DISTINCT ua.allergy_name) FILTER (WHERE ua.allergy_name IS NOT NULL) AS allergies,
                          array_agg(DISTINCT uc.condition_name) FILTER (WHERE uc.condition_name IS NOT NULL) AS conditions
                   FROM users u
                   LEFT JOIN user_profiles up ON u.user_id = up.user_id
                   LEFT JOIN user_allergies ua ON u.user_id = ua.user_id
                   LEFT JOIN user_conditions uc ON u.user_id = uc.user_id
                   WHERE u.username = %s
                   GROUP BY up.profile_id, u.email""",
                (username,),
            )
            row = cur.fetchone()
            if not row:
                return {'conditions': [], 'allergies': [], 'age': None, 'gender': None}
            return {
                'conditions': row.get('conditions') or [],
                'allergies': row.get('allergies') or [],
                'age': None,  # calculate from date_of_birth if needed
                'gender': row.get('gender'),
                'email': row.get('email'),
                'first_name': row.get('first_name'),
                'last_name': row.get('last_name'),
            }


# ---------------------------------------------------------------------------
# Treatment plans
# ---------------------------------------------------------------------------
def create_treatment_plan(username, disease_name, recommendations):
    """
    Insert a treatment plan into the DB.
    Returns the new plan_id (integer).
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Resolve user_id
            cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"User '{username}' not found")
            user_id = row[0]

            # Resolve or create disease
            cur.execute("SELECT disease_id FROM diseases WHERE disease_name = %s", (disease_name,))
            row = cur.fetchone()
            if row:
                disease_id = row[0]
            else:
                cur.execute(
                    "INSERT INTO diseases (disease_name) VALUES (%s) RETURNING disease_id",
                    (disease_name,),
                )
                disease_id = cur.fetchone()[0]

            cur.execute(
                """INSERT INTO treatment_plans
                       (user_id, disease_id, start_date, status)
                   VALUES (%s, %s, CURRENT_DATE, 'active')
                   RETURNING plan_id""",
                (user_id, disease_id),
            )
            return cur.fetchone()[0]


def get_treatment_plan(username, plan_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT tp.*, d.disease_name
                   FROM treatment_plans tp
                   JOIN users u ON tp.user_id = u.user_id
                   JOIN diseases d ON tp.disease_id = d.disease_id
                   WHERE u.username = %s AND tp.plan_id = %s""",
                (username, plan_id),
            )
            return cur.fetchone()


def get_user_plans(username):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT tp.plan_id AS id, d.disease_name AS disease,
                          tp.created_at, tp.status
                   FROM treatment_plans tp
                   JOIN users u ON tp.user_id = u.user_id
                   JOIN diseases d ON tp.disease_id = d.disease_id
                   WHERE u.username = %s
                   ORDER BY tp.created_at DESC""",
                (username,),
            )
            return [dict(r) for r in cur.fetchall()]


def log_symptom(username, plan_id, symptom, severity, notes=''):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
            user_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO symptom_logs (plan_id, user_id, symptom, severity, notes)
                   VALUES (%s, %s, %s, %s, %s)""",
                (plan_id, user_id, symptom, severity, notes),
            )


def add_plan_note(username, plan_id, content):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
            user_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO plan_notes (plan_id, user_id, note_text) VALUES (%s, %s, %s)",
                (plan_id, user_id, content),
            )


# ---------------------------------------------------------------------------
# Lab results
# ---------------------------------------------------------------------------
def save_lab_result(username, test_name, value, unit, test_date=None):
    """
    Save a lab result.  test_id is resolved (or created) by test_name.
    Falls back silently if the DB is unavailable.
    """
    if test_date is None:
        test_date = datetime.now()

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
                if not row:
                    return
                user_id = row[0]

                # Resolve or create lab test entry
                cur.execute(
                    """SELECT lt.test_id FROM lab_tests lt
                       JOIN lab_test_categories lc ON lt.category_id = lc.category_id
                       WHERE LOWER(lt.test_name) = LOWER(%s)""",
                    (test_name,),
                )
                row = cur.fetchone()
                if row:
                    test_id = row[0]
                else:
                    # Create a default category if needed
                    cur.execute(
                        "INSERT INTO lab_test_categories (category_name) VALUES ('General') ON CONFLICT DO NOTHING"
                    )
                    cur.execute("SELECT category_id FROM lab_test_categories WHERE category_name = 'General'")
                    cat_id = cur.fetchone()[0]
                    cur.execute(
                        """INSERT INTO lab_tests (test_name, category_id, unit)
                           VALUES (%s, %s, %s) RETURNING test_id""",
                        (test_name, cat_id, unit or ''),
                    )
                    test_id = cur.fetchone()[0]

                cur.execute(
                    """INSERT INTO user_lab_results (user_id, test_id, result_value, test_date)
                       VALUES (%s, %s, %s, %s)""",
                    (user_id, test_id, float(value), test_date),
                )
    except Exception as e:
        logger.warning(f"Could not save lab result to DB (falling back): {e}")


def get_lab_history(username, start_date=None, end_date=None, test_name=None):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = """
                    SELECT lt.test_name, ulr.result_value AS value,
                           lt.unit, ulr.test_date
                    FROM user_lab_results ulr
                    JOIN lab_tests lt ON ulr.test_id = lt.test_id
                    JOIN users u ON ulr.user_id = u.user_id
                    WHERE u.username = %s
                """
                params = [username]
                if test_name:
                    query += " AND LOWER(lt.test_name) = LOWER(%s)"
                    params.append(test_name)
                if start_date:
                    query += " AND ulr.test_date >= %s"
                    params.append(start_date)
                if end_date:
                    query += " AND ulr.test_date <= %s"
                    params.append(end_date)
                query += " ORDER BY ulr.test_date ASC"
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"Could not fetch lab history from DB: {e}")
        return []


# ---------------------------------------------------------------------------
# Treatment steps
# ---------------------------------------------------------------------------
def create_treatment_steps(plan_id, steps):
    """Insert treatment steps for a plan. Returns list of dicts with 'id' added."""
    result = []
    with get_db() as conn:
        with conn.cursor() as cur:
            for step in steps:
                cur.execute(
                    """INSERT INTO treatment_steps
                           (plan_id, step_type, name, description, frequency, status)
                       VALUES (%s, %s, %s, %s, %s, 'not_started')
                       RETURNING step_id""",
                    (plan_id, step.get('type', 'general'), step.get('name', ''),
                     step.get('description', ''), step.get('frequency', '')),
                )
                step_id = cur.fetchone()[0]
                result.append({**step, 'id': str(step_id), 'status': 'not_started', 'completions': [], 'notes': []})
    return result


def get_treatment_steps(plan_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM treatment_steps WHERE plan_id = %s ORDER BY step_id",
                (plan_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def update_step_status(plan_id, step_id, new_status):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE treatment_steps SET status = %s WHERE step_id = %s AND plan_id = %s",
                (new_status, step_id, plan_id),
            )
            return cur.rowcount > 0


def get_plan_symptom_logs(plan_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM symptom_logs WHERE plan_id = %s ORDER BY log_date",
                (plan_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_plan_notes(plan_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM plan_notes WHERE plan_id = %s ORDER BY created_at",
                (plan_id,),
            )
            return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Medication schedules
# ---------------------------------------------------------------------------
def _resolve_user_id(cur, username):
    cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"User '{username}' not found")
    return row[0]


def create_medication_schedule(username, plan_id, medications):
    with get_db() as conn:
        with conn.cursor() as cur:
            user_id = _resolve_user_id(cur, username)
            cur.execute(
                """INSERT INTO medication_schedules (user_id, plan_id)
                   VALUES (%s, %s) RETURNING schedule_id""",
                (user_id, plan_id),
            )
            schedule_id = str(cur.fetchone()[0])
            for med in medications:
                cur.execute(
                    """INSERT INTO scheduled_medications
                           (schedule_id, name, description, frequency, times_per_day, schedule_times)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (schedule_id, med.get('name', ''), med.get('description', ''),
                     med.get('frequency', 'Once daily'), med.get('times_per_day', 1),
                     med.get('schedule', ['08:00'])),
                )
    return schedule_id


def _build_schedule_dict(conn, schedule_id, plan_id=None):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM scheduled_medications WHERE schedule_id = %s", (schedule_id,))
        meds = []
        for row in cur.fetchall():
            med = dict(row)
            med['id'] = str(med.pop('med_id'))
            med['schedule_id'] = str(med['schedule_id'])
            cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur2.execute("SELECT * FROM medication_taken_logs WHERE med_id = %s", (med['id'],))
            med['taken_logs'] = [{'id': str(r['log_id']), 'timestamp': r['taken_at'].isoformat()} for r in cur2.fetchall()]
            cur2.close()
            meds.append(med)
        return {'id': str(schedule_id), 'plan_id': plan_id, 'medications': meds}


def get_medication_schedule(username, schedule_id):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                user_id = _resolve_user_id(cur, username)
                cur.execute(
                    "SELECT plan_id FROM medication_schedules WHERE schedule_id = %s AND user_id = %s",
                    (schedule_id, user_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                plan_id = row[0]
            return _build_schedule_dict(conn, schedule_id, plan_id)
    except Exception as e:
        logger.warning(f"get_medication_schedule: {e}")
        return None


def get_user_schedules(username):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                user_id = _resolve_user_id(cur, username)
                cur.execute(
                    "SELECT schedule_id, plan_id FROM medication_schedules WHERE user_id = %s",
                    (user_id,),
                )
                rows = cur.fetchall()
            return [_build_schedule_dict(conn, str(r[0]), r[1]) for r in rows]
    except Exception as e:
        logger.warning(f"get_user_schedules: {e}")
        return []


def update_medication(username, schedule_id, med_id, updates):
    allowed = {'name', 'description', 'frequency', 'times_per_day', 'schedule_times',
                'end_date', 'reminders_enabled'}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False
    set_clause = ', '.join(f"{k} = %s" for k in fields)
    with get_db() as conn:
        with conn.cursor() as cur:
            user_id = _resolve_user_id(cur, username)
            cur.execute(
                f"""UPDATE scheduled_medications sm
                    SET {set_clause}
                    FROM medication_schedules ms
                    WHERE sm.med_id = %s AND sm.schedule_id = %s
                      AND ms.schedule_id = sm.schedule_id AND ms.user_id = %s""",
                (*fields.values(), med_id, schedule_id, user_id),
            )
            return cur.rowcount > 0


def log_medication_taken(username, schedule_id, med_id, timestamp=None):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                _resolve_user_id(cur, username)
                if timestamp:
                    cur.execute(
                        "INSERT INTO medication_taken_logs (med_id, taken_at) VALUES (%s, %s)",
                        (med_id, timestamp),
                    )
                else:
                    cur.execute(
                        "INSERT INTO medication_taken_logs (med_id) VALUES (%s)",
                        (med_id,),
                    )
        return True
    except Exception as e:
        logger.warning(f"log_medication_taken: {e}")
        return False


def get_today_medications(username):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                user_id = _resolve_user_id(cur, username)
                cur.execute(
                    """SELECT sm.*, ms.plan_id,
                              (SELECT COUNT(*) FROM medication_taken_logs mtl
                               WHERE mtl.med_id = sm.med_id
                                 AND mtl.taken_at::date = CURRENT_DATE) AS today_taken_count
                       FROM scheduled_medications sm
                       JOIN medication_schedules ms ON sm.schedule_id = ms.schedule_id
                       WHERE ms.user_id = %s
                         AND sm.start_date::date <= CURRENT_DATE
                         AND (sm.end_date IS NULL OR sm.end_date::date >= CURRENT_DATE)""",
                    (user_id,),
                )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    med = dict(row)
                    med['id'] = str(med.pop('med_id'))
                    med['today_taken_count'] = int(med.get('today_taken_count', 0))
                    med['today_remaining_count'] = med['times_per_day'] - med['today_taken_count']
                    result.append(med)
                return result
    except Exception as e:
        logger.warning(f"get_today_medications: {e}")
        return []


def get_medication_adherence(username, days=7):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                user_id = _resolve_user_id(cur, username)
                cur.execute(
                    """SELECT sm.name, sm.times_per_day,
                              COUNT(mtl.log_id) AS taken_count,
                              %s * sm.times_per_day AS expected_count
                       FROM scheduled_medications sm
                       JOIN medication_schedules ms ON sm.schedule_id = ms.schedule_id
                       LEFT JOIN medication_taken_logs mtl
                           ON mtl.med_id = sm.med_id
                          AND mtl.taken_at >= NOW() - INTERVAL '%s days'
                       WHERE ms.user_id = %s
                       GROUP BY sm.med_id, sm.name, sm.times_per_day""",
                    (days, days, user_id),
                )
                rows = cur.fetchall()
                total_expected = sum(r['expected_count'] for r in rows)
                total_taken = sum(r['taken_count'] for r in rows)
                overall = (total_taken / total_expected * 100) if total_expected > 0 else 0
                return {
                    'overall_adherence': round(overall, 1),
                    'total_doses': total_expected,
                    'taken_doses': total_taken,
                    'missed_doses': total_expected - total_taken,
                    'days_analyzed': days,
                    'by_medication': {r['name']: {
                        'total': r['expected_count'],
                        'taken': r['taken_count'],
                        'percentage': round(r['taken_count'] / r['expected_count'] * 100, 1) if r['expected_count'] else 0,
                    } for r in rows},
                }
    except Exception as e:
        logger.warning(f"get_medication_adherence: {e}")
        return {'overall_adherence': 0, 'total_doses': 0, 'taken_doses': 0, 'missed_doses': 0, 'days_analyzed': days, 'by_medication': {}}


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
def create_appointment(username, provider_name, appointment_type, appointment_date,
                       location='', notes='', plan_id=None):
    with get_db() as conn:
        with conn.cursor() as cur:
            user_id = _resolve_user_id(cur, username)
            cur.execute(
                """INSERT INTO medical_appointments
                       (user_id, plan_id, provider_name, appointment_type,
                        appointment_date, location, notes, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'scheduled')
                   RETURNING appointment_id""",
                (user_id, plan_id, provider_name, appointment_type,
                 appointment_date, location, notes),
            )
            return cur.fetchone()[0]


def get_user_appointments(username, status=None):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            user_id = _resolve_user_id(cur, username)
            query = """SELECT * FROM medical_appointments
                       WHERE user_id = %s"""
            params = [user_id]
            if status:
                query += " AND status = %s"
                params.append(status)
            query += " ORDER BY appointment_date ASC"
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]


def get_appointment(username, appointment_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            user_id = _resolve_user_id(cur, username)
            cur.execute(
                "SELECT * FROM medical_appointments WHERE appointment_id = %s AND user_id = %s",
                (appointment_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def update_appointment_status(username, appointment_id, status):
    with get_db() as conn:
        with conn.cursor() as cur:
            user_id = _resolve_user_id(cur, username)
            cur.execute(
                """UPDATE medical_appointments SET status = %s
                   WHERE appointment_id = %s AND user_id = %s""",
                (status, appointment_id, user_id),
            )
            return cur.rowcount > 0


def delete_appointment(username, appointment_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            user_id = _resolve_user_id(cur, username)
            cur.execute(
                "DELETE FROM medical_appointments WHERE appointment_id = %s AND user_id = %s",
                (appointment_id, user_id),
            )


# ---------------------------------------------------------------------------
# Doctor / Hospital Reviews
# ---------------------------------------------------------------------------

def add_doctor_review(username, hospital_id, rating, review_text):
    """Insert or update a user's review for a hospital. Returns the review id."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            user_id = _resolve_user_id(cur, username)
            cur.execute(
                """INSERT INTO doctor_reviews (user_id, hospital_id, rating, review_text)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (user_id, hospital_id) DO UPDATE
                     SET rating = EXCLUDED.rating,
                         review_text = EXCLUDED.review_text,
                         created_at = NOW()
                   RETURNING review_id""",
                (user_id, hospital_id, rating, review_text),
            )
            return cur.fetchone()['review_id']


def get_hospital_reviews(hospital_id):
    """Return all reviews for a hospital, newest first."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT r.review_id, u.username, r.rating, r.review_text, r.created_at
                   FROM doctor_reviews r
                   JOIN users u ON u.user_id = r.user_id
                   WHERE r.hospital_id = %s
                   ORDER BY r.created_at DESC""",
                (hospital_id,),
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]


def get_hospital_avg_rating(hospital_id):
    """Return {'avg': float, 'count': int} or None if no reviews."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT AVG(rating)::numeric(3,1), COUNT(*) FROM doctor_reviews WHERE hospital_id = %s",
                (hospital_id,),
            )
            avg, count = cur.fetchone()
            if count == 0:
                return None
            return {'avg': float(avg), 'count': int(count)}
            return cur.rowcount > 0
