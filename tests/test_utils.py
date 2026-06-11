# tests/test_utils.py
"""
Tests for src/backend/utils.py utility functions.
Run: PYTHONPATH=src/backend python -m pytest tests/test_utils.py -v
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'backend'))

from utils import parse_medicine_list, format_symptoms_for_display, safe_get, calculate_severity


class TestParseMedicineList:
    def test_parses_json_array(self):
        result = parse_medicine_list('["Aspirin", "Ibuprofen"]')
        assert result == ['Aspirin', 'Ibuprofen']

    def test_parses_single_quotes(self):
        result = parse_medicine_list("['Paracetamol', 'Amoxicillin']")
        assert 'Paracetamol' in result
        assert 'Amoxicillin' in result

    def test_returns_list(self):
        result = parse_medicine_list('["Aspirin"]')
        assert isinstance(result, list)

    def test_fallback_on_malformed(self):
        result = parse_medicine_list('Aspirin, Ibuprofen')
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_single_medicine(self):
        result = parse_medicine_list('["Aspirin"]')
        assert len(result) == 1
        assert result[0] == 'Aspirin'


class TestFormatSymptomsForDisplay:
    def test_empty_list(self):
        result = format_symptoms_for_display([])
        assert result == 'No symptoms specified'

    def test_none_values_filtered(self):
        result = format_symptoms_for_display([None, '', None])
        assert result == 'No symptoms specified'

    def test_single_symptom(self):
        assert format_symptoms_for_display(['fever']) == 'fever'

    def test_two_symptoms(self):
        result = format_symptoms_for_display(['fever', 'cough'])
        assert 'fever' in result
        assert 'cough' in result
        assert 'and' in result

    def test_three_symptoms(self):
        result = format_symptoms_for_display(['fever', 'cough', 'fatigue'])
        assert 'fever' in result
        assert 'cough' in result
        assert 'fatigue' in result
        assert ',' in result

    def test_returns_string(self):
        assert isinstance(format_symptoms_for_display(['a', 'b', 'c']), str)


class TestSafeGet:
    def test_returns_value_for_existing_key(self):
        assert safe_get({'a': 1}, 'a') == 1

    def test_returns_default_for_missing_key(self):
        assert safe_get({'a': 1}, 'b') is None

    def test_returns_custom_default(self):
        assert safe_get({'a': 1}, 'b', 'default') == 'default'

    def test_handles_non_dict(self):
        result = safe_get(None, 'key', 'fallback')
        assert result == 'fallback'

    def test_handles_none_value(self):
        assert safe_get({'key': None}, 'key') is None


class TestCalculateSeverity:
    def test_empty_returns_unknown(self):
        assert calculate_severity([]) == 'Unknown'

    def test_high_confidence(self):
        assert calculate_severity([95.0]) == 'High'

    def test_medium_confidence(self):
        assert calculate_severity([75.0]) == 'Medium'

    def test_low_confidence(self):
        assert calculate_severity([50.0]) == 'Low'

    def test_uses_maximum(self):
        assert calculate_severity([20.0, 95.0, 30.0]) == 'High'

    def test_boundary_90(self):
        assert calculate_severity([90.0]) == 'High'

    def test_boundary_70(self):
        assert calculate_severity([70.0]) == 'Medium'
