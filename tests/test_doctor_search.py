# tests/test_doctor_search.py
"""
Tests for DoctorSearch.
Run: PYTHONPATH=src/backend python -m pytest tests/test_doctor_search.py -v
"""
import sys
import os
import json
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'backend'))


@pytest.fixture
def sample_data_file():
    """Write a small doctors JSON file and return its path."""
    data = {
        "1": {
            "Hospital Name": "City General Hospital",
            "Speciality": "Cardiology",
            "Town": "Mumbai",
            "District": "Mumbai",
            "State": "Maharashtra",
            "Subdistrict": "",
            "Location": "Mumbai",
        },
        "2": {
            "Hospital Name": "Green Valley Clinic",
            "Speciality": "Dermatology",
            "Town": "Pune",
            "District": "Pune",
            "State": "Maharashtra",
            "Subdistrict": "",
            "Location": "Pune",
        },
        "3": {
            "Hospital Name": "North Star Medical",
            "Speciality": "Cardiology",
            "Town": "Delhi",
            "District": "Delhi",
            "State": "Delhi",
            "Subdistrict": "",
            "Location": "Delhi",
        },
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        return f.name


@pytest.fixture
def searcher(sample_data_file):
    try:
        from doctor_search import DoctorSearch
        return DoctorSearch(data_file=sample_data_file)
    except Exception:
        pytest.skip("DoctorSearch could not be loaded")


class TestSearchByCity:
    def test_returns_list(self, searcher):
        result = searcher.search_by_city('Mumbai')
        assert isinstance(result, list)

    def test_finds_doctors_in_city(self, searcher):
        result = searcher.search_by_city('Mumbai')
        assert len(result) >= 1

    def test_empty_city_returns_empty(self, searcher):
        result = searcher.search_by_city('')
        assert result == []

    def test_none_city_returns_empty(self, searcher):
        result = searcher.search_by_city(None)
        assert result == []

    def test_unknown_city_returns_empty(self, searcher):
        result = searcher.search_by_city('Atlantis_Not_Real_City_XYZ')
        assert result == []

    def test_case_insensitive_search(self, searcher):
        lower = searcher.search_by_city('mumbai')
        upper = searcher.search_by_city('MUMBAI')
        assert len(lower) == len(upper)

    def test_limit_respected(self, searcher):
        result = searcher.search_by_city('Maharashtra', limit=1)
        assert len(result) <= 1

    def test_multiple_cities(self, searcher):
        mumbai = searcher.search_by_city('Mumbai')
        pune = searcher.search_by_city('Pune')
        assert len(mumbai) >= 1
        assert len(pune) >= 1


class TestDoctorSearchInit:
    def test_loads_with_valid_file(self, sample_data_file):
        from doctor_search import DoctorSearch
        ds = DoctorSearch(data_file=sample_data_file)
        assert len(ds.doctors_data) == 3

    def test_handles_missing_file(self):
        from doctor_search import DoctorSearch
        ds = DoctorSearch(data_file='/nonexistent/path/doctors.json')
        assert ds.doctors_data == {}

    def test_search_returns_empty_when_no_data(self):
        from doctor_search import DoctorSearch
        ds = DoctorSearch(data_file='/nonexistent/path/doctors.json')
        assert ds.search_by_city('Mumbai') == []
