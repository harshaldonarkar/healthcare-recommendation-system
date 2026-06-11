# progress_tracker.py — DB-backed with in-memory fallback

import datetime
import uuid
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def _build_steps_from_recommendations(recommendations: Dict[str, Any]) -> List[Dict]:
    steps = []
    for medicine in recommendations.get('medicines', []):
        steps.append({'type': 'medication', 'name': medicine,
                      'description': f'Take {medicine} as prescribed',
                      'frequency': 'As directed by healthcare provider'})
    if recommendations.get('diet'):
        steps.append({'type': 'diet', 'name': 'Dietary Changes',
                      'description': recommendations['diet'], 'frequency': 'Daily'})
    if recommendations.get('workout'):
        steps.append({'type': 'exercise', 'name': 'Exercise Routine',
                      'description': recommendations['workout'], 'frequency': '3-4 times per week'})
    for i, p in enumerate(recommendations.get('precautions', [])):
        if p:
            steps.append({'type': 'precaution', 'name': f'Precaution {i+1}',
                          'description': p, 'frequency': 'Ongoing'})
    return steps


class ProgressTracker:
    """Track patient treatment progress — PostgreSQL-backed with in-memory fallback."""

    def __init__(self, db_file=None):
        self._fallback: Dict = {}  # used only when DB is unavailable
        try:
            import db as _db
            self._db = _db
            self._use_db = True
        except Exception:
            self._db = None
            self._use_db = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def create_treatment_plan(self, user_id: str, disease: str,
                              recommendations: Dict[str, Any]) -> str:
        steps = _build_steps_from_recommendations(recommendations)
        if self._use_db:
            try:
                plan_id = self._db.create_treatment_plan(user_id, disease, recommendations)
                self._db.create_treatment_steps(plan_id, steps)
                return str(plan_id)
            except Exception as e:
                logger.warning(f"DB unavailable for create_treatment_plan: {e}")
        # fallback
        plan_id = str(uuid.uuid4())
        plan = {
            'id': plan_id, 'user_id': user_id, 'disease': disease,
            'created_at': datetime.datetime.now().isoformat(),
            'last_updated': datetime.datetime.now().isoformat(),
            'overall_status': 'active',
            'treatment_steps': [{'id': str(uuid.uuid4()), 'status': 'not_started',
                                  'completions': [], 'notes': [], **s} for s in steps],
            'symptom_logs': [], 'notes': [],
        }
        self._fallback.setdefault(user_id, {})[plan_id] = plan
        return plan_id

    def get_treatment_plan(self, user_id: str, plan_id: str) -> Optional[Dict]:
        if self._use_db:
            try:
                row = self._db.get_treatment_plan(user_id, plan_id)
                if row is None:
                    return None
                steps = self._db.get_treatment_steps(plan_id)
                logs = self._db.get_plan_symptom_logs(plan_id)
                notes = self._db.get_plan_notes(plan_id)
                return {
                    'id': str(row.get('plan_id', plan_id)),
                    'user_id': user_id,
                    'disease': row.get('disease_name', ''),
                    'created_at': row.get('created_at', datetime.datetime.now()).isoformat()
                        if hasattr(row.get('created_at'), 'isoformat') else str(row.get('created_at', '')),
                    'last_updated': datetime.datetime.now().isoformat(),
                    'overall_status': row.get('status', 'active'),
                    'treatment_steps': [
                        {'id': str(s.get('step_id', '')), 'type': s.get('step_type', ''),
                         'name': s.get('name', ''), 'description': s.get('description', ''),
                         'frequency': s.get('frequency', ''), 'status': s.get('status', 'not_started'),
                         'completions': [], 'notes': []}
                        for s in steps
                    ],
                    'symptom_logs': [
                        {'symptom': l.get('symptom', ''), 'severity': l.get('severity'),
                         'date': l.get('log_date', datetime.datetime.now()).isoformat()
                             if hasattr(l.get('log_date'), 'isoformat') else str(l.get('log_date', '')),
                         'notes': l.get('notes', '')}
                        for l in logs
                    ],
                    'notes': [
                        {'content': n.get('note_text', ''),
                         'date': n.get('created_at', datetime.datetime.now()).isoformat()
                             if hasattr(n.get('created_at'), 'isoformat') else str(n.get('created_at', ''))}
                        for n in notes
                    ],
                }
            except Exception as e:
                logger.warning(f"DB unavailable for get_treatment_plan: {e}")
        return self._fallback.get(user_id, {}).get(plan_id)

    def get_user_plans(self, user_id: str) -> List[Dict]:
        if self._use_db:
            try:
                return self._db.get_user_plans(user_id)
            except Exception as e:
                logger.warning(f"DB unavailable for get_user_plans: {e}")
        return list(self._fallback.get(user_id, {}).values())

    def get_progress_summary(self, user_id: str, plan_id: str) -> Optional[Dict]:
        plan = self.get_treatment_plan(user_id, plan_id)
        if not plan:
            return None
        steps = plan.get('treatment_steps', [])
        completed = sum(1 for s in steps if s.get('status') == 'completed')
        in_progress = sum(1 for s in steps if s.get('status') == 'in_progress')
        total = len(steps)
        pct = (completed / total * 100) if total > 0 else 0
        created_str = plan.get('created_at', datetime.datetime.now().isoformat())
        try:
            created_at = datetime.datetime.fromisoformat(created_str)
        except Exception:
            created_at = datetime.datetime.now()
        days = (datetime.datetime.now() - created_at).days
        logs = plan.get('symptom_logs', [])
        improvement = None
        if len(logs) >= 2:
            sorted_logs = sorted(logs, key=lambda x: x.get('date', ''))
            if sorted_logs[0].get('severity') and sorted_logs[-1].get('severity'):
                improvement = sorted_logs[0]['severity'] - sorted_logs[-1]['severity']
        return {
            'progress_percentage': round(pct, 1),
            'completed_steps': completed,
            'in_progress_steps': in_progress,
            'not_started_steps': total - completed - in_progress,
            'days_since_start': days,
            'overall_status': plan.get('overall_status', 'active'),
            'symptom_improvement': improvement,
            'total_steps': total,
        }

    def update_step_status(self, user_id: str, plan_id: str, step_id: str, new_status: str) -> bool:
        if self._use_db:
            try:
                return self._db.update_step_status(plan_id, step_id, new_status)
            except Exception as e:
                logger.warning(f"DB unavailable for update_step_status: {e}")
        plan = self._fallback.get(user_id, {}).get(plan_id)
        if not plan:
            return False
        for step in plan.get('treatment_steps', []):
            if step.get('id') == step_id:
                step['status'] = new_status
                plan['last_updated'] = datetime.datetime.now().isoformat()
                return True
        return False

    def log_symptom(self, user_id: str, plan_id: str, symptom: str,
                    severity: int, notes: str = '') -> bool:
        if self._use_db:
            try:
                self._db.log_symptom(user_id, plan_id, symptom, severity, notes)
                return True
            except Exception as e:
                logger.warning(f"DB unavailable for log_symptom: {e}")
        plan = self._fallback.get(user_id, {}).get(plan_id)
        if not plan:
            return False
        plan['symptom_logs'].append({'symptom': symptom, 'severity': severity,
                                     'date': datetime.datetime.now().isoformat(), 'notes': notes})
        plan['last_updated'] = datetime.datetime.now().isoformat()
        return True

    def add_note(self, user_id: str, plan_id: str, content: str) -> bool:
        if self._use_db:
            try:
                self._db.add_plan_note(user_id, plan_id, content)
                return True
            except Exception as e:
                logger.warning(f"DB unavailable for add_note: {e}")
        plan = self._fallback.get(user_id, {}).get(plan_id)
        if not plan:
            return False
        plan['notes'].append({'content': content, 'date': datetime.datetime.now().isoformat()})
        plan['last_updated'] = datetime.datetime.now().isoformat()
        return True

    def debug_info(self):
        return {
            'backend': 'postgresql' if self._use_db else 'in-memory',
            'fallback_user_count': len(self._fallback),
        }
