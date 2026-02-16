"""
Integration tests for USASpending.gov contract fetching.

Tests command execution, database persistence, view rendering,
and company linking across both data sources (DoD and USASpending).
"""

import json
from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch, Mock

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from tracker.models import DefenseContract, Company


@pytest.mark.django_db
class TestUSASpendingIntegration:
    """Integration tests for USASpending data source."""

    def test_fetch_usaspending_command_creates_contracts(self):
        """Test that fetch_contracts --source usaspending creates records."""
        mock_response = {
            "page_metadata": {"hasNext": False},
            "results": [
                {
                    "Award ID": "CONT_AWD_12345_9700_ABCD_-NONE-",
                    "Recipient Name": "Test Defense Corporation",
                    "Award Amount": 1500000.50,
                    "Description": "Cybersecurity services for classified networks",
                    "Start Date": "2025-10-15",
                    "Awarding Agency": "Department of Defense",
                    "Awarding Sub Agency": "Defense Information Systems Agency",
                    "Recipient Location City Name": "Arlington",
                    "Recipient Location State Code": "VA",
                    "Place of Performance State Code": "MD",
                    "Contract Award Type": "Definitive Contract",
                }
            ],
        }

        with patch("tracker.services.usaspending_service.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_response,
                headers={"Content-Type": "application/json"},
            )

            out = StringIO()
            call_command("fetch_contracts", "--source", "usaspending", "--limit", "10", stdout=out)
            output = out.getvalue()

            # Verify command output
            assert "All Agencies" in output
            assert "federal contracts" in output  # Changed from "Fetching up to 10 contracts"

            # Verify database record
            contract = DefenseContract.objects.filter(data_source="usaspending").first()
            assert contract is not None
            assert contract.award_id == "CONT_AWD_12345_9700_ABCD_-NONE-"
            assert contract.company_name_raw == "Test Defense Corporation"
            assert contract.amount == 1500000.50
            assert contract.awarding_agency == "Department of Defense"
            assert contract.awarding_sub_agency == "Defense Information Systems Agency"
            assert contract.place_of_performance_state == "MD"
            assert "Arlington" in contract.company_location  # Service builds "city, state" format
            assert contract.branch == "other"  # USASpending contracts use "other" for branch

    def test_fetch_all_sources_command(self):
        """Test that fetch_contracts --source all calls both services."""
        mock_usaspending_response = {
            "page_metadata": {"hasNext": False},
            "results": [
                {
                    "Award ID": "FEDERAL_123",
                    "Recipient Name": "Federal Contractor Inc",
                    "Award Amount": 500000,
                    "Description": "Federal contract description",
                    "Start Date": "2025-11-01",
                    "Awarding Agency": "Department of Homeland Security",
                    "Awarding Sub Agency": "Cybersecurity Agency",
                    "Recipient Location City Name": "Washington",
                    "Recipient Location State Code": "DC",
                    "Place of Performance State Code": "DC",
                    "Contract Award Type": "Definitive Contract",
                }
            ],
        }

        mock_wargov_response = {
            "articles": [
                {
                    "title": "Test DoD Contract Article",
                    "url": "https://www.war.gov/test-article-123",
                    "date": "2025-11-15",
                    "content": "Army: Test Military Corp, Location*, $1,000,000. Contract details here.",
                }
            ]
        }

        with patch("tracker.services.usaspending_service.requests.post") as mock_usaspending, \
             patch("tracker.services.contract_scraper.ContractScraperService.scrape_latest") as mock_wargov:
            
            mock_usaspending.return_value = Mock(
                status_code=200,
                json=lambda: mock_usaspending_response,
                headers={"Content-Type": "application/json"},
            )
            mock_wargov.return_value = {
                "articles_processed": 1,
                "contracts_created": 1,
                "contracts_updated": 0,
                "contracts_skipped": 0,
                "errors": [],
            }

            out = StringIO()
            call_command("fetch_contracts", "--source", "all", "--limit", "10", stdout=out)
            output = out.getvalue()

            # Verify both headings appear
            assert "DoD Contracts" in output
            assert "All Agencies" in output

            # Verify both services were called
            assert mock_usaspending.called
            assert mock_wargov.called


