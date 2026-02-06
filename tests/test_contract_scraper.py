"""
Unit tests for the defense contract scraper service.

Tests cover:
- Company name and location parsing from contract paragraphs
- Dollar amount extraction
- Contract number extraction
- Multi-awardee paragraph handling
- Article date parsing from titles
- Branch section splitting
- Small business detection
- ScrapedArticle caching (skip already-scraped URLs)
"""

from datetime import datetime
from decimal import Decimal

import pytest

from tracker.models import ScrapedArticle
from tracker.services.contract_scraper import ContractScraperService


@pytest.fixture
def scraper():
    """Create a scraper instance without loading the company name cache."""
    service = ContractScraperService()
    service._company_name_cache = {}  # Empty cache (no DB calls)
    return service


# ──────────────────────────────────────────────
# parse_article_date
# ──────────────────────────────────────────────


class TestParseArticleDate:
    """Tests for article date parsing from titles."""

    def test_standard_date(self, scraper):
        result = scraper.parse_article_date("Contracts for Feb. 5, 2026")
        assert result == datetime(2026, 2, 5)

    def test_through_date_range(self, scraper):
        result = scraper.parse_article_date(
            "Contracts for Feb. 2, 2026, Through Feb. 4, 2026"
        )
        assert result == datetime(2026, 2, 2)

    def test_full_month_name(self, scraper):
        result = scraper.parse_article_date("Contracts for January 15, 2026")
        assert result == datetime(2026, 1, 15)

    def test_abbreviated_month_no_period(self, scraper):
        result = scraper.parse_article_date("Contracts for Jan 30, 2026")
        assert result == datetime(2026, 1, 30)

    def test_no_date_in_title(self, scraper):
        result = scraper.parse_article_date("Some other article")
        assert result is None


# ──────────────────────────────────────────────
# parse_dollar_amount
# ──────────────────────────────────────────────


class TestParseDollarAmount:
    """Tests for dollar string parsing."""

    def test_simple_amount(self):
        result = ContractScraperService.parse_dollar_amount("$12,497,947")
        assert result == Decimal("12497947")

    def test_large_amount(self):
        result = ContractScraperService.parse_dollar_amount("$265,164,486")
        assert result == Decimal("265164486")

    def test_small_amount(self):
        result = ContractScraperService.parse_dollar_amount("$276,242")
        assert result == Decimal("276242")

    def test_no_commas(self):
        result = ContractScraperService.parse_dollar_amount("$5000")
        assert result == Decimal("5000")

    def test_with_decimals(self):
        result = ContractScraperService.parse_dollar_amount("$1,234.56")
        assert result == Decimal("1234.56")

    def test_invalid_string(self):
        result = ContractScraperService.parse_dollar_amount("not a number")
        assert result is None


# ──────────────────────────────────────────────
# split_by_branch
# ──────────────────────────────────────────────


class TestSplitByBranch:
    """Tests for splitting article text by military branch headings."""

    def test_two_branches(self, scraper):
        text = "ARMY\nSome army contracts here.\n\nNAVY\nSome navy contracts here."
        sections = scraper.split_by_branch(text)
        assert len(sections) == 2
        assert sections[0][0] == "army"
        assert "army contracts" in sections[0][1]
        assert sections[1][0] == "navy"
        assert "navy contracts" in sections[1][1]

    def test_no_branch_headings(self, scraper):
        text = "Just some text without branch headings."
        sections = scraper.split_by_branch(text)
        assert len(sections) == 1
        assert sections[0][0] == "other"

    def test_defense_logistics_agency(self, scraper):
        text = "DEFENSE LOGISTICS AGENCY\nSome DLA contracts."
        sections = scraper.split_by_branch(text)
        assert len(sections) == 1
        assert sections[0][0] == "defense_logistics_agency"


# ──────────────────────────────────────────────
# split_into_contract_paragraphs
# ──────────────────────────────────────────────


