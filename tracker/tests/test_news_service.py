"""
Test suite for news service and CompanyNews integration.

Tests cover:
- NewsArticle class instantiation and conversion
- NewsAggregator initialization and configuration
- Google News RSS feed fetching
- NewsAPI fallback fetching
- Article deduplication
- CompanyNews model functionality
- label_companies view integration
"""

import pytest
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from tracker.models import Company, CompanyNews
from tracker.services.news_service import NewsArticle, NewsAggregator


class NewsArticleTestCase(TestCase):
    """Tests for NewsArticle class."""

    def test_instantiation(self):
        """Test creating a NewsArticle."""
        article = NewsArticle(
            title="Test Article",
            url="https://example.com/article",
            date=timezone.now(),
            source="google_news",
            snippet="Test snippet"
        )
        assert article.title == "Test Article"
        assert article.url == "https://example.com/article"
        assert article.source == "google_news"

    def test_to_dict(self):
        """Test converting NewsArticle to dict."""
        now = timezone.now()
        article = NewsArticle(
            title="Test",
            url="https://example.com",
            date=now,
            source="google_news",
            snippet="Snippet"
        )
        article_dict = article.to_dict()
        assert article_dict["title"] == "Test"
        assert article_dict["url"] == "https://example.com"
        assert article_dict["source"] == "google_news"
        assert article_dict["snippet"] == "Snippet"

    def test_default_date(self):
        """Test that date defaults to now if not provided."""
        article = NewsArticle(
            title="Test",
            url="https://example.com",
            date=None,
            source="google_news"
        )
        assert article.date is not None


class NewsAggregatorTestCase(TestCase):
    """Tests for NewsAggregator class."""

    def test_initialization(self):
        """Test NewsAggregator initialization."""
        aggregator = NewsAggregator()
        assert aggregator.GOOGLE_NEWS_BASE_URL
        assert aggregator.NEWSAPI_BASE_URL
        assert aggregator.REQUEST_TIMEOUT == 10

    @patch('tracker.services.news_service.feedparser.parse')
    def test_google_news_fetch_success(self, mock_parse):
        """Test successful Google News RSS fetch."""
        # Mock feedparser response
        mock_feed = MagicMock()
        mock_entry = MagicMock()
        mock_entry.get = MagicMock(side_effect=lambda key, default='': {
            'title': 'Test Company wins major contract',
            'link': 'https://example.com/article',
            'summary': 'Test Company announced a major contract award.'
        }.get(key, default))
        mock_entry.published_parsed = timezone.now().timetuple()[:9]
        mock_feed.entries = [mock_entry]
        mock_parse.return_value = mock_feed

        aggregator = NewsAggregator()
        articles = aggregator._fetch_google_news_rss("Test Company", 30)

        assert len(articles) > 0
        assert articles[0].title == "Test Company wins major contract"
        assert articles[0].source == "google_news"

    @patch('tracker.services.news_service.requests.get')
    def test_newsapi_fetch_success(self, mock_get):
        """Test successful NewsAPI fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'status': 'ok',
            'articles': [
                {
                    'title': 'Test Article',
                    'url': 'https://example.com/article',
                    'description': 'Test description',
                    'publishedAt': '2024-12-01T10:00:00Z'
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        aggregator = NewsAggregator()
        aggregator.newsapi_key = 'test-key'
        articles = aggregator._fetch_newsapi("Test Company", 30)

        assert len(articles) > 0
        assert articles[0].title == "Test Article"
        assert articles[0].source == "newsapi"

    def test_deduplicate_articles(self):
        """Test article deduplication by URL."""
        articles = [
            NewsArticle("Article 1", "https://example.com/1", timezone.now(), "source1"),
            NewsArticle("Article 2", "https://example.com/2", timezone.now(), "source1"),
            NewsArticle("Article 1 Duplicate", "https://example.com/1", timezone.now(), "source2"),
        ]
        unique = NewsAggregator._deduplicate_articles(articles)
        assert len(unique) == 2
        assert unique[0].url == "https://example.com/1"


class CompanyNewsModelTestCase(TestCase):
    """Tests for CompanyNews model."""

    def setUp(self):
        """Set up test fixtures."""
        self.company = Company.objects.create(
            name="Test Company",
            domain="test.com",
            first_contact=timezone.now(),
            last_contact=timezone.now(),
        )

    def test_company_news_creation(self):
        """Test creating a CompanyNews record."""
        news = CompanyNews.objects.create(
            company=self.company,
            cache_duration_hours=24
        )
        assert news.company == self.company
        assert news.cache_duration_hours == 24
        assert news.articles == []

    def test_is_cache_fresh_no_fetch(self):
        """Test cache freshness when never fetched."""
        news = CompanyNews.objects.create(company=self.company)
        assert not news.is_cache_fresh()

    def test_is_cache_fresh_recent(self):
        """Test cache freshness when recently fetched."""
        news = CompanyNews.objects.create(
            company=self.company,
            last_fetched=timezone.now() - timedelta(hours=12),
            cache_duration_hours=24
        )
        assert news.is_cache_fresh()

    def test_is_cache_fresh_stale(self):
        """Test cache staleness."""
        news = CompanyNews.objects.create(
            company=self.company,
            last_fetched=timezone.now() - timedelta(hours=48),
            cache_duration_hours=24
        )
        assert not news.is_cache_fresh()

    def test_add_articles(self):
        """Test adding articles to CompanyNews."""
        news = CompanyNews.objects.create(company=self.company)
        articles = [
            {
                'title': 'Article 1',
                'url': 'https://example.com/1',
                'date': timezone.now().isoformat(),
                'source': 'google_news',
                'snippet': 'Snippet 1'
            }
        ]
        news.add_articles(articles)
        assert len(news.articles) == 1
        assert len(news.all_articles) == 1

    def test_get_display_articles_limit(self):
        """Test that display articles are limited to 5."""
        news = CompanyNews.objects.create(company=self.company)
        articles = [
            {
                'title': f'Article {i}',
                'url': f'https://example.com/{i}',
                'date': (timezone.now() - timedelta(days=i)).isoformat(),
                'source': 'google_news',
                'snippet': f'Snippet {i}'
            }
            for i in range(10)
        ]
        news.articles = articles
        display = news.get_display_articles()
        assert len(display) <= 5

    def test_get_all_articles(self):
        """Test retrieving all historical articles."""
        news = CompanyNews.objects.create(company=self.company)
        articles = [
            {
                'title': f'Article {i}',
                'url': f'https://example.com/{i}',
                'date': timezone.now().isoformat(),
                'source': 'google_news',
                'snippet': f'Snippet {i}'
            }
            for i in range(3)
        ]
        news.all_articles = articles
        all_articles = news.get_all_articles()
        assert len(all_articles) == 3


class LabelCompaniesViewNewsIntegrationTestCase(TestCase):
    """Tests for news integration in label_companies view."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass"
        )
        self.company = Company.objects.create(
            name="Test Company",
            domain="test.com",
            first_contact=timezone.now(),
            last_contact=timezone.now(),
        )
        self.client.login(username="testuser", password="testpass")

    @patch('tracker.services.news_service.NewsAggregator.get_news_for_company')
    def test_label_companies_fetches_news(self, mock_fetch):
        """Test that label_companies view fetches news for selected company."""
        mock_fetch.return_value = [
            NewsArticle("Article", "https://example.com", timezone.now(), "google_news")
        ]

        response = self.client.get(f'/label_companies/?company={self.company.id}')
        assert response.status_code == 200
        assert 'company_news' in response.context

    def test_label_companies_creates_news_record(self):
        """Test that label_companies renders without eagerly creating CompanyNews."""
        assert not CompanyNews.objects.filter(company=self.company).exists()

        response = self.client.get(f'/label_companies/?company={self.company.id}')

        assert response.status_code == 200
        assert 'company_news' in response.context
        assert response.context['company_news'] is None
        assert not CompanyNews.objects.filter(company=self.company).exists()

    def test_refresh_company_news_endpoint_success(self):
        """Test the refresh_company_news AJAX endpoint."""
        CompanyNews.objects.create(company=self.company)

        with patch('tracker.services.news_service.NewsAggregator.get_news_for_company') as mock_fetch:
            mock_fetch.return_value = [
                NewsArticle("New Article", "https://example.com", timezone.now(), "google_news")
            ]
            response = self.client.post(f'/company/{self.company.id}/refresh_news/')

        assert response.status_code == 200
        data = response.json()
        assert data['success']
        assert 'articles' in data

    def test_refresh_company_news_not_found(self):
        """Test refresh endpoint with invalid company."""
        response = self.client.post('/company/99999/refresh_news/')
        assert response.status_code == 404