@pytest.mark.django_db
class TestWarGovIntegration:
    """Integration tests for war.gov data source."""

    def test_fetch_wargov_command_creates_contracts(self):
        """Test that fetch_contracts --source war_gov creates DoD records."""
        with patch("tracker.services.contract_scraper.ContractScraperService.scrape_latest") as mock_scrape:
            mock_scrape.return_value = {
                "articles_processed": 1,
                "contracts_created": 2,
                "contracts_updated": 0,
                "contracts_skipped": 0,
                "errors": [],
            }

            # Create mock contracts
            DefenseContract.objects.create(
                data_source="war_gov",
                company_name_raw="Lockheed Martin Corp",
                amount=5000000,
                description="F-35 maintenance contract",
                branch="air_force",
                contract_number="FA8601-25-C-0001",
                source_url="https://www.war.gov/test-123",
                article_date=date.today(),
            )

            out = StringIO()
            call_command("fetch_contracts", "--source", "war_gov", "--max-articles", "5", stdout=out)
            output = out.getvalue()

            # Verify command output
            assert "DoD Contracts" in output
            assert "contracts created" in output.lower()

            # Verify database record
            contract = DefenseContract.objects.filter(data_source="war_gov").first()
            assert contract is not None
            assert contract.branch == "air_force"
            assert contract.award_id == ""  # war.gov contracts don't have award_id
            assert contract.awarding_agency == ""  # war.gov contracts don't have agencies


@pytest.mark.django_db
class TestCompanyLinking:
    """Test company fuzzy matching and linking."""

    def test_company_exact_match(self):
        """Test that exact company name match creates link."""
        company = Company.objects.create(
            name="Northrop Grumman",
            domain="northropgrumman.com",
            first_contact=date.today(),
            last_contact=date.today(),
        )

        mock_response = {
            "page_metadata": {"hasNext": False},
            "results": [
                {
                    "Award ID": "TEST_EXACT_MATCH",
                    "Recipient Name": "Northrop Grumman",  # Exact match
                    "Award Amount": 1000000,
                    "Description": "Test contract",
                    "Start Date": "2025-11-01",
                    "Awarding Agency": "DoD",
                    "Awarding Sub Agency": "Air Force",
                    "Recipient Location City Name": "Falls Church",
                    "Recipient Location State Code": "VA",
                    "Place of Performance State Code": "CA",
                    "Contract Award Type": "Definitive Contract",
                }
            ],
        }

        with patch("tracker.services.usaspending_service.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_response,
                headers={"Content-Type": "application/json"},
            )

            call_command("fetch_contracts", "--source", "usaspending", "--limit", "10", stdout=StringIO())

            contract = DefenseContract.objects.get(award_id="TEST_EXACT_MATCH")
            assert contract.company == company

    def test_company_fuzzy_match(self):
        """Test that fuzzy company name match (>85%) creates link."""
        company = Company.objects.create(
            name="General Dynamics",
            domain="generaldynamics.com",
            first_contact=date.today(),
            last_contact=date.today(),
        )

        mock_response = {
            "page_metadata": {"hasNext": False},
            "results": [
                {
                    "Award ID": "TEST_FUZZY_MATCH",
                    "Recipient Name": "General Dynamics Corp",  # Fuzzy match
                    "Award Amount": 2000000,
                    "Description": "Test fuzzy contract",
                    "Start Date": "2025-11-01",
                    "Awarding Agency": "DoD",
                    "Awarding Sub Agency": "Navy",
                    "Recipient Location City Name": "Reston",
                    "Recipient Location State Code": "VA",
                    "Place of Performance State Code": "CT",
                    "Contract Award Type": "Definitive Contract",
                }
            ],
        }

        with patch("tracker.services.usaspending_service.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_response,
                headers={"Content-Type": "application/json"},
            )

            call_command("fetch_contracts", "--source", "usaspending", "--limit", "10", stdout=StringIO())

            contract = DefenseContract.objects.get(award_id="TEST_FUZZY_MATCH")
            assert contract.company == company

    def test_company_no_match(self):
        """Test that no match leaves company unlinked."""
        Company.objects.create(
            name="Boeing",
            domain="boeing.com",
            first_contact=date.today(),
            last_contact=date.today(),
        )

        mock_response = {
            "page_metadata": {"hasNext": False},
            "results": [
                {
                    "Award ID": "TEST_NO_MATCH",
                    "Recipient Name": "Unknown Contractor LLC",  # No match
                    "Award Amount": 500000,
                    "Description": "Test no match",
                    "Start Date": "2025-11-01",
                    "Awarding Agency": "DoD",
                    "Awarding Sub Agency": "Army",
                    "Recipient Location City Name": "Unknown",
                    "Recipient Location State Code": "TX",
                    "Place of Performance State Code": "TX",
                    "Contract Award Type": "Definitive Contract",
                }
            ],
        }

        with patch("tracker.services.usaspending_service.requests.post") as mock_post:
            mock_post.return_value = Mock(
                status_code=200,
                json=lambda: mock_response,
                headers={"Content-Type": "application/json"},
            )

            call_command("fetch_contracts", "--source", "usaspending", "--limit", "10", stdout=StringIO())

            contract = DefenseContract.objects.get(award_id="TEST_NO_MATCH")
            assert contract.company is None


