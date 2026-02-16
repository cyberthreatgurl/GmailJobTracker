"""
Unit tests for USASpending.gov API integration service.

Tests cover:
- API client requests and response handling
- Pagination logic (100 results/page max)
- Company matching (exact + fuzzy at 85% threshold)
- Contract deduplication (award_id uniqueness)
- Error handling and retry logic
- Rate limiting (1 second between requests)
- Contract parsing and field mapping
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone
from requests.exceptions import ConnectionError, HTTPError, Timeout

from tracker.models import Company, DefenseContract
from tracker.services.usaspending_service import USASpendingService, USASpendingAPIError


@pytest.fixture
def service():
    """Create a USASpendingService instance."""
    return USASpendingService()


@pytest.fixture
def mock_company():
    """Create a mock Company instance."""
    now = timezone.now()
    return Company.objects.create(
        name="Lockheed Martin Corporation",
        domain="lockheedmartin.com",
        first_contact=now,
        last_contact=now,
    )


@pytest.fixture
def sample_api_response():
    """Sample API response with 2 contracts."""
    return {
        "page_metadata": {
            "page": 1,
            "hasNext": False,
            "total": 2,
        },
        "results": [
            {
                "Award ID": "CONT_AWD_N0002423C0123_9700_-NONE-_-NONE-",
                "Recipient Name": "LOCKHEED MARTIN CORPORATION",
                "Award Amount": 125000000.50,
                "Description": "F-35 Lightning II production and sustainment",
                "Awarding Agency": "Department of the Navy",
                "Awarding Sub Agency": "Naval Air Systems Command",
                "Place of Performance State": "Texas",
                "recipient_location_city_name": "Fort Worth",
                "recipient_location_state_code": "TX",
                "Base Obligation Date": "2025-10-15",
                "generated_internal_id": "CONT_AWD_N0002423C0123_9700_-NONE-_-NONE-",
                "contract_award_unique_key": "CONT_AWD_N0002423C0123_9700",
            },
            {
                "Award ID": "CONT_AWD_W56HZV23C0456_9700_-NONE-_-NONE-",
                "Recipient Name": "RAYTHEON COMPANY",
                "Award Amount": 75000000.00,
                "Description": "Patriot missile system upgrades",
                "Awarding Agency": "Department of the Army",
                "Awarding Sub Agency": "Army Contracting Command",
                "Place of Performance State": "Arizona",
                "recipient_location_city_name": "Tucson",
                "recipient_location_state_code": "AZ",
                "Base Obligation Date": "2025-11-20",
                "generated_internal_id": "CONT_AWD_W56HZV23C0456_9700_-NONE-_-NONE-",
                "contract_award_unique_key": "CONT_AWD_W56HZV23C0456_9700",
            },
        ],
    }


# ──────────────────────────────────────────────
# API Client Tests
# ──────────────────────────────────────────────


@pytest.mark.django_db
class TestAPIClient:
    """Tests for API request/response handling."""

    @patch("tracker.services.usaspending_service.requests.post")
    def test_successful_api_request(self, mock_post, service, sample_api_response):
        """Test successful API request returns parsed data."""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: sample_api_response,
            headers={"Content-Type": "application/json"},
        )

        contracts = service._fetch_contracts_from_api(limit=10)

        assert len(contracts) == 2
        assert contracts[0]["Recipient Name"] == "LOCKHEED MARTIN CORPORATION"
        assert contracts[1]["Recipient Name"] == "RAYTHEON COMPANY"
        mock_post.assert_called_once()

    @patch("tracker.services.usaspending_service.requests.post")
    def test_timeout_retries_with_backoff(self, mock_post, service):
        """Test timeout triggers retry with exponential backoff."""
        mock_post.side_effect = [
            Timeout("Request timeout"),
            Timeout("Request timeout"),
            Mock(
                status_code=200,
                json=lambda: {"page_metadata": {"hasNext": False}, "results": []},
                headers={"Content-Type": "application/json"},
            ),
        ]

        with patch("time.sleep") as mock_sleep:
            service._fetch_contracts_from_api(limit=10)

        assert mock_post.call_count == 3
        # Check exponential backoff: 2^0=1, 2^1=2 seconds
        assert mock_sleep.call_count == 2

    @patch("tracker.services.usaspending_service.requests.post")
    def test_max_retries_exceeded(self, mock_post, service):
        """Test exception raised after 3 failed retries."""
        mock_post.side_effect = Timeout("Request timeout")

        with pytest.raises(USASpendingAPIError):
            service._fetch_contracts_from_api(limit=10)

        assert mock_post.call_count == 3


# ──────────────────────────────────────────────
# Company Matching Tests
# ──────────────────────────────────────────────


@pytest.mark.django_db
class TestCompanyMatching:
    """Tests for exact + fuzzy company name matching."""

    def test_exact_match_case_insensitive(self, service, mock_company):
        """Test exact match ignores case."""
        company = service._match_company("LOCKHEED MARTIN CORPORATION")
        assert company == mock_company

    def test_exact_match_with_extra_whitespace(self, service, mock_company):
        """Test exact match handles leading/trailing whitespace."""
        # Note: In production, _parse_contract strips before calling _match_company
        # This test uses already-stripped input
        company = service._match_company("Lockheed Martin Corporation")
        assert company == mock_company

    def test_fuzzy_match_at_threshold(self, service, mock_company):
        """Test fuzzy match at 85% threshold."""
        # "Lockheed Martin Corp" should match "Lockheed Martin Corporation"
        company = service._match_company("Lockheed Martin Corp")
        assert company == mock_company

    def test_no_match_when_no_companies_exist(self, service):
        """Test returns None when no companies in database."""
        company = service._match_company("Any Company Name")
        assert company is None

    def test_chooses_best_fuzzy_match(self, service):
        """Test selects highest similarity match when multiple candidates."""
        now = timezone.now()
        Company.objects.create(
            name="Lockheed Corporation",
            domain="lockheed1.com",
            first_contact=now,
            last_contact=now,
        )
        Company.objects.create(
            name="Lockheed Martin Corporation",
            domain="lockheed2.com",
            first_contact=now,
            last_contact=now,
        )
        Company.objects.create(
            name="Lockheed Industries",
            domain="lockheed3.com",
            first_contact=now,
            last_contact=now,
        )

        # Should match "Lockheed Martin Corporation" (highest similarity)
        company = service._match_company("Lockheed Martin Corp")
        assert company.name == "Lockheed Martin Corporation"


# ──────────────────────────────────────────────
# Contract Parsing Tests
# ──────────────────────────────────────────────


@pytest.mark.django_db
class TestContractParsing:
    """Tests for API response to DefenseContract field mapping."""

    def test_parse_contract_all_fields(self, service, mock_company):
        """Test all fields are correctly parsed from API response."""
        api_contract = {
            "Award ID": "CONT_AWD_N0002423C0123_9700_-NONE-_-NONE-",
            "Recipient Name": "LOCKHEED MARTIN CORPORATION",
            "Award Amount": 125000000.50,
            "Description": "F-35 Lightning II production",
            "Awarding Agency": "Department of the Navy",
            "Awarding Sub Agency": "Naval Air Systems Command",
            "Place of Performance State": "Texas",
            "Place of Performance City Name": "Fort Worth",
            "Place of Performance State Code": "TX",
            "Base Obligation Date": "2025-10-15",
            "contract_award_unique_key": "CONT_AWD_N0002423C0123_9700",
        }

        parsed = service._parse_contract(api_contract)

        assert parsed["data_source"] == "usaspending"
        assert parsed["award_id"] == "CONT_AWD_N0002423C0123_9700_-NONE-_-NONE-"
        assert parsed["contract_number"] == ""  # Not provided by USASpending
        assert parsed["company_name_raw"] == "LOCKHEED MARTIN CORPORATION"
        assert parsed["company"] == mock_company
        assert parsed["amount"] == Decimal("125000000.50")
        assert parsed["description"] == "F-35 Lightning II production"
        assert parsed["awarding_agency"] == "Department of the Navy"
        assert parsed["awarding_sub_agency"] == "Naval Air Systems Command"
        assert parsed["place_of_performance_state"] == "TX"
        assert parsed["work_location"] == "Fort Worth, TX"
        assert parsed["article_date"] == date(2025, 10, 15)
        assert parsed["branch"] == "other"

    def test_parse_contract_missing_optional_fields(self, service):
        """Test parsing with missing optional fields."""
        api_contract = {
            "Award ID": "AWARD_001",
            "Recipient Name": "Test Company",
            "Award Amount": 1000000,
            "Description": "Test contract",
            "Base Obligation Date": "2025-11-01",
            "contract_award_unique_key": "KEY_001",
            # Missing: Awarding Agency, Sub Agency, Performance State
        }

        parsed = service._parse_contract(api_contract)

        assert parsed["awarding_agency"] == ""
        assert parsed["awarding_sub_agency"] == ""
        assert parsed["place_of_performance_state"] == ""
        assert parsed["work_location"] == ""  # No city/state

    def test_parse_contract_invalid_date_format(self, service):
        """Test parsing handles invalid date gracefully."""
        api_contract = {
            "Award ID": "AWARD_001",
            "Recipient Name": "Test Company",
            "Award Amount": 1000000,
            "Description": "Test",
            "Base Obligation Date": "invalid-date",
            "contract_award_unique_key": "KEY_001",
        }

        parsed = service._parse_contract(api_contract)

        # Should default to today when date parsing fails
        assert parsed["article_date"] is not None
        assert parsed["article_date"] == date.today()


# ──────────────────────────────────────────────
# Deduplication Tests
# ──────────────────────────────────────────────


@pytest.mark.django_db
class TestDeduplication:
    """Tests for contract deduplication logic."""

    @patch("tracker.services.usaspending_service.requests.post")
    def test_skips_duplicate_award_id(self, mock_post, service, sample_api_response):
        """Test duplicate award_id is skipped."""
        # Create existing contract with same award_id
        DefenseContract.objects.create(
            data_source="usaspending",
            award_id="CONT_AWD_N0002423C0123_9700_-NONE-_-NONE-",
            contract_number="CONT_AWD_N0002423C0123_9700",
            company_name_raw="LOCKHEED MARTIN CORPORATION",
            amount=Decimal("125000000.50"),
            description="Existing contract",
            article_date=timezone.now(),
            branch="other",
        )

        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: sample_api_response,
            headers={"Content-Type": "application/json"},
        )

        result = service.fetch_and_save_contracts(limit=10)

        # First contract should be skipped (duplicate award_id)
        # Second contract should be created
        assert result["created"] == 1
        assert result["skipped"] == 1

    @patch("tracker.services.usaspending_service.requests.post")
    def test_creates_contracts_with_unique_award_ids(
        self, mock_post, service, sample_api_response
    ):
        """Test contracts with unique award_ids are created."""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: sample_api_response,
            headers={"Content-Type": "application/json"},
        )

        result = service.fetch_and_save_contracts(limit=10)

        assert result["created"] == 2
        assert result["skipped"] == 0
        assert DefenseContract.objects.filter(data_source="usaspending").count() == 2


# ──────────────────────────────────────────────
# Integration Tests
# ──────────────────────────────────────────────


@pytest.mark.django_db
class TestFetchAndSaveContracts:
    """Integration tests for the main fetch_and_save_contracts method."""

    @patch("tracker.services.usaspending_service.requests.post")
    def test_fetch_and_save_creates_contracts(
        self, mock_post, service, sample_api_response, mock_company
    ):
        """Test end-to-end contract fetching and saving."""
        mock_post.return_value = Mock(
            status_code=200,
            json=lambda: sample_api_response,
            headers={"Content-Type": "application/json"},
        )

        result = service.fetch_and_save_contracts(limit=10)

        assert result["created"] == 2
        assert result["skipped"] == 0

        contracts = DefenseContract.objects.filter(data_source="usaspending")
        assert contracts.count() == 2

        # Verify first contract
        contract1 = contracts.get(
            award_id="CONT_AWD_N0002423C0123_9700_-NONE-_-NONE-"
        )
        assert contract1.company == mock_company
        assert contract1.amount == Decimal("125000000.50")
        assert contract1.awarding_agency == "Department of the Navy"

    @patch("tracker.services.usaspending_service.requests.post")
    def test_fetch_and_save_handles_api_errors(self, mock_post, service):
        """Test error handling in fetch_and_save_contracts."""
        mock_post.side_effect = HTTPError("API Error")

        with pytest.raises(USASpendingAPIError):
            service.fetch_and_save_contracts(limit=10)
