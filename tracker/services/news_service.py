"""
News aggregation service for company research.

Supports multiple providers with fallback chain:
1. Primary: Google News RSS (free, no API key required)
2. Fallback: NewsAPI.org (requires API key)

Stores articles in database for historical tracking and analysis.
"""

import requests
import feedparser
from gnews import GNews
from datetime import datetime, timedelta
from typing import List, Optional
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
import logging
import re
from urllib.parse import quote_plus
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)


class NewsArticle:
    """Represents a single news article."""

    def __init__(
        self,
        title: str,
        url: str,
        date: Optional[datetime],
        source: str,
        snippet: str = ""
    ):
        """
        Initialize a news article.

        Args:
            title: Article headline
            url: Article URL
            date: Publication datetime
            source: Source provider name (google_news, newsapi, etc.)
            snippet: Article preview/description
        """
        self.title = title
        self.url = url
        self.date = date or timezone.now()
        self.source = source
        self.snippet = snippet

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "title": self.title,
            "url": self.url,
            "date": self.date.isoformat(),
            "date_display": self.date.strftime("%B %d, %Y"),
            "source": self.source,
            "snippet": self.snippet
        }

    def __repr__(self) -> str:
        return f"NewsArticle({self.title[:50]}... from {self.source})"


class NewsAggregator:
    """
    Fetch and aggregate news from multiple providers.

    Provider order:
    1. Google News RSS (free, reliable)
    2. NewsAPI.org (requires key, broader coverage)
    """

    # Configuration
    GOOGLE_NEWS_BASE_URL = "https://news.google.com/rss/search"
    NEWSAPI_BASE_URL = "https://newsapi.org/v2/everything"
    REQUEST_TIMEOUT = 10

    def __init__(self):
        """Initialize aggregator with configuration."""
        self.google_news_key = getattr(settings, 'GOOGLE_NEWS_API_KEY', None)
        self.newsapi_key = getattr(settings, 'NEWS_API_KEY', None)
        self.cache_timeout = 3600  # Cache for 1 hour
        self.gnews = GNews(
            language='en',
            country='US',
            max_results=25,
        )

    def get_news_for_company(
        self,
        company_name: str,
        num_articles: int = 5,
        days_back: int = 30,
        focus_area: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> List[NewsArticle]:
        """
        Fetch news for a company from configured providers.

        Tries Google News RSS first (free), falls back to NewsAPI.

        Args:
            company_name: Company name to search
            num_articles: Number of articles to return (default 5)
            days_back: Search window in days (default 30)

        Returns:
            List of NewsArticle objects, sorted by date (newest first)

        Raises:
            Exception: If all providers fail
        """
        cache_parts = [company_name or ""]
        if focus_area:
            cache_parts.append(focus_area)
        if domain:
            cache_parts.append(domain)
        safe_key = re.sub(r"[^a-zA-Z0-9:_-]", "_", "|".join(cache_parts))
        cache_key = f"news:{safe_key}"
        cached_articles = cache.get(cache_key)

        if cached_articles:
            logger.debug(f"Using cached news for {company_name}")
            return cached_articles

        articles = []
        errors = []

        # Try providers in order
        try:
            articles = self._fetch_gnews(
                company_name,
                days_back,
                focus_area=focus_area,
                domain=domain,
            )
            logger.info(
                f"GNews: Found {len(articles)} articles for {company_name}"
            )
        except Exception as e:
            errors.append(f"GNews: {str(e)}")
            logger.warning(f"GNews failed: {e}")

        # Fallback to Google News RSS
        if len(articles) < num_articles:
            try:
                rss_articles = self._fetch_google_news_rss(
                company_name,
                days_back,
                focus_area=focus_area,
                domain=domain,
            )
                articles.extend(rss_articles)
                logger.info(
                    f"Google News RSS: Found {len(rss_articles)} articles for {company_name}"
                )
            except Exception as e:
                errors.append(f"Google News RSS: {str(e)}")
                logger.warning(f"Google News RSS failed: {e}")

        # If Google News didn't return enough, try NewsAPI
        if len(articles) < num_articles and self.newsapi_key:
            try:
                newsapi_articles = self._fetch_newsapi(
                    company_name,
                    days_back,
                    focus_area=focus_area,
                    domain=domain,
                )
                logger.info(
                    f"NewsAPI: Found {len(newsapi_articles)} articles for "
                    f"{company_name}"
                )
                articles.extend(newsapi_articles)
            except Exception as e:
                errors.append(f"NewsAPI: {str(e)}")
                logger.warning(f"NewsAPI failed: {e}")

        if not articles and errors:
            error_msg = "; ".join(errors)
            logger.error(f"All news providers failed: {error_msg}")
            raise Exception(f"Failed to fetch news: {error_msg}")

        # Deduplicate, filter, and sort
        unique_articles = self._deduplicate_articles(articles)
        unique_articles = self._filter_relevant_articles(
            unique_articles,
            company_name=company_name,
            focus_area=focus_area,
            domain=domain,
        )
        unique_articles.sort(key=lambda a: a.date, reverse=True)

        # Cache results
        cache.set(cache_key, unique_articles, self.cache_timeout)

        return unique_articles[:num_articles]

    def _filter_relevant_articles(
        self,
        articles: List[NewsArticle],
        company_name: str,
        focus_area: Optional[str],
        domain: Optional[str],
    ) -> List[NewsArticle]:
        """Filter out obituary/sports/person-name noise and keep relevant hits."""
        if not articles:
            return []

        normalized_domain = self._normalize_domain(domain)
        company_tokens = [t for t in re.split(r"\W+", company_name.lower()) if t]
        focus_tokens = []
        if focus_area:
            focus_tokens = [
                t for t in re.split(r"\W+", focus_area.lower()) if t
            ]

        blocklist = [
            "obituary",
            "obituaries",
            "funeral",
            "memorial",
            "legacy.com",
            "sports",
            "football",
            "basketball",
            "baseball",
            "hockey",
            "soccer",
            "coach",
            "score",
            "scores",
            "high school",
        ]

        filtered = []
        for article in articles:
            text = f"{article.title} {article.snippet}".lower()

            if any(word in text for word in blocklist):
                continue

            if normalized_domain and normalized_domain in text:
                filtered.append(article)
                continue

            company_match = any(token in text for token in company_tokens)
            focus_match = any(token in text for token in focus_tokens)

            if focus_tokens:
                if company_match and focus_match:
                    filtered.append(article)
            else:
                if company_match:
                    filtered.append(article)

        return filtered

    def _fetch_google_news_rss(
        self,
        company_name: str,
        days_back: int,
        focus_area: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> List[NewsArticle]:
        """
        Fetch from Google News RSS feed (free, no API key needed).

        Args:
            company_name: Company to search
            days_back: Days to look back

        Returns:
            List of NewsArticle objects
        """
        queries = self._build_queries(company_name, focus_area, domain)

        try:
            articles = []
            cutoff = timezone.now() - timedelta(days=days_back)

            for query in queries:
                url = (
                    f"{self.GOOGLE_NEWS_BASE_URL}?"
                    f"q={quote_plus(query)}&ceid=US:en&hl=en&gl=US"
                )
                feed = feedparser.parse(url)

                for entry in feed.entries[:20]:  # Process up to 20 entries
                    try:
                        # Parse publication date
                        if hasattr(entry, 'published_parsed'):
                            pub_date = datetime(*entry.published_parsed[:6])
                            pub_date = timezone.make_aware(pub_date)
                        else:
                            pub_date = timezone.now()

                        # Skip if too old
                        if pub_date < cutoff:
                            continue

                        # Extract snippet from summary (remove HTML)
                        snippet = entry.get('summary', '')
                        snippet = re.sub(r'<[^>]+>', '', snippet)
                        snippet = snippet[:200]  # Limit length

                        article = NewsArticle(
                            title=entry.get('title', 'No title'),
                            url=entry.get('link', ''),
                            date=pub_date,
                            source="google_news",
                            snippet=snippet
                        )
                        articles.append(article)

                    except (KeyError, ValueError, TypeError) as e:
                        logger.debug(f"Skipped entry due to {e}")
                        continue

            return articles

        except Exception as e:
            logger.error(f"Google News RSS error: {e}")
            raise

    def _fetch_gnews(
        self,
        company_name: str,
        days_back: int,
        focus_area: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> List[NewsArticle]:
        """Fetch using gnews library (Google News RSS wrapper)."""
        queries = self._build_queries(company_name, focus_area, domain)
        cutoff = timezone.now() - timedelta(days=days_back)
        articles = []

        for query in queries:
            results = self.gnews.get_news(query)
            for item in results:
                try:
                    published = item.get("published date") or item.get("published_date")
                    if published:
                        pub_date = parsedate_to_datetime(published)
                        if timezone.is_naive(pub_date):
                            pub_date = timezone.make_aware(pub_date)
                    else:
                        pub_date = timezone.now()

                    if pub_date < cutoff:
                        continue

                    article = NewsArticle(
                        title=item.get("title") or "No title",
                        url=item.get("url") or "",
                        date=pub_date,
                        source="gnews",
                        snippet=(item.get("description") or "")[:200],
                    )
                    articles.append(article)
                except (TypeError, ValueError) as e:
                    logger.debug(f"Skipped gnews entry due to {e}")
                    continue

        return articles

    def _fetch_newsapi(
        self,
        company_name: str,
        days_back: int,
        focus_area: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> List[NewsArticle]:
        """
        Fetch from NewsAPI.org (requires API key).

        Args:
            company_name: Company to search
            days_back: Days to look back

        Returns:
            List of NewsArticle objects
        """
        if not self.newsapi_key:
            raise ValueError("NEWS_API_KEY not configured in .env")

        from_date = (
            (timezone.now() - timedelta(days=days_back)).date().isoformat()
        )

        params = {
            "q": self._build_queries(company_name, focus_area, domain)[0],
            "sortBy": "publishedAt",
            "language": "en",
            "from": from_date,
            "apiKey": self.newsapi_key,
            "pageSize": 15  # Fetch more to have options
        }

        try:
            response = requests.get(
                self.NEWSAPI_BASE_URL,
                params=params,
                timeout=self.REQUEST_TIMEOUT
            )
            response.raise_for_status()

            articles = []
            data = response.json()

            if data.get('status') != 'ok':
                raise ValueError(f"NewsAPI error: {data.get('message')}")

            for item in data.get('articles', []):
                try:
                    pub_date = datetime.fromisoformat(
                        item['publishedAt'].replace('Z', '+00:00')
                    )

                    article = NewsArticle(
                        title=item.get('title', 'No title'),
                        url=item.get('url', ''),
                        date=pub_date,
                        source="newsapi",
                        snippet=item.get('description', '')[:200]
                    )
                    articles.append(article)

                except (KeyError, ValueError) as e:
                    logger.debug(f"Skipped NewsAPI item: {e}")
                    continue

            return articles

        except requests.RequestException as e:
            logger.error(f"NewsAPI HTTP error: {e}")
            raise

    @staticmethod
    def _deduplicate_articles(
        articles: List[NewsArticle]
    ) -> List[NewsArticle]:
        """Remove duplicate articles by URL."""
        seen_urls = set()
        unique = []

        for article in articles:
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                unique.append(article)

        return unique

    @staticmethod
    def _normalize_domain(domain: Optional[str]) -> Optional[str]:
        """Normalize a domain string for search usage."""
        if not domain:
            return None
        cleaned = domain.strip().lower()
        cleaned = re.sub(r"^https?://", "", cleaned)
        cleaned = cleaned.split("/")[0]
        cleaned = cleaned.lstrip("www.")
        return cleaned or None

    def _build_queries(
        self,
        company_name: str,
        focus_area: Optional[str],
        domain: Optional[str],
    ) -> List[str]:
        """Build a list of targeted search queries using company + context.

        NOTE: Domain is intentionally ignored to avoid over-filtering.
        """
        base_exact = f'"{company_name}"'
        base_loose = company_name

        queries = []
        normalized_focus = self._normalize_focus_area(focus_area)
        normalized_domain = self._normalize_domain(domain)
        or_terms = []

        if normalized_focus:
            or_terms.append(f'"{normalized_focus}"')
        if normalized_domain:
            or_terms.append(f'"{normalized_domain}"')

        if or_terms:
            or_clause = f"({' OR '.join(or_terms)})"
            queries.append(f"{base_loose} AND {or_clause}")
            queries.append(f"{base_exact} {or_clause}")

        if normalized_focus:
            focus_exact = f'"{normalized_focus}"'
            queries.append(f"{base_exact} {focus_exact}")
            queries.append(f"{base_loose} {normalized_focus}")
        if normalized_domain:
            queries.append(f"{base_loose} {normalized_domain}")

        # Always include fallback queries (least restrictive last)
        queries.append(base_exact)
        queries.append(base_loose)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique.append(q)
        return unique

    @staticmethod
    def _normalize_focus_area(focus_area: Optional[str]) -> Optional[str]:
        """Normalize focus area to improve query results."""
        if not focus_area:
            return None
        cleaned = focus_area.strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip(" .;")
        return cleaned or None