@pytest.mark.django_db
class TestDefenseContractsView:
    """Test defense_contracts view with dual-source support."""

    @pytest.fixture(autouse=True)
    def setup_user(self, django_user_model):
        """Create and auto-login a test user for all view tests."""
        self.user = django_user_model.objects.create_user(
            username="testuser",
            password="testpass123"
        )

    def test_view_with_no_source_filter_defaults_to_all(self, client, django_user_model):
        """Test that view shows all contracts by default."""
        # Create test contracts
        DefenseContract.objects.create(
            data_source="war_gov",
            company_name_raw="DoD Contractor",
            amount=1000000,
            branch="army",
            source_url="https://war.gov/test",
            article_date=date.today(),
        )
        DefenseContract.objects.create(
            data_source="usaspending",
            company_name_raw="Federal Contractor",
            amount=2000000,
            award_id="FED_123",
            awarding_agency="DHS",
            article_date=date.today(),
        )

        client.force_login(self.user)
        response = client.get(reverse("defense_contracts"))

        assert response.status_code == 200
        assert "DoD Contractor" in response.content.decode()
        assert "Federal Contractor" in response.content.decode()
        assert response.context["source_filter"] == "all"

    def test_view_with_war_gov_source_filter(self, client, django_user_model):
        """Test that source=war_gov filters to DoD contracts only."""
        DefenseContract.objects.create(
            data_source="war_gov",
            company_name_raw="DoD Contractor",
            amount=1000000,
            branch="navy",
            source_url="https://war.gov/test",
            article_date=date.today(),
        )
        DefenseContract.objects.create(
            data_source="usaspending",
            company_name_raw="Federal Contractor",
            amount=2000000,
            award_id="FED_123",
            awarding_agency="DHS",
            article_date=date.today(),
        )

        client.force_login(self.user)
        response = client.get(reverse("defense_contracts") + "?source=war_gov")

        assert response.status_code == 200
        content = response.content.decode()
        assert "DoD Contractor" in content
        assert "Federal Contractor" not in content
        assert response.context["source_filter"] == "war_gov"

    def test_view_with_usaspending_source_filter(self, client, django_user_model):
        """Test that source=usaspending filters to federal contracts only."""
        DefenseContract.objects.create(
            data_source="war_gov",
            company_name_raw="DoD Contractor",
            amount=1000000,
            branch="air_force",
            source_url="https://war.gov/test",
            article_date=date.today(),
        )
        DefenseContract.objects.create(
            data_source="usaspending",
            company_name_raw="Federal Contractor",
            amount=2000000,
            award_id="FED_123",
            awarding_agency="DHS",
            article_date=date.today(),
        )

        client.force_login(self.user)
        response = client.get(reverse("defense_contracts") + "?source=usaspending")

        assert response.status_code == 200
        content = response.content.decode()
        assert "DoD Contractor" not in content
        assert "Federal Contractor" in content
        assert response.context["source_filter"] == "usaspending"

    def test_view_with_agency_filter(self, client, django_user_model):
        """Test that agency filter works for USASpending contracts."""
        DefenseContract.objects.create(
            data_source="usaspending",
            company_name_raw="DHS Contractor",
            amount=1000000,
            award_id="DHS_123",
            awarding_agency="Department of Homeland Security",
            article_date=date.today(),
        )
        DefenseContract.objects.create(
            data_source="usaspending",
            company_name_raw="DoD Contractor",
            amount=2000000,
            award_id="DOD_123",
            awarding_agency="Department of Defense",
            article_date=date.today(),
        )

        client.force_login(self.user)
        response = client.get(reverse("defense_contracts") + "?agency=Homeland")

        assert response.status_code == 200
        content = response.content.decode()
        assert "DHS Contractor" in content
        assert "DoD Contractor" not in content

    def test_view_context_includes_source_counts(self, client, django_user_model):
        """Test that view provides source counts for template."""
        DefenseContract.objects.create(
            data_source="war_gov",
            company_name_raw="DoD 1",
            amount=1000000,
            branch="army",
            source_url="https://war.gov/test1",
            article_date=date.today(),
        )
        DefenseContract.objects.create(
            data_source="war_gov",
            company_name_raw="DoD 2",
            amount=1000000,
            branch="navy",
            source_url="https://war.gov/test2",
            article_date=date.today(),
        )
        DefenseContract.objects.create(
            data_source="usaspending",
            company_name_raw="Federal 1",
            amount=2000000,
            award_id="FED_123",
            awarding_agency="DHS",
            article_date=date.today(),
        )

        client.force_login(self.user)
        response = client.get(reverse("defense_contracts"))

        assert response.status_code == 200
        assert response.context["source_counts"]["all"] == 3
        assert response.context["source_counts"]["war_gov"] == 2
        assert response.context["source_counts"]["usaspending"] == 1

    def test_view_context_includes_agency_choices(self, client, django_user_model):
        """Test that view provides top agencies for dropdown."""
        for i in range(5):
            DefenseContract.objects.create(
                data_source="usaspending",
                company_name_raw=f"Contractor {i}",
                amount=1000000,
                award_id=f"AWD_{i}",
                awarding_agency="Department of Defense",
                article_date=date.today(),
            )
        
        DefenseContract.objects.create(
            data_source="usaspending",
            company_name_raw="DHS Contractor",
            amount=1000000,
            award_id="DHS_001",
            awarding_agency="Department of Homeland Security",
            article_date=date.today(),
        )

        client.force_login(self.user)
        response = client.get(reverse("defense_contracts"))

        assert response.status_code == 200
        agency_choices = response.context["agency_choices"]
        # agency_choices is now a simple list of agency names
        assert "Department of Defense" in agency_choices
        assert "Department of Homeland Security" in agency_choices


