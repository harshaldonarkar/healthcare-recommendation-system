# tests/test_medication_reminder.py
"""
Tests for MedicationReminder (DB-backed with in-memory fallback).
Run: PYTHONPATH=src/backend python -m pytest tests/test_medication_reminder.py -v
"""
import sys
import os
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'backend'))


@pytest.fixture
def reminder():
    """MedicationReminder in in-memory fallback mode."""
    from medication_reminder import MedicationReminder
    r = MedicationReminder()
    r._use_db = False
    r._db = None
    return r


class TestParseFrequency:
    @pytest.fixture(autouse=True)
    def _reminder(self, reminder):
        self.r = reminder

    def test_once_daily(self):
        assert self.r._parse_frequency('Once daily') == 1

    def test_twice_daily(self):
        assert self.r._parse_frequency('Twice daily') == 2

    def test_three_times(self):
        assert self.r._parse_frequency('Three times daily') == 3

    def test_four_times(self):
        assert self.r._parse_frequency('Four times daily') == 4

    def test_every_8_hours(self):
        assert self.r._parse_frequency('Every 8 hours') == 3

    def test_unknown_defaults_to_1(self):
        assert self.r._parse_frequency('As needed') == 1


class TestGenerateDefaultTimes:
    @pytest.fixture(autouse=True)
    def _reminder(self, reminder):
        self.r = reminder

    def test_once_gives_one_time(self):
        assert len(self.r._generate_default_times(1)) == 1

    def test_twice_gives_two_times(self):
        assert len(self.r._generate_default_times(2)) == 2

    def test_three_gives_three_times(self):
        assert len(self.r._generate_default_times(3)) == 3

    def test_four_gives_four_times(self):
        assert len(self.r._generate_default_times(4)) == 4

    def test_times_are_hhmm_format(self):
        for t in self.r._generate_default_times(2):
            assert len(t) == 5
            assert t[2] == ':'


class TestInMemoryOperations:
    def test_create_schedule_returns_string_id(self, reminder):
        sid = reminder.create_medication_schedule('u1', 'plan1', [{'name': 'Aspirin', 'frequency': 'Once daily'}])
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_get_user_schedules_empty(self, reminder):
        assert reminder.get_user_schedules('nobody') == []

    def test_get_user_schedules_returns_created(self, reminder):
        reminder.create_medication_schedule('u2', 'p1', [{'name': 'Ibuprofen', 'frequency': 'Twice daily'}])
        schedules = reminder.get_user_schedules('u2')
        assert len(schedules) == 1
        assert schedules[0]['medications'][0]['name'] == 'Ibuprofen'

    def test_log_medication_taken_returns_true(self, reminder):
        sid = reminder.create_medication_schedule('u3', 'p1', [{'name': 'Aspirin', 'frequency': 'Once daily'}])
        schedule = reminder.get_medication_schedule('u3', sid)
        med_id = schedule['medications'][0]['id']
        assert reminder.log_medication_taken('u3', sid, med_id) is True

    def test_log_medication_taken_returns_false_bad_schedule(self, reminder):
        assert reminder.log_medication_taken('u3', 'bad-sid', 'bad-mid') is False

    def test_update_medication_schedule_works(self, reminder):
        sid = reminder.create_medication_schedule('u4', 'p1', [{'name': 'Aspirin', 'frequency': 'Once daily'}])
        schedule = reminder.get_medication_schedule('u4', sid)
        med_id = schedule['medications'][0]['id']
        result = reminder.update_medication_schedule('u4', sid, med_id, {'frequency': 'Twice daily'})
        assert result is True

    def test_get_medication_schedule_returns_none_for_unknown(self, reminder):
        assert reminder.get_medication_schedule('u1', 'nonexistent') is None


class TestDBBackend:
    def test_create_schedule_delegates_to_db(self):
        from medication_reminder import MedicationReminder
        mock_db = MagicMock()
        mock_db.create_medication_schedule.return_value = 'db-schedule-id'
        r = MedicationReminder()
        r._use_db = True
        r._db = mock_db
        sid = r.create_medication_schedule('user', 'plan', [{'name': 'X', 'frequency': 'Once daily'}])
        assert mock_db.create_medication_schedule.called
        assert sid == 'db-schedule-id'

    def test_fallback_on_db_error(self):
        from medication_reminder import MedicationReminder
        mock_db = MagicMock()
        mock_db.create_medication_schedule.side_effect = Exception("DB down")
        r = MedicationReminder()
        r._use_db = True
        r._db = mock_db
        sid = r.create_medication_schedule('user', 'plan', [{'name': 'Y', 'frequency': 'Once daily'}])
        assert isinstance(sid, str)  # fallback UUID
