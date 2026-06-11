# tests/test_progress_tracker.py
"""
Tests for ProgressTracker (DB-backed with in-memory fallback).
Run: PYTHONPATH=src/backend python -m pytest tests/test_progress_tracker.py -v
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'backend'))


@pytest.fixture
def tracker_no_db():
    """ProgressTracker forced into in-memory fallback mode."""
    with patch.dict('sys.modules', {'db': None}):
        from progress_tracker import ProgressTracker
        t = ProgressTracker()
        t._use_db = False
        t._db = None
        return t


@pytest.fixture
def mock_db():
    m = MagicMock()
    m.create_treatment_plan.return_value = 42
    m.create_treatment_steps.return_value = [
        {'id': '1', 'type': 'medication', 'name': 'Aspirin',
         'description': 'Take as prescribed', 'frequency': 'Daily', 'status': 'not_started',
         'completions': [], 'notes': []}
    ]
    m.get_treatment_plan.return_value = {
        'plan_id': 42, 'disease_name': 'Flu', 'status': 'active',
        'created_at': '2026-01-01T00:00:00',
    }
    m.get_treatment_steps.return_value = [
        {'step_id': 1, 'step_type': 'medication', 'name': 'Aspirin',
         'description': '', 'frequency': 'Daily', 'status': 'completed'}
    ]
    m.get_plan_symptom_logs.return_value = []
    m.get_plan_notes.return_value = []
    m.get_user_plans.return_value = [{'id': 42, 'disease': 'Flu', 'status': 'active'}]
    m.update_step_status.return_value = True
    m.log_symptom.return_value = None
    m.add_plan_note.return_value = None
    return m


@pytest.fixture
def tracker_with_db(mock_db):
    from progress_tracker import ProgressTracker
    t = ProgressTracker()
    t._use_db = True
    t._db = mock_db
    return t


class TestInMemoryFallback:
    def test_create_plan_returns_string_id(self, tracker_no_db):
        plan_id = tracker_no_db.create_treatment_plan(
            'user1', 'Flu', {'medicines': ['Paracetamol'], 'diet': 'Rest', 'workout': '', 'precautions': []})
        assert isinstance(plan_id, str)
        assert len(plan_id) > 0

    def test_get_user_plans_empty(self, tracker_no_db):
        plans = tracker_no_db.get_user_plans('unknown_user')
        assert plans == []

    def test_get_user_plans_returns_created(self, tracker_no_db):
        tracker_no_db.create_treatment_plan('u1', 'Flu', {'medicines': ['X'], 'diet': '', 'workout': '', 'precautions': []})
        plans = tracker_no_db.get_user_plans('u1')
        assert len(plans) == 1

    def test_log_symptom_returns_false_for_unknown_plan(self, tracker_no_db):
        result = tracker_no_db.log_symptom('u1', 'nonexistent-plan', 'headache', 5)
        assert result is False

    def test_log_symptom_returns_true_for_known_plan(self, tracker_no_db):
        plan_id = tracker_no_db.create_treatment_plan('u2', 'Cold', {'medicines': [], 'diet': '', 'workout': '', 'precautions': []})
        result = tracker_no_db.log_symptom('u2', plan_id, 'runny nose', 3)
        assert result is True

    def test_add_note_returns_false_for_unknown_plan(self, tracker_no_db):
        assert tracker_no_db.add_note('u1', 'bad-id', 'note') is False

    def test_add_note_works_for_known_plan(self, tracker_no_db):
        plan_id = tracker_no_db.create_treatment_plan('u3', 'Cold', {'medicines': [], 'diet': '', 'workout': '', 'precautions': []})
        assert tracker_no_db.add_note('u3', plan_id, 'Feeling better') is True

    def test_progress_summary_no_steps(self, tracker_no_db):
        plan_id = tracker_no_db.create_treatment_plan('u4', 'Flu', {'medicines': [], 'diet': '', 'workout': '', 'precautions': []})
        summary = tracker_no_db.get_progress_summary('u4', plan_id)
        assert summary is not None
        assert summary['progress_percentage'] == 0.0
        assert summary['total_steps'] == 0

    def test_progress_summary_with_completed_steps(self, tracker_no_db):
        plan_id = tracker_no_db.create_treatment_plan(
            'u5', 'Flu', {'medicines': ['A', 'B'], 'diet': '', 'workout': '', 'precautions': []})
        plan = tracker_no_db._fallback['u5'][plan_id]
        step_id = plan['treatment_steps'][0]['id']
        tracker_no_db.update_step_status('u5', plan_id, step_id, 'completed')
        summary = tracker_no_db.get_progress_summary('u5', plan_id)
        assert summary['completed_steps'] == 1
        assert summary['progress_percentage'] == 50.0

    def test_update_step_status_returns_false_for_bad_plan(self, tracker_no_db):
        assert tracker_no_db.update_step_status('u1', 'bad', 'bad', 'completed') is False


class TestDBBackend:
    def test_create_plan_calls_db(self, tracker_with_db, mock_db):
        plan_id = tracker_with_db.create_treatment_plan('admin', 'Flu', {'medicines': ['X'], 'diet': '', 'workout': '', 'precautions': []})
        assert mock_db.create_treatment_plan.called
        assert mock_db.create_treatment_steps.called
        assert plan_id == '42'

    def test_get_user_plans_delegates_to_db(self, tracker_with_db, mock_db):
        plans = tracker_with_db.get_user_plans('admin')
        assert mock_db.get_user_plans.called
        assert len(plans) == 1

    def test_fallback_on_db_error(self, tracker_with_db, mock_db):
        mock_db.create_treatment_plan.side_effect = Exception("DB down")
        plan_id = tracker_with_db.create_treatment_plan('u', 'Flu', {'medicines': [], 'diet': '', 'workout': '', 'precautions': []})
        assert isinstance(plan_id, str)  # fallback still works