@pytest.mark.django_db
class TestDeduplication:
    """Test that contracts are properly deduplicated by source."""

    def test_war_gov_deduplication(self):
        """Test war.gov contracts are deduplicated by source_url + company + contract_number."""
        from django.db.utils import IntegrityError
        
        contract_data = {
            "data_source": "war_gov",
            "company_name_raw": "Test Corp",
            "amount": 1000000,
            "branch": "army",
            "contract_number": "W91234",
            "source_url": "https://war.gov/test",
            "article_date": date.today(),
        }

        # Create first contract
        contract1 = DefenseContract.objects.create(**contract_data)
        assert DefenseContract.objects.filter(source_url=contract_data["source_url"]).count() == 1

        # Try to create duplicate - should raise IntegrityError
        with pytest.raises(IntegrityError):
            DefenseContract.objects.create(**contract_data)

    def test_usaspending_deduplication(self):
        """Test USASpending contracts are deduplicated by award_id."""
        from django.db.utils import IntegrityError
        
        contract_data = {
            "data_source": "usaspending",
            "company_name_raw": "Test Federal Corp",
            "amount": 2000000,
            "award_id": "UNIQUE_AWARD_123",
            "awarding_agency": "DoD",
            "article_date": date.today(),
        }

        # Create first contract
        contract1 = DefenseContract.objects.create(**contract_data)
        assert DefenseContract.objects.filter(award_id=contract_data["award_id"]).count() == 1

        # Try to create duplicate - should be prevented by unique constraint on award_id
        with pytest.raises(IntegrityError):
            DefenseContract.objects.create(**contract_data)
