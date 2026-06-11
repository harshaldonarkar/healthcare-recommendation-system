# src/backend/blueprints/appointments.py

import logging
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash

from core import login_required
import db

logger = logging.getLogger(__name__)

appointments_bp = Blueprint('appointments', __name__)

APPOINTMENT_TYPES = [
    'General Checkup', 'Follow-up', 'Specialist Consultation',
    'Lab Test', 'Imaging / Scan', 'Vaccination', 'Dental', 'Other',
]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@appointments_bp.route('/appointments')
@login_required
def appointments_list():
    username = session.get('user_id')
    try:
        appointments = db.get_user_appointments(username)
    except Exception as e:
        logger.warning(f"Could not load appointments: {e}")
        appointments = []
    now = datetime.now()
    upcoming = [a for a in appointments if a.get('status') == 'scheduled'
                and a.get('appointment_date') and a['appointment_date'] >= now]
    past = [a for a in appointments if a not in upcoming]
    return render_template('appointments.html',
                           upcoming=upcoming, past=past,
                           appointment_types=APPOINTMENT_TYPES)


@appointments_bp.route('/appointments/new', methods=['GET', 'POST'])
@login_required
def new_appointment():
    username = session.get('user_id')
    if request.method == 'POST':
        provider = request.form.get('provider_name', '').strip()
        appt_type = request.form.get('appointment_type', 'General Checkup')
        date_str = request.form.get('appointment_date', '')
        location = request.form.get('location', '').strip()
        notes = request.form.get('notes', '').strip()
        plan_id = request.form.get('plan_id') or None

        if not provider or not date_str:
            flash('Provider name and date are required.', 'danger')
            return redirect(url_for('appointments.new_appointment'))

        try:
            appt_date = datetime.fromisoformat(date_str)
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('appointments.new_appointment'))

        try:
            db.create_appointment(username, provider, appt_type, appt_date,
                                  location, notes, plan_id)
            flash('Appointment booked successfully!', 'success')
        except Exception as e:
            logger.error(f"Error creating appointment: {e}")
            flash('Could not save appointment. Database may be unavailable.', 'warning')

        return redirect(url_for('appointments.appointments_list'))

    return render_template('new_appointment.html', appointment_types=APPOINTMENT_TYPES)


@appointments_bp.route('/appointments/<int:appointment_id>/cancel', methods=['POST'])
@login_required
def cancel_appointment(appointment_id):
    username = session.get('user_id')
    try:
        db.update_appointment_status(username, appointment_id, 'cancelled')
        flash('Appointment cancelled.', 'info')
    except Exception as e:
        logger.error(f"Error cancelling appointment: {e}")
        flash('Could not cancel appointment.', 'danger')
    return redirect(url_for('appointments.appointments_list'))


@appointments_bp.route('/appointments/<int:appointment_id>/complete', methods=['POST'])
@login_required
def complete_appointment(appointment_id):
    username = session.get('user_id')
    try:
        db.update_appointment_status(username, appointment_id, 'completed')
        flash('Appointment marked as completed.', 'success')
    except Exception as e:
        logger.error(f"Error completing appointment: {e}")
        flash('Could not update appointment.', 'danger')
    return redirect(url_for('appointments.appointments_list'))


@appointments_bp.route('/appointments/<int:appointment_id>/delete', methods=['POST'])
@login_required
def delete_appointment(appointment_id):
    username = session.get('user_id')
    try:
        db.delete_appointment(username, appointment_id)
        flash('Appointment deleted.', 'info')
    except Exception as e:
        logger.error(f"Error deleting appointment: {e}")
        flash('Could not delete appointment.', 'danger')
    return redirect(url_for('appointments.appointments_list'))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@appointments_bp.route('/api/appointments', methods=['GET'])
@login_required
def api_list():
    username = session.get('user_id')
    try:
        appts = db.get_user_appointments(username)
        for a in appts:
            if a.get('appointment_date'):
                a['appointment_date'] = a['appointment_date'].isoformat()
            if a.get('created_at'):
                a['created_at'] = a['created_at'].isoformat()
        return jsonify(appts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@appointments_bp.route('/api/appointments', methods=['POST'])
@login_required
def api_create():
    username = session.get('user_id')
    data = request.get_json() or {}
    try:
        appt_date = datetime.fromisoformat(data['appointment_date'])
        appt_id = db.create_appointment(
            username,
            data.get('provider_name', ''),
            data.get('appointment_type', 'General Checkup'),
            appt_date,
            data.get('location', ''),
            data.get('notes', ''),
            data.get('plan_id'),
        )
        return jsonify({'appointment_id': appt_id}), 201
    except KeyError:
        return jsonify({'error': 'appointment_date and provider_name are required'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
