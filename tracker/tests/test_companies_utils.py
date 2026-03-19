from unittest.mock import MagicMock
import pytest
from tracker.views.companies import _parse_operating_cities, _company_matches_city


def test_parse_operating_cities_basic():
    """Test basic multiline splitting and whitespace cleanup."""
    raw_text = "New York, NY\n   Los Angeles, CA   \nChicago, IL"
    cities = _parse_operating_cities(raw_text)
    assert cities == ["New York, NY", "Los Angeles, CA", "Chicago, IL"]


def test_parse_operating_cities_deduplication():
    """Test that it correctly deduplicates cities while preserving order."""
    raw_text = "Austin, TX\nSeattle, WA\nAustin, TX\nBoston, MA\nseattle, wa"
    cities = _parse_operating_cities(raw_text)
    assert cities == ["Austin, TX", "Seattle, WA", "Boston, MA"]


def test_parse_operating_cities_empty():
    """Test edge cases with empty or None input."""
    assert _parse_operating_cities(None) == []
    assert _parse_operating_cities("") == []
    assert _parse_operating_cities("   \n\n  \n") == []


@pytest.fixture
def mock_company():
    """Provide a mock company object for testing location matching."""
    company = MagicMock()
    company.location = "San Francisco, CA"
    
    # Mock the operating_cities relationship
    city1 = MagicMock()
    city1.city = "Denver, CO"
    city2 = MagicMock()
    city2.city = "Austin, TX"
    
    company.operating_cities.all.return_value = [city1, city2]
    return company


def test_company_matches_city_exact(mock_company):
    """Test exact matching against HQ and operating cities."""
    # Note: Search terms are expected to be normalized before passing to this function
    assert _company_matches_city(mock_company, "san francisco, ca") is True
    assert _company_matches_city(mock_company, "denver, co") is True
    assert _company_matches_city(mock_company, "austin, tx") is True


def test_company_matches_city_fuzzy(mock_company):
    """Test fuzzy matching with slight typos."""
    # Missing a letter but still > 82% similarity
    assert _company_matches_city(mock_company, "san franciso, ca") is True
    assert _company_matches_city(mock_company, "denver co") is True


def test_company_matches_city_no_match(mock_company):
    """Test that unrelated cities return False."""
    assert _company_matches_city(mock_company, "new york, ny") is False
    assert _company_matches_city(mock_company, "chicago, il") is False
    assert _company_matches_city(mock_company, "") is False
    assert _company_matches_city(mock_company, None) is False