"""
One-time script to backfill ScrapedArticle records from existing
DefenseContract.source_url values.
"""

import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import DefenseContract, ScrapedArticle  # noqa: E402


def main():
    urls = list(
        DefenseContract.objects
        .values_list("source_url", flat=True)
        .distinct()
    )
    # Deduplicate (distinct() returns per-value rows, not unique set)
    urls = list(set(urls))
    print(f"Found {len(urls)} distinct source URLs in DefenseContract table")

    for url in urls:
        contracts = DefenseContract.objects.filter(source_url=url)
        count = contracts.count()
        first = contracts.first()

        title = f"Contracts (backfilled from {count} contracts)"
        if first and first.article_date:
            title = f"Contracts for {first.article_date.strftime('%b. %-d, %Y')}"

        article_date = first.article_date if first else None

        obj, created = ScrapedArticle.objects.update_or_create(
            url=url,
            defaults={
                "title": title[:300],
                "article_date": article_date,
                "contracts_found": count,
            },
        )
        status = "CREATED" if created else "UPDATED"
        print(f"  {status}: {title} ({count} contracts) - {url}")

    print(f"\nScrapedArticle total: {ScrapedArticle.objects.count()}")


if __name__ == "__main__":
    main()