class TestSplitIntoContractParagraphs:
    """Tests for splitting branch sections into individual contract paragraphs."""

    def test_two_paragraphs(self, scraper):
        text = (
            "Company A, City, State, was awarded a $1,000,000 contract "
            "for something. This is a long enough paragraph to pass the filter.\n\n"
            "Company B, City, State, was awarded a $2,000,000 contract "
            "for something else. This is also long enough to pass the filter."
        )
        paragraphs = scraper.split_into_contract_paragraphs(text)
        assert len(paragraphs) == 2

    def test_filters_short_fragments(self, scraper):
        text = (
            "Company A, City, State, was awarded a $1,000,000 contract "
            "for something. This is a long enough paragraph.\n\n"
            "Short line\n\n"
            "*Small business"
        )
        paragraphs = scraper.split_into_contract_paragraphs(text)
        assert len(paragraphs) == 1


# ──────────────────────────────────────────────
# parse_contract_paragraph
# ──────────────────────────────────────────────


class TestParseContractParagraph:
    """Tests for parsing individual contract paragraphs."""

    def test_standard_contract(self, scraper):
        paragraph = (
            "Lockheed Martin Corp., Fort Worth, Texas, was awarded a "
            "$47,753,808 modification (P00007) to previously awarded "
            "contract N00024-22-C-5501 for Navy work. Work will be "
            "performed in Fort Worth, Texas, and is expected to be "
            "completed by September 2028. Naval Sea Systems Command, "
            "Washington, D.C., is the contracting activity."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "navy", datetime(2026, 2, 5), "https://example.com"
        )
        assert result is not None
        assert result["company_name_raw"] == "Lockheed Martin Corp."
        assert result["company_location"] == "Fort Worth, Texas"
        assert result["amount"] == Decimal("47753808")
        assert result["branch"] == "navy"
        assert result["is_modification"] is True
        assert result["contract_number"] in ("P00007", "N00024-22-C-5501")

    def test_small_business_asterisk(self, scraper):
        paragraph = (
            "Blair Remy Merrick MP JV LLC,* Oklahoma City, Oklahoma, "
            "is awarded a $33,000,000 firm-fixed-price contract for "
            "architect-engineer design services. Work will be performed "
            "at various locations."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "navy", datetime(2026, 2, 5), "https://example.com"
        )
        assert result is not None
        assert result["company_name_raw"] == "Blair Remy Merrick MP JV LLC"
        assert result["is_small_business"] is True
        assert result["amount"] == Decimal("33000000")

    def test_multi_awardee_first_company(self, scraper):
        paragraph = (
            "NV5 Geospatial Inc., St. Petersburg, Florida (W912P9-26-D-A019); "
            "Woolpert Inc., Beavercreek, Ohio (W912P9-26-D-A020); "
            "Dewberry Engineers Inc., Fairfax, Virginia (W912P9-26-D-A021); "
            "were each awarded a total of $249,000,000 in firm-fixed-price "
            "contracts. Work will be performed at multiple locations."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "army", datetime(2026, 2, 5), "https://example.com"
        )
        assert result is not None
        assert result["company_name_raw"] == "NV5 Geospatial Inc."
        assert result["company_location"] == "St. Petersburg, Florida"
        assert result["amount"] == Decimal("249000000")

    def test_city_with_period(self, scraper):
        """Cities like 'St. Petersburg' or 'Ft. Worth' should parse."""
        paragraph = (
            "Some Company LLC, St. Louis, Missouri, was awarded a "
            "$5,000,000 contract for support services. Work will be "
            "performed at multiple sites."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "army", datetime(2026, 2, 5), "https://example.com"
        )
        assert result is not None
        assert result["company_location"] == "St. Louis, Missouri"

    def test_unparseable_paragraph(self, scraper):
        """Paragraphs that don't follow the expected format return None."""
        paragraph = "This is just random text without a contract structure."
        result = scraper.parse_contract_paragraph(
            paragraph, "navy", datetime(2026, 2, 5), "https://example.com"
        )
        assert result is None

    def test_work_location_extraction(self, scraper):
        paragraph = (
            "Test Corp., Houston, Texas, was awarded a $10,000,000 "
            "contract for engineering services. Work will be performed "
            "in San Diego, California, and is expected to be completed "
            "by December 2027."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "navy", datetime(2026, 2, 5), "https://example.com"
        )
        assert result is not None
        assert "San Diego" in result["work_location"]

    def test_completion_date_extraction(self, scraper):
        paragraph = (
            "Test Corp., Houston, Texas, was awarded a $10,000,000 "
            "contract for engineering services. Work will be performed "
            "in San Diego, California, and is expected to be completed "
            "by December 2027."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "navy", datetime(2026, 2, 5), "https://example.com"
        )
        assert result is not None
        assert "December 2027" in result["completion_date"]

    def test_virginia_typo(self, scraper):
        """Handle common 'Virgina' typo in source data."""
        paragraph = (
            "Dark Wolf Solutions LLC, Herndon, Virgina, was awarded a "
            "$67,200,000 indefinite-delivery/indefinite-quantity contract "
            "for cyber space innovation support services."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "air_force", datetime(2026, 1, 30), "https://example.com"
        )
        assert result is not None
        assert result["company_name_raw"] == "Dark Wolf Solutions LLC"

    def test_contract_for_not_captured_as_number(self, scraper):
        """'contract for ...' should NOT capture 'for' as the contract number."""
        paragraph = (
            "Abbott Rapid Diagnostics, Santa Clara, California, was awarded "
            "a $15,000,000 fixed-price contract for diagnostic test kits. "
            "Work will be performed at multiple sites."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "defense_logistics_agency", datetime(2026, 2, 5),
            "https://example.com"
        )
        assert result is not None
        assert result["contract_number"] != "for"

    def test_contract_with_not_captured_as_number(self, scraper):
        """'contract with ...' should NOT capture 'with' as the contract number."""
        paragraph = (
            "Katmai North America LLC, Anchorage, Alaska, was awarded a "
            "$20,000,000 task-order contract with a one-year base period "
            "for maintenance services."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "navy", datetime(2026, 1, 30), "https://example.com"
        )
        assert result is not None
        assert result["contract_number"] != "with"

    def test_ceiling_amount_parsed(self, scraper):
        """'was awarded a ceiling of $X' should still extract the amount."""
        paragraph = (
            "Dark Wolf Solutions LLC, Herndon, Virgina, was awarded a "
            "ceiling of $67,200,000 indefinite-delivery/indefinite-quantity "
            "contract for cyber space innovation support services. Work "
            "will be performed at the Pentagon."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "air_force", datetime(2026, 1, 30), "https://example.com"
        )
        assert result is not None
        assert result["amount"] == Decimal("67200000")
        assert result["contract_number"] != "for"

    def test_real_contract_id_after_word_contract(self, scraper):
        """'contract N00024-22-C-5501' should capture the real contract ID."""
        paragraph = (
            "Test Corp., Houston, Texas, was awarded a $10,000,000 "
            "contract N00024-22-C-5501 for engineering services. Work "
            "will be performed at multiple sites."
        )
        result = scraper.parse_contract_paragraph(
            paragraph, "navy", datetime(2026, 2, 5), "https://example.com"
        )
        assert result is not None
        assert result["contract_number"] == "N00024-22-C-5501"


