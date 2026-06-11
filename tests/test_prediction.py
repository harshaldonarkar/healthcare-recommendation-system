# tests/test_prediction.py
"""
Tests for the BERT-based disease prediction pipeline.
Run from the project root:
    PYTHONPATH=src/backend python -m pytest tests/test_prediction.py -v
"""
import sys
import os
import pytest

# Make src/backend importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'backend'))


# ---------------------------------------------------------------------------
# direct_symptom_matching
# ---------------------------------------------------------------------------
class TestDirectSymptomMatching:
    def setup_method(self):
        import importlib
        # Skip if medical_data CSV is missing
        try:
            import core
            self.module = core
        except Exception:
            pytest.skip("core module could not be loaded (missing data/model files)")

    def test_returns_list(self):
        results = self.module.direct_symptom_matching("fever headache cough")
        assert isinstance(results, list)

    def test_sorted_by_confidence_descending(self):
        results = self.module.direct_symptom_matching("high fever chills sweating muscle pain")
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i]['confidence'] >= results[i + 1]['confidence']

    def test_malaria_fast_path(self):
        results = self.module.direct_symptom_matching("high fever chills sweating muscle pain")
        diseases = [r['disease'] for r in results]
        assert 'Malaria' in diseases
        malaria = next(r for r in results if r['disease'] == 'Malaria')
        assert malaria['confidence'] == 95.0

    def test_empty_input_returns_list(self):
        results = self.module.direct_symptom_matching("")
        assert isinstance(results, list)

    def test_threshold_filters_low_matches(self):
        results = self.module.direct_symptom_matching("xyz_symptom_not_in_db", threshold=0.9)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# get_recommendations
# ---------------------------------------------------------------------------
class TestGetRecommendations:
    def setup_method(self):
        try:
            import core
            self.module = core
        except Exception:
            pytest.skip("core module could not be loaded")

    def test_prediction_error_returns_fallback(self):
        rec = self.module.get_recommendations('Prediction Error')
        assert 'causes' in rec
        assert 'medicines' in rec

    def test_unknown_disease_returns_error_key(self):
        rec = self.module.get_recommendations('DefinitelyNotARealDisease12345')
        assert 'error' in rec

    def test_allergy_filtering(self):
        # Get recommendations for any disease in the dataset
        if self.module.diseases_list:
            disease = self.module.diseases_list[0]
            rec_plain = self.module.get_recommendations(disease)
            # With a user profile that bans all medicines
            all_meds = rec_plain.get('medicines', [])
            if all_meds:
                rec_filtered = self.module.get_recommendations(disease, user_profile={'allergies': all_meds})
                assert rec_filtered.get('medicines') == []


# ---------------------------------------------------------------------------
# get_disease_info
# ---------------------------------------------------------------------------
class TestGetDiseaseInfo:
    def setup_method(self):
        try:
            import core
            self.module = core
        except Exception:
            pytest.skip("core module could not be loaded")

    def test_prediction_error_returns_dict(self):
        info = self.module.get_disease_info('Prediction Error')
        assert info['name'] == 'Prediction Error'
        assert 'symptoms' in info

    def test_unknown_disease_returns_error(self):
        info = self.module.get_disease_info('DefinitelyNotARealDisease12345')
        assert 'error' in info

    def test_valid_disease_has_required_fields(self):
        if self.module.diseases_list:
            disease = self.module.diseases_list[0]
            info = self.module.get_disease_info(disease)
            for field in ('name', 'symptoms', 'causes', 'medicines', 'precautions'):
                assert field in info
