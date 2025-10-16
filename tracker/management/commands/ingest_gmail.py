# ingest_gmail.py

from django.core.management.base import BaseCommand
import os

from gmail_auth import get_gmail_service  # adjust if needed
from parser import ingest_message, parse_subject
from tracker.models import IngestionStats, ProcessedMessage
from django.db.models import Q
from datetime import datetime, timedelta


def fetch_all_messages(service, label_ids, max_results=500, after_date=None):
    """Fetch all pages of messages for given label IDs, optionally filtered by date."""
    all_msgs = []
    next_token = None

    # Build query with date filter
    query_parts = []
    if after_date:
        query_parts.append(f"after:{after_date.strftime('%Y/%m/%d')}")

    while True:
        kwargs = dict(userId="me", labelIds=label_ids, maxResults=max_results)
        if query_parts:
            kwargs["q"] = " ".join(query_parts)
        if next_token:
            kwargs["pageToken"] = next_token

        resp = service.users().messages().list(**kwargs).execute()
        all_msgs.extend(resp.get("messages", []))
        next_token = resp.get("nextPageToken")
        if not next_token:
            break
    return all_msgs


class Command(BaseCommand):
    help = "Ingest Gmail messages and populate job applications"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit-msg", type=str, help="Only ingest this single message ID"
        )
        parser.add_argument("--query", type=str, help="Custom Gmail search query")
        parser.add_argument(
            "--days-back",
            type=int,
            default=7,
            help="How many days back to fetch (default: 7)",
        )
        parser.add_argument(
            "--force", action="store_true", help="Re-process already seen messages"
        )

    def handle(self, *args, **options):
        try:
            service = get_gmail_service()
            stats, _ = IngestionStats.objects.get_or_create(
                date=datetime.today().date()
            )

            # Single message mode
            if options.get("limit_msg"):
                msg_id = options["limit_msg"]
                self.stdout.write(f"Ingesting single message: {msg_id}")
                try:
                    ingest_message(service, msg_id)
                    ProcessedMessage.objects.get_or_create(gmail_id=msg_id)
                    self.stdout.write(
                        self.style.SUCCESS(f"Successfully ingested {msg_id}")
                    )
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Failed: {e}"))
                return

            # Calculate date range
            days_back = options.get("days_back", 7)
            after_date = datetime.now() - timedelta(days=days_back)

            self.stdout.write(f"Fetching Gmail messages from last {days_back} days...")

            # Fetch with date filter
            inbox_msgs = fetch_all_messages(service, ["INBOX"], after_date=after_date)
            jobhunt_label = os.getenv(
                "GMAIL_JOBHUNT_LABEL_ID"
            )  # e.g., "Label_954880951792342706"
            jobhunt_msgs = (
                fetch_all_messages(service, [jobhunt_label], after_date=after_date)
                if jobhunt_label
                else []
            )

            all_msgs_by_id = {m["id"]: m for m in (inbox_msgs + jobhunt_msgs)}

            # Filter out already processed messages (unless --force)
            if not options.get("force"):
                processed_ids = set(
                    ProcessedMessage.objects.filter(
                        gmail_id__in=all_msgs_by_id.keys()
                    ).values_list("gmail_id", flat=True)
                )

                new_msgs = {
                    k: v for k, v in all_msgs_by_id.items() if k not in processed_ids
                }
                self.stdout.write(
                    f"Found {len(all_msgs_by_id)} messages, {len(new_msgs)} are new"
                )
                all_msgs_by_id = new_msgs

            if not all_msgs_by_id:
                self.stdout.write(self.style.WARNING("No new Gmail messages found."))
                return

            self.stdout.write(f"Processing {len(all_msgs_by_id)} messages...")

            fetched = inserted = ignored = 0

            for msg in all_msgs_by_id.values():
                msg_id = msg["id"]
                try:
                    msg_meta = (
                        service.users()
                        .messages()
                        .get(
                            userId="me",
                            id=msg_id,
                            format="full",  # or 'metadata' with snippet
                        )
                        .execute()
                    )
                    headers = {
                        h["name"]: h["value"]
                        for h in msg_meta.get("payload", {}).get("headers", [])
                    }
                    subject = headers.get("Subject", "") or ""
                    sender = headers.get("From", "") or ""
                    sender_domain = sender.split("@")[-1] if "@" in sender else None

                    parsed = parse_subject(
                        subject,
                        body="",
                        sender=sender,
                        sender_domain=sender_domain,
                    )
                    self.stdout.write(f"Processing: {subject}")

                    if parsed.get("ignore"):
                        ignored += 1
                        fetched += 1
                        ProcessedMessage.objects.get_or_create(
                            gmail_id=msg_id
                        )  # Mark as processed
                        continue

                    ret = ingest_message(service, msg_id)
                    fetched += 1

                    # Mark as processed
                    ProcessedMessage.objects.get_or_create(gmail_id=msg_id)

                    # Best-effort detection if an insert happened
                    inserted_flag = False
                    if isinstance(ret, bool):
                        inserted_flag = ret
                    elif isinstance(ret, int):
                        inserted_flag = ret > 0
                    elif isinstance(ret, dict):
                        inserted_flag = bool(
                            ret.get("inserted")
                            or ret.get("created")
                            or ret.get("saved")
                        )
                    else:
                        inserted_flag = True

                    if inserted_flag:
                        inserted += 1

                except Exception as e:
                    self.stderr.write(f"Failed to ingest {msg_id}: {e}")

            # Persist aggregated stats
            stats.total_fetched += fetched
            stats.total_inserted += inserted
            stats.total_ignored += ignored
            stats.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Stats for {stats.date}: Fetched={stats.total_fetched}, Inserted={stats.total_inserted}, Ignored={stats.total_ignored}"
                )
            )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Ingestion failed: {e}"))
