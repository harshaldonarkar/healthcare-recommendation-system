# src/backend/email_service.py
# Sends email reminders via SMTP. Configure SMTP_* vars in .env.

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
FROM_NAME = os.environ.get('SMTP_FROM_NAME', 'Health Advisor')


def _send(to_email: str, subject: str, html_body: str) -> bool:
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("SMTP not configured — skipping email send")
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f'{FROM_NAME} <{SMTP_USER}>'
        msg['To'] = to_email
        msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def send_medication_reminder(to_email: str, username: str, medications: list) -> bool:
    if not medications:
        return False
    rows = ''.join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #eee'>{m['name']}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #eee'>{m.get('frequency','')}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #eee'>"
        f"{m.get('today_remaining_count', '?')} remaining</td></tr>"
        for m in medications
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <div style="background:#0d6efd;color:#fff;padding:20px;border-radius:8px 8px 0 0">
        <h2 style="margin:0">&#128138; Medication Reminder</h2>
      </div>
      <div style="padding:20px;background:#f8f9fa">
        <p>Hi <strong>{username}</strong>,</p>
        <p>Here are your medications due today ({datetime.now().strftime('%d %b %Y')}):</p>
        <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:6px;overflow:hidden">
          <thead>
            <tr style="background:#e9ecef">
              <th style="padding:10px;text-align:left">Medication</th>
              <th style="padding:10px;text-align:left">Frequency</th>
              <th style="padding:10px;text-align:left">Status</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        <p style="margin-top:20px;color:#6c757d;font-size:0.9em">
          This is an automated reminder from Health Advisor. Do not reply to this email.
        </p>
      </div>
    </div>"""
    return _send(to_email, f'Medication Reminder — {datetime.now().strftime("%d %b")}', html)


def send_appointment_reminder(to_email: str, username: str, appointment: dict) -> bool:
    appt_date = appointment.get('appointment_date', '')
    if hasattr(appt_date, 'strftime'):
        appt_date = appt_date.strftime('%d %b %Y at %I:%M %p')
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <div style="background:#198754;color:#fff;padding:20px;border-radius:8px 8px 0 0">
        <h2 style="margin:0">&#128197; Appointment Reminder</h2>
      </div>
      <div style="padding:20px;background:#f8f9fa">
        <p>Hi <strong>{username}</strong>,</p>
        <p>You have an upcoming appointment:</p>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="padding:6px;font-weight:bold">Provider</td>
              <td style="padding:6px">{appointment.get('provider_name','')}</td></tr>
          <tr><td style="padding:6px;font-weight:bold">Type</td>
              <td style="padding:6px">{appointment.get('appointment_type','')}</td></tr>
          <tr><td style="padding:6px;font-weight:bold">Date & Time</td>
              <td style="padding:6px">{appt_date}</td></tr>
          <tr><td style="padding:6px;font-weight:bold">Location</td>
              <td style="padding:6px">{appointment.get('location','') or 'Not specified'}</td></tr>
        </table>
        <p style="margin-top:20px;color:#6c757d;font-size:0.9em">
          Manage your appointments at Health Advisor.
        </p>
      </div>
    </div>"""
    return _send(to_email, f'Appointment Reminder: {appointment.get("provider_name","")}', html)


def send_welcome_email(to_email: str, username: str) -> bool:
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <div style="background:#0d6efd;color:#fff;padding:20px;border-radius:8px 8px 0 0">
        <h2 style="margin:0">&#10084; Welcome to Health Advisor</h2>
      </div>
      <div style="padding:20px;background:#f8f9fa">
        <p>Hi <strong>{username}</strong>, welcome aboard!</p>
        <p>Here's what you can do with Health Advisor:</p>
        <ul>
          <li>&#129657; Analyze symptoms with AI-powered disease prediction</li>
          <li>&#128138; Track medications and get reminders</li>
          <li>&#128197; Book and manage medical appointments</li>
          <li>&#129514; Upload and analyze lab reports</li>
          <li>&#128200; Track your treatment progress over time</li>
        </ul>
        <p style="color:#6c757d;font-size:0.9em">This is an automated message from Health Advisor.</p>
      </div>
    </div>"""
    return _send(to_email, 'Welcome to Health Advisor!', html)
