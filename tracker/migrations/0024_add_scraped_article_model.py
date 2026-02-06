"""
Migration: Add ScrapedArticle model to track fetched war.gov article URLs.

Prevents redundant HTTP requests by recording which articles have already
been scraped. The force_refresh flag in scrape_latest() bypasses this check.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0023_add_defense_contract_model"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScrapedArticle",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "url",
                    models.URLField(
                        help_text="Full URL of the war.gov article page",
                        max_length=512,
                        unique=True,
                    ),
                ),
                (
                    "title",
                    models.CharField(
                        blank=True,
                        help_text="Article title (e.g., 'Contracts for Feb. 5, 2026')",
                        max_length=300,
                    ),
                ),
                (
                    "article_date",
                    models.DateField(
                        blank=True,
                        help_text="Parsed publication date of the article",
                        null=True,
                    ),
                ),
                (
                    "contracts_found",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Number of contracts parsed from this article",
                    ),
                ),
                (
                    "scraped_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When this article was last scraped",
                    ),
                ),
            ],
            options={
                "ordering": ["-article_date", "-scraped_at"],
                "indexes": [
                    models.Index(
                        fields=["article_date"],
                        name="tracker_scra_article_idx",
                    ),
                ],
            },
        ),
    ]