@pytest.mark.django_db
class PyTestCompanyNewsTestCase:
    """Pytest-style tests for CompanyNews model."""

    def test_company_news_str(self):
        """Test CompanyNews string representation."""
        company = Company.objects.create(
            name="Test Corp",
            domain="test.com",
            first_contact=timezone.now(),
            last_contact=timezone.now(),
        )
        news = CompanyNews.objects.create(company=company)
        assert str(news) == f"News for {company.name}"

    def test_company_news_one_to_one_relationship(self):
        """Test one-to-one relationship between Company and CompanyNews."""
        company = Company.objects.create(
            name="Test Corp",
            domain="test.com",
            first_contact=timezone.now(),
            last_contact=timezone.now(),
        )
        news1 = CompanyNews.objects.create(company=company)
        # Accessing news through company
        assert company.news == news1


# Integration test for end-to-end news flow
@pytest.mark.django_db
class NewsIntegrationTestCase:
    """End-to-end integration tests."""

    def test_full_news_workflow(self):
        """Test complete workflow: create company → fetch news → update cache."""
        company = Company.objects.create(
            name="TechCorp",
            domain="techcorp.com",
            first_contact=timezone.now(),
            last_contact=timezone.now(),
        )

        # Create CompanyNews
        news, created = CompanyNews.objects.get_or_create(company=company)
        assert created

        # Simulate fetching articles
        articles = [
            NewsArticle("Tech News 1", "https://example.com/1", timezone.now(), "google_news"),
            NewsArticle("Tech News 2", "https://example.com/2", timezone.now(), "newsapi"),
        ]
        article_dicts = [a.to_dict() for a in articles]
        news.add_articles(article_dicts)
        news.last_fetched = timezone.now()
        news.save()

        # Verify articles are cached
        refreshed_news = CompanyNews.objects.get(company=company)
        assert len(refreshed_news.articles) == 2
        assert len(refreshed_news.all_articles) == 2