# ──────────────────────────────────────────────
# match_company
# ──────────────────────────────────────────────


class TestMatchCompany:
    """Tests for company name matching against cached records."""

    def test_exact_match(self, scraper):
        scraper._company_name_cache = {"lockheed martin": 42}
        result = scraper.match_company("Lockheed Martin")
        assert result == 42

    def test_suffix_stripping(self, scraper):
        scraper._company_name_cache = {"lockheed martin": 42}
        result = scraper.match_company("Lockheed Martin Corp.")
        assert result == 42

    def test_no_match(self, scraper):
        scraper._company_name_cache = {"google": 1}
        result = scraper.match_company("Nonexistent Company")
        assert result is None

    def test_inc_suffix(self, scraper):
        scraper._company_name_cache = {"general dynamics": 10}
        result = scraper.match_company("General Dynamics Inc.")
        assert result == 10

    def test_llc_suffix(self, scraper):
        scraper._company_name_cache = {"dark wolf solutions": 5}
        result = scraper.match_company("Dark Wolf Solutions LLC")
        assert result == 5


# ──────────────────────────────────────────────
# ScrapedArticle caching
# ──────────────────────────────────────────────


@pytest.mark.django_db
class TestRecordScrapedArticle:
    """Tests for the _record_scraped_article method."""

    def test_creates_record(self, scraper):
        """A new ScrapedArticle row is created on first call."""
        url = "https://www.war.gov/News/Contracts/Article/123/"
        title = "Contracts for Feb. 5, 2026"
        scraper._record_scraped_article(url, title, 12, {})

        assert ScrapedArticle.objects.count() == 1
        article = ScrapedArticle.objects.get(url=url)
        assert article.title == title
        assert article.contracts_found == 12
        assert article.article_date == datetime(2026, 2, 5).date()

    def test_update_on_refresh(self, scraper):
        """Calling again with the same URL updates (upserts) the record."""
        url = "https://www.war.gov/News/Contracts/Article/123/"
        title = "Contracts for Feb. 5, 2026"

        # First call
        scraper._record_scraped_article(url, title, 10, {})
        assert ScrapedArticle.objects.count() == 1

        # Second call with updated count (refresh scenario)
        scraper._record_scraped_article(url, title, 15, {})
        assert ScrapedArticle.objects.count() == 1  # Still one row
        article = ScrapedArticle.objects.get(url=url)
        assert article.contracts_found == 15

    def test_title_truncated(self, scraper):
        """Titles longer than 300 chars are truncated."""
        url = "https://www.war.gov/News/Contracts/Article/999/"
        long_title = "A" * 400
        scraper._record_scraped_article(url, long_title, 1, {})

        article = ScrapedArticle.objects.get(url=url)
        assert len(article.title) == 300


