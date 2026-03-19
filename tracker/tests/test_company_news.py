"""
Test suite for news service and CompanyNews integration.

Tests cover:
- NewsArticle class instantiation and conversion
- NewsAggregator initialization and configuration
- CompanyNews model functionality
- label_companies view integration with news
"""

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
        self.assertEqual(article.title, "Test Article")
        self.assertEqual(article.url, "https://example.com/article")
        self.assertEqual(article.source, "google_news")

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
        self.assertEqual(article_dict["title"], "Test")
        self.assertEqual(article_dict["url"], "https://example.com")
        self.assertEqual(article_dict["source"], "google_news")
        self.assertEqual(article_dict["snippet"], "Snippet")

    def test_default_date(self):
        """Test that date defaults to now if not provided."""
        article = NewsArticle(
            title="Test",
            url="https://example.com",
            date=None,
            source="google_news"
        )
        self.assertIsNotNone(article.date)


class NewsAggregatorTestCase(TestCase):
    """Tests for NewsAggregator class."""

    def test_initialization(self):
        """Test NewsAggregator initialization."""
        aggregator = NewsAggregator()
        self.assertIsNotNone(aggregator.GOOGLE_NEWS_BASE_URL)
        self.assertIsNotNone(aggregator.NEWSAPI_BASE_URL)
        self.assertEqual(aggregator.REQUEST_TIMEOUT, 10)

    def test_deduplicate_articles(self):
        """Test article deduplication by URL."""
        articles = [
            NewsArticle("Article 1", "https://example.com/1", timezone.now(), "source1"),
            NewsArticle("Article 2", "https://example.com/2", timezone.now(), "source1"),
            NewsArticle("Article 1 Duplicate", "https://example.com/1", timezone.now(), "source2"),
        ]
        unique = NewsAggregator._deduplicate_articles(articles)
        self.assertEqual(len(unique), 2)
        self.assertEqual(unique[0].url, "https://example.com/1")


class CompanyNewsModelTestCase(TestCase):
    """Tests for CompanyNews model."""

    def setUp(self):
        """Set up test fixtures."""
        self.company = Company.objects.create(
            name="Test Company",
            domain="test.com",
            first_contact=timezone.now(),
            last_contact=timezone.now()
        )

    def test_company_news_creation(self):
        """Test creating a CompanyNews record."""
        news = CompanyNews.objects.create(
            company=self.company,
            cache_duration_hours=24
        )
        self.assertEqual(news.company, self.company)
        self.assertEqual(news.cache_duration_hours, 24)
        self.assertEqual(news.articles, [])

    def test_is_cache_fresh_no_fetch(self):
        """Test cache freshness when never fetched."""
        news = CompanyNews.objects.create(company=self.company)
        self.assertFalse(news.is_cache_fresh())

    def test_is_cache_fresh_recent(self):
        """Test cache freshness when recently fetched."""
        news = CompanyNews.objects.create(
            company=self.company,
            last_fetched=timezone.now() - timedelta(hours=12),
            cache_duration_hours=24
        )
        self.assertTrue(news.is_cache_fresh())

    def test_is_cache_fresh_stale(self):
        """Test cache staleness."""
        news = CompanyNews.objects.create(
            company=self.company,
            last_fetched=timezone.now() - timedelta(hours=48),
            cache_duration_hours=24
        )
        self.assertFalse(news.is_cache_fresh())

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
        self.assertEqual(len(news.articles), 1)
        self.assertEqual(len(news.all_articles), 1)

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
        self.assertLessEqual(len(display), 5)

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
        self.assertEqual(len(all_articles), 3)

    def test_company_news_str(self):
        """Test CompanyNews string representation."""
        news = CompanyNews.objects.create(company=self.company)
        self.assertEqual(str(news), f"News for {self.company.name}")


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
            last_contact=timezone.now()
        )
        self.client.login(username="testuser", password="testpass")

    def test_label_companies_renders_without_creating_news_record(self):
        """Test that label_companies renders news context without eager CompanyNews creation."""
        self.assertFalse(
            CompanyNews.objects.filter(company=self.company).exists()
        )

        response = self.client.get(f'/label_companies/?company={self.company.id}')

        self.assertEqual(response.status_code, 200)
        self.assertIn('company_news', response.context)
        self.assertIsNone(response.context['company_news'])
        self.assertFalse(
            CompanyNews.objects.filter(company=self.company).exists()
        )

    def test_refresh_company_news_endpoint_not_found(self):
        """Test refresh endpoint with invalid company."""
        response = self.client.post('/company/99999/refresh_news/')
        self.assertEqual(response.status_code, 404)

    def test_refresh_company_news_requires_post(self):
        """Test that refresh endpoint requires POST method."""
        response = self.client.get(f'/company/{self.company.id}/refresh_news/')
        self.assertEqual(response.status_code, 400)
