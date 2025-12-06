# scripts/re_enrich_missing_companies.py
from tracker.enrichment import enrich_company
from tracker.models import Message

missing = Message.objects.filter(company__isnull=True)
for msg in missing:
    enrich_company(msg)
    msg.save()
print(f"Re-enriched {missing.count()} messages.")
