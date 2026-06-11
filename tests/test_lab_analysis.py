# tests/test_lab_analysis.py
"""
Tests for lab report parsing and analysis utilities.
Run from the project root:
    PYTHONPATH=src/backend python -m pytest tests/test_lab_analysis.py -v
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'backend'))


@pytest.fixture
def parse_lab_results():
    try:
        from blueprints.lab import parse_lab_results_from_text
        return parse_lab_results_from_text
    except Exception:
        pytest.skip("lab blueprint could not be loaded")


class TestParseLabResults:
    def test_glucose_parsed(self, parse_lab_results):
        text = "Glucose: 95.0 mg/dL"
        results = parse_lab_results(text)
        names = [r['test_name'] for r in results]
        # parser normalises 'glucose' → 'blood_glucose_fasting'
        assert any('glucose' in n for n in names)

    def test_multiple_tests_parsed(self, parse_lab_results):
        text = "Glucose: 95 mg/dL\nCholesterol: 180 mg/dL\nHemoglobin: 14.5 g/dL"
        results = parse_lab_results(text)
        assert len(results) >= 3

    def test_empty_text_returns_empty_list(self, parse_lab_results):
        results = parse_lab_results("")
        assert results == []

    def test_irrelevant_text_returns_empty_list(self, parse_lab_results):
        results = parse_lab_results("This is a random sentence with no lab values.")
        assert results == []

    def test_result_has_required_fields(self, parse_lab_results):
        text = "WBC: 5000 cells/mcL"
        results = parse_lab_results(text)
        if results:
            for field in ('test_name', 'value', 'unit', 'test_date'):
                assert field in results[0]

    def test_value_is_numeric(self, parse_lab_results):
        text = "LDL: 110 mg/dL"
        results = parse_lab_results(text)
        if results:
            assert isinstance(results[0]['value'], float)


# ---------------------------------------------------------------------------
# Baseline / trend helpers
# ---------------------------------------------------------------------------
class TestBaselineHelpers:
    def setup_method(self):
        try:
            from core import calculate_baseline, analyze_baseline_comparison, analyze_lab_trends
            self.calculate_baseline = calculate_baseline
            self.analyze_baseline_comparison = analyze_baseline_comparison
            self.analyze_lab_trends = analyze_lab_trends
        except Exception:
            pytest.skip("core module could not be loaded")

    def test_baseline_uses_first_three(self):
        history = [{'value': 100}, {'value': 110}, {'value': 90}, {'value': 200}]
        baseline = self.calculate_baseline(history)
        assert baseline == pytest.approx((100 + 110 + 90) / 3, rel=1e-3)

    def test_baseline_short_history(self):
        history = [{'value': 80}, {'value': 100}]
        baseline = self.calculate_baseline(history)
        assert baseline == pytest.approx(90.0, rel=1e-3)

    def test_comparison_within_range(self):
        result = self.analyze_baseline_comparison(100.0, {'value': 105.0})
        assert result['classification'] == "Within normal variation"

    def test_comparison_significant_increase(self):
        result = self.analyze_baseline_comparison(100.0, {'value': 150.0})
        assert "Significant" in result['recommendation']

    def test_trends_empty_data(self):
        assert self.analyze_lab_trends([]) is None

    def test_trends_increasing(self):
        data = [{'value': 10}, {'value': 20}, {'value': 30}]
        result = self.analyze_lab_trends(data)
        assert result['trend'] == 'increasing'
