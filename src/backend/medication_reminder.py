# src/backend/medication_reminder.py — DB-backed with in-memory fallback

import datetime
import uuid
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class MedicationReminder:
    """Medication reminder system — PostgreSQL-backed with in-memory fallback."""

    def __init__(self, data_file=None):
        self._fallback: Dict = {}  # keyed by user_id → {schedule_id → schedule}
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

    def create_medication_schedule(self, user_id: str, plan_id: str,
                                   medications: List[Dict[str, Any]]) -> str:
        enriched = []
        for med in medications:
            tpd = self._parse_frequency(med.get('frequency', 'Once daily'))
            enriched.append({**med, 'times_per_day': tpd,
                             'schedule': self._generate_default_times(tpd)})
        if self._use_db:
            try:
                return self._db.create_medication_schedule(user_id, plan_id, enriched)
            except Exception as e:
                logger.warning(f"DB unavailable for create_medication_schedule: {e}")
        schedule_id = str(uuid.uuid4())
        schedule = {
            'id': schedule_id, 'user_id': user_id, 'plan_id': plan_id,
            'created_at': datetime.datetime.now().isoformat(),
            'updated_at': datetime.datetime.now().isoformat(),
            'medications': [
                {'id': str(uuid.uuid4()), 'taken_logs': [],
                 'start_date': datetime.datetime.now().isoformat(), 'end_date': None,
                 'reminders_enabled': True, **m}
                for m in enriched
            ],
        }
        self._fallback.setdefault(user_id, {})[schedule_id] = schedule
        return schedule_id

    def get_medication_schedule(self, user_id: str, schedule_id: str) -> Optional[Dict]:
        if self._use_db:
            try:
                return self._db.get_medication_schedule(user_id, schedule_id)
            except Exception as e:
                logger.warning(f"DB unavailable for get_medication_schedule: {e}")
        return self._fallback.get(user_id, {}).get(schedule_id)

    def get_user_schedules(self, user_id: str) -> List[Dict]:
        if self._use_db:
            try:
                return self._db.get_user_schedules(user_id)
            except Exception as e:
                logger.warning(f"DB unavailable for get_user_schedules: {e}")
        return list(self._fallback.get(user_id, {}).values())

    def update_medication_schedule(self, user_id: str, schedule_id: str,
                                   medication_id: str, updates: Dict[str, Any]) -> bool:
        if self._use_db:
            try:
                return self._db.update_medication(user_id, schedule_id, medication_id, updates)
            except Exception as e:
                logger.warning(f"DB unavailable for update_medication_schedule: {e}")
        schedule = self._fallback.get(user_id, {}).get(schedule_id)
        if not schedule:
            return False
        for med in schedule['medications']:
            if med['id'] == medication_id:
                for k, v in updates.items():
                    if k in med:
                        med[k] = v
                schedule['updated_at'] = datetime.datetime.now().isoformat()
                return True
        return False

    def log_medication_taken(self, user_id: str, schedule_id: str,
                             medication_id: str, timestamp: Optional[str] = None) -> bool:
        if timestamp is None:
            timestamp = datetime.datetime.now().isoformat()
        if self._use_db:
            try:
                return self._db.log_medication_taken(user_id, schedule_id, medication_id, timestamp)
            except Exception as e:
                logger.warning(f"DB unavailable for log_medication_taken: {e}")
        schedule = self._fallback.get(user_id, {}).get(schedule_id)
        if not schedule:
            return False
        for med in schedule['medications']:
            if med['id'] == medication_id:
                med['taken_logs'].append({'id': str(uuid.uuid4()), 'timestamp': timestamp})
                schedule['updated_at'] = datetime.datetime.now().isoformat()
                return True
        return False

    def get_today_medication_schedule(self, user_id: str) -> List[Dict]:
        if self._use_db:
            try:
                return self._db.get_today_medications(user_id)
            except Exception as e:
                logger.warning(f"DB unavailable for get_today_medication_schedule: {e}")
        today = datetime.datetime.now().date()
        today_meds = []
        for schedule in self.get_user_schedules(user_id):
            for med in schedule.get('medications', []):
                start = datetime.datetime.fromisoformat(med['start_date']).date()
                end = None
                if med.get('end_date'):
                    end = datetime.datetime.fromisoformat(med['end_date']).date()
                if start <= today and (end is None or today <= end):
                    today_logs = [
                        l for l in med.get('taken_logs', [])
                        if datetime.datetime.fromisoformat(l['timestamp']).date() == today
                    ]
                    m = {**med, 'plan_id': schedule['plan_id'],
                         'today_taken_count': len(today_logs),
                         'today_remaining_count': med['times_per_day'] - len(today_logs),
                         'next_time': self._get_next_dose_time(med)}
                    today_meds.append(m)
        today_meds.sort(key=lambda m: m['next_time'] or '23:59')
        return today_meds

    def get_upcoming_doses(self, user_id: str, hours: int = 2) -> List[Dict]:
        now = datetime.datetime.now()
        window = now + datetime.timedelta(hours=hours)
        upcoming = []
        for med in self.get_today_medication_schedule(user_id):
            if med.get('today_remaining_count', 0) > 0 and med.get('next_time'):
                h, m = map(int, med['next_time'].split(':'))
                next_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if next_dt < now:
                    next_dt += datetime.timedelta(days=1)
                if now <= next_dt <= window:
                    upcoming.append({'medication_id': med['id'], 'name': med['name'],
                                     'description': med.get('description', ''),
                                     'dose_time': next_dt.isoformat(),
                                     'minutes_until': (next_dt - now).total_seconds() // 60})
        upcoming.sort(key=lambda d: d['dose_time'])
        return upcoming

    def get_adherence_stats(self, user_id: str, days: int = 7) -> Dict[str, Any]:
        if self._use_db:
            try:
                return self._db.get_medication_adherence(user_id, days)
            except Exception as e:
                logger.warning(f"DB unavailable for get_adherence_stats: {e}")
        # fallback: compute from in-memory data
        now = datetime.datetime.now()
        total, taken = 0, 0
        for schedule in self.get_user_schedules(user_id):
            for med in schedule.get('medications', []):
                total += days * med.get('times_per_day', 1)
                taken += sum(
                    1 for l in med.get('taken_logs', [])
                    if (now - datetime.datetime.fromisoformat(l['timestamp'])).days <= days
                )
        overall = (taken / total * 100) if total > 0 else 0
        return {'overall_adherence': round(overall, 1), 'total_doses': total,
                'taken_doses': taken, 'missed_doses': total - taken, 'days_analyzed': days}

    # ------------------------------------------------------------------
    # Private helpers (unchanged logic)
    # ------------------------------------------------------------------

    def _parse_frequency(self, frequency: str) -> int:
        freq = frequency.lower()
        if 'four times' in freq or 'qid' in freq:
            return 4
        if 'three times' in freq or 'tid' in freq:
            return 3
        if 'twice' in freq or 'two times' in freq or 'bid' in freq:
            return 2
        if 'once' in freq or 'daily' in freq:
            return 1
        if 'every' in freq and 'hours' in freq:
            try:
                hours = int(''.join(filter(str.isdigit, freq)))
                return 24 // hours if hours > 0 else 1
            except (ValueError, ZeroDivisionError):
                return 1
        return 1

    def _generate_default_times(self, times_per_day: int) -> List[str]:
        defaults = {1: ['08:00'], 2: ['08:00', '20:00'],
                    3: ['08:00', '14:00', '20:00'], 4: ['08:00', '12:00', '16:00', '20:00']}
        if times_per_day in defaults:
            return defaults[times_per_day]
        interval = 14 / (times_per_day or 1)
        return [f"{8 + int(i * interval):02d}:{int((i * interval * 60) % 60):02d}"
                for i in range(times_per_day)]

    def _get_next_dose_time(self, medication: Dict[str, Any]) -> Optional[str]:
        schedule = medication.get('schedule') or medication.get('schedule_times', [])
        if not schedule:
            return None
        now = datetime.datetime.now()
        current = f"{now.hour:02d}:{now.minute:02d}"
        today = now.date()
        today_logs = [
            l for l in medication.get('taken_logs', [])
            if datetime.datetime.fromisoformat(l['timestamp']).date() == today
        ]
        if len(today_logs) >= medication.get('times_per_day', 1):
            return None
        for t in sorted(schedule):
            if t > current:
                return t
        return sorted(schedule)[0] if schedule else None
