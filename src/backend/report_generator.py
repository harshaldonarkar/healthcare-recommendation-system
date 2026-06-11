# src/backend/report_generator.py
# Generates a PDF health report for a treatment plan using reportlab.

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

_W, _H = A4
_BLUE = colors.HexColor('#0d6efd')
_GREEN = colors.HexColor('#198754')
_LIGHT = colors.HexColor('#f8f9fa')
_MUTED = colors.HexColor('#6c757d')


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle('Title2', parent=s['Title'], fontSize=20, textColor=_BLUE, spaceAfter=4))
    s.add(ParagraphStyle('SectionHead', parent=s['Heading2'], fontSize=12, textColor=_BLUE,
                         spaceBefore=14, spaceAfter=4))
    s.add(ParagraphStyle('SubHead', parent=s['Heading3'], fontSize=10, textColor=_GREEN,
                         spaceBefore=8, spaceAfter=2))
    s.add(ParagraphStyle('Body2', parent=s['Normal'], fontSize=9, leading=14))
    s.add(ParagraphStyle('Muted', parent=s['Normal'], fontSize=8, textColor=_MUTED))
    return s


def _table_style(header_color=_BLUE):
    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [_LIGHT, colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ])


def generate_health_report(plan: dict, medications: list = None,
                            symptom_logs: list = None, username: str = '') -> bytes:
    """
    Build a PDF report and return the raw bytes.

    Args:
        plan: treatment plan dict (disease, steps, recommendations, created_at, …)
        medications: list of medication dicts from MedicationReminder
        symptom_logs: list of {symptom, severity, date} dicts
        username: display name for the report header
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )
    s = _styles()
    story = []

    # ── Header ──────────────────────────────────────────────────────────────
    story.append(Paragraph('Health Advisor', s['Title2']))
    story.append(Paragraph('Personal Health Report', s['Heading2']))
    meta_rows = [
        ['Patient', username or 'N/A'],
        ['Disease / Condition', plan.get('disease', 'N/A')],
        ['Plan Created', _fmt_date(plan.get('created_at', ''))],
        ['Report Generated', datetime.now().strftime('%d %b %Y %H:%M')],
    ]
    story.append(Table(meta_rows, colWidths=[50 * mm, 110 * mm],
                       style=TableStyle([
                           ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                           ('FONTSIZE', (0, 0), (-1, -1), 9),
                           ('TOPPADDING', (0, 0), (-1, -1), 3),
                           ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                       ])))
    story.append(HRFlowable(width='100%', thickness=1, color=_BLUE, spaceAfter=8))

    # ── Recommendations ─────────────────────────────────────────────────────
    recs = plan.get('recommendations', {})
    if recs:
        story.append(Paragraph('Recommendations', s['SectionHead']))

        if recs.get('causes'):
            story.append(Paragraph('Causes', s['SubHead']))
            story.append(Paragraph(str(recs['causes']), s['Body2']))

        if recs.get('diet'):
            story.append(Paragraph('Diet', s['SubHead']))
            story.append(Paragraph(str(recs['diet']), s['Body2']))

        if recs.get('workout'):
            story.append(Paragraph('Workout / Activity', s['SubHead']))
            story.append(Paragraph(str(recs['workout']), s['Body2']))

        if recs.get('precautions'):
            story.append(Paragraph('Precautions', s['SubHead']))
            for p in recs['precautions']:
                story.append(Paragraph(f'• {p}', s['Body2']))

        if recs.get('medicines'):
            story.append(Paragraph('Suggested Medicines', s['SubHead']))
            med_data = [['Medicine']] + [[m] for m in recs['medicines']]
            story.append(Table(med_data, colWidths=[160 * mm], style=_table_style()))

    # ── Treatment Steps ──────────────────────────────────────────────────────
    steps = plan.get('steps', [])
    if steps:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph('Treatment Steps', s['SectionHead']))
        step_data = [['#', 'Step', 'Status']]
        for i, step in enumerate(steps, 1):
            step_data.append([
                str(i),
                step.get('description', step.get('name', '')),
                step.get('status', 'pending').title(),
            ])
        story.append(Table(step_data, colWidths=[10 * mm, 120 * mm, 30 * mm],
                           style=_table_style()))

    # ── Medications ──────────────────────────────────────────────────────────
    if medications:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph('Current Medications', s['SectionHead']))
        med_data = [['Medication', 'Frequency', 'Times/Day']]
        for m in medications:
            med_data.append([
                m.get('name', ''),
                m.get('frequency', ''),
                str(m.get('times_per_day', '')),
            ])
        story.append(Table(med_data, colWidths=[70 * mm, 70 * mm, 20 * mm],
                           style=_table_style(_GREEN)))

    # ── Symptom Log ──────────────────────────────────────────────────────────
    if symptom_logs:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph('Symptom History', s['SectionHead']))
        log_data = [['Date', 'Symptom', 'Severity (1-10)']]
        for log in sorted(symptom_logs, key=lambda x: x.get('date', ''))[-30:]:
            log_data.append([
                str(log.get('date', ''))[:10],
                log.get('symptom', ''),
                str(log.get('severity', '')),
            ])
        story.append(Table(log_data, colWidths=[35 * mm, 90 * mm, 35 * mm],
                           style=_table_style()))

    # ── Disclaimer ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        'This report is generated by Health Advisor for informational purposes only. '
        'It is not a substitute for professional medical advice, diagnosis, or treatment. '
        'Always consult a qualified healthcare professional.',
        s['Muted'],
    ))

    doc.build(story)
    return buf.getvalue()


def _fmt_date(value):
    if not value:
        return 'N/A'
    if hasattr(value, 'strftime'):
        return value.strftime('%d %b %Y')
    try:
        return str(value)[:10]
    except Exception:
        return str(value)
