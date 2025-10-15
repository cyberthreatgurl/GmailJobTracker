# ingest_gmail.py

from django.core.management.base import BaseCommand
import os
import sys
from gmail_auth import get_gmail_service  # adjust if needed
from parser import ingest_message, parse_subject  # parse_subject now includes ML
import django
from tracker.models import IngestionStats
from datetime import datetime

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()


class Command(BaseCommand):
    help = 'Ingest Gmail messages and populate job applications'

    def handle(self, *args, **kwargs):
        try:
            service = get_gmail_service()
            
            stats, _ = IngestionStats.objects.get_or_create(date=datetime.today().date())
            
            # Fetch Gmail messages
            results = service.users().messages().list(
                userId='me',
                labelIds=['INBOX'],  # or use a custom label like 'JobApps'
                maxResults=1000
            ).execute()
            
            print(f" Fetching Gmail messages...")
            messages = results.get('messages', [])

            if not messages:
                self.stdout.write(self.style.WARNING("No Gmail messages found."))
                return

            for idx, msg in enumerate(messages, start=1):
                msg_id = msg['id']
                try:
                    # Fetch metadata first to inspect subject
                    msg_meta = service.users().messages().get(userId='me', id=msg_id, format='metadata', metadataHeaders=['Subject', 'From']).execute()
                    headers = {h['name']: h['value'] for h in msg_meta.get('payload', {}).get('headers', [])}
                    subject = headers.get('Subject', '')
                    sender = headers.get('From', '')
                    sender_domain = sender.split('@')[-1] if '@' in sender else None

                    parsed = parse_subject(subject, sender, sender_domain)
                    print(f" Processing message: {subject}")
                    
                    if parsed.get('ignore'):
                        self.stdout.write(f" Ignored: {subject}")
                        stats.total_fetched += 1
                        stats.save()
                        continue

                    ingest_message(service, msg_id)
                    stats.total_fetched += 1
                    stats.save()
                except Exception as e:
                    self.stderr.write(f" Failed to ingest {msg_id}: {e}")

            self.stdout.write(self.style.SUCCESS(
                f"📊 Stats for {stats.date}: Fetched={stats.total_fetched}, Inserted={stats.total_inserted}, Ignored={stats.total_ignored}"
))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f" Ingestion failed: {e}"))