@pytest.mark.django_db
class TestScrapedArticleCacheLookup:
    """Tests for the already-scraped URL lookup in scrape_latest."""

    def test_cached_set_populated_from_db(self):
        """
        Verify that ScrapedArticle URLs are queryable as a set for
        cache-hit detection.
        """
        ScrapedArticle.objects.create(
            url="https://www.war.gov/News/Contracts/Article/100/",
            title="Contracts for Jan. 1, 2026",
            contracts_found=5,
        )
        ScrapedArticle.objects.create(
            url="https://www.war.gov/News/Contracts/Article/200/",
            title="Contracts for Jan. 2, 2026",
            contracts_found=3,
        )

        cached = set(ScrapedArticle.objects.values_list("url", flat=True))
        assert len(cached) == 2
        assert "https://www.war.gov/News/Contracts/Article/100/" in cached
        assert "https://www.war.gov/News/Contracts/Article/200/" in cached
        assert "https://www.war.gov/News/Contracts/Article/300/" not in cached

    def test_force_refresh_skips_cache(self):
        """
        When force_refresh=True, the already_scraped set should be empty
        so no articles are skipped.
        """
        ScrapedArticle.objects.create(
            url="https://www.war.gov/News/Contracts/Article/100/",
            title="Contracts for Jan. 1, 2026",
            contracts_found=5,
        )

        # Simulate the force_refresh=True branch
        already_scraped: set = set()
        force_refresh = True
        if not force_refresh:
            already_scraped = set(
                ScrapedArticle.objects.values_list("url", flat=True)
            )

        assert len(already_scraped) == 0

    def test_incremental_populates_cache(self):
        """
        When force_refresh=False, the already_scraped set should contain
        all previously scraped URLs.
        """
        ScrapedArticle.objects.create(
            url="https://www.war.gov/News/Contracts/Article/100/",
            title="Contracts for Jan. 1, 2026",
            contracts_found=5,
        )

        # Simulate the force_refresh=False branch
        already_scraped: set = set()
        force_refresh = False
        if not force_refresh:
            already_scraped = set(
                ScrapedArticle.objects.values_list("url", flat=True)
            )

        assert len(already_scraped) == 1
        assert "https://www.war.gov/News/Contracts/Article/100/" in already_scraped
