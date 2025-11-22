# ingest_gmail.py

import os
from datetime import datetime, timedelta
from parser import ingest_message

from django.core.management.base import BaseCommand

from gmail_auth import get_gmail_service  # adjust if needed
from tracker.models import IngestionStats, ProcessedMessage
from tracker_logger import log_console


def fetch_all_messages(service, max_results=500, after_date=None, custom_query=None):
    """Fetch all pages of messages from entire Gmail account, optionally filtered by date and/or custom query."""
    all_msgs = []
    next_token = None

    # Build query with date filter and optional custom query
    query_parts = []
    if after_date:
        query_parts.append(f"after:{after_date.strftime('%Y/%m/%d')}")
    if custom_query:
        query_parts.append(custom_query)

    while True:
        kwargs = dict(userId="me", maxResults=max_results)
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
        parser.add_argument("--limit-msg", type=str, help="Only ingest this single message ID")
        parser.add_argument("--query", type=str, help="Custom Gmail search query")
        parser.add_argument(
            "--days-back",
            type=int,
            default=7,
            help="How many days back to fetch (default: 7)",
        )
        parser.add_argument("--force", action="store_true", help="Re-process already seen messages")
        parser.add_argument(
            "--reparse-all",
            action="store_true",
            help="Re-parse and re-ingest ALL messages, including already processed ones",
        )
        parser.add_argument(
            "--metrics-before",
            action="store_true",
            help="Print parsing/ML metrics before ingestion (calls report_parsing_metrics)",
        )
        parser.add_argument(
            "--metrics-after",
            action="store_true",
            help="Print parsing/ML metrics after ingestion (calls report_parsing_metrics)",
        )

    def handle(self, *args, **options):
        import subprocess
        import sys

        try:
            # Print metrics before if requested
            if options.get("metrics_before"):
                log_console("\n--- Parsing/ML Metrics BEFORE Ingestion ---\n")
                subprocess.run([sys.executable, "manage.py", "report_parsing_metrics"])
                log_console("\n--- End BEFORE Metrics ---\n")

            service = get_gmail_service()
            stats, _ = IngestionStats.objects.get_or_create(date=datetime.today().date())

            # Single message mode
            if options.get("limit_msg"):
                msg_id = options["limit_msg"]
                self.stdout.write(f"Ingesting single message: {msg_id}")
                try:
                    ingest_message(service, msg_id)
                    ProcessedMessage.objects.get_or_create(gmail_id=msg_id)
                    log_console(f"Successfully ingested {msg_id}")
                except Exception as e:
                    log_console(f"Failed: {e}")
                return

            # Calculate date range
            days_back = options.get("days_back", 7)
            after_date = datetime.now() - timedelta(days=days_back)
            custom_query = options.get("query")

            log_console(f"Fetching Gmail messages from last {days_back} days...")
            if custom_query:
                log_console(f"Using custom query: {custom_query}")

            # Fetch all messages from entire Gmail account (no label filtering)
            all_msgs = fetch_all_messages(service, after_date=after_date, custom_query=custom_query)
            
            all_msgs_by_id = {m["id"]: m for m in all_msgs}
            log_console(f"Total messages fetched: {len(all_msgs_by_id)}")

            # If --reparse-all, skip ProcessedMessage filtering and reprocess everything
            if options.get("reparse_all"):
                self.stdout.write(
                    self.style.WARNING("Re-parsing and re-ingesting ALL messages (ignoring ProcessedMessage table)!")
                )
            elif not options.get("force"):
                processed_ids = set(
                    ProcessedMessage.objects.filter(gmail_id__in=all_msgs_by_id.keys()).values_list(
                        "gmail_id", flat=True
                    )
                )
                new_msgs = {k: v for k, v in all_msgs_by_id.items() if k not in processed_ids}
                log_console(f"Found {len(all_msgs_by_id)} messages, {len(new_msgs)} are new")
                all_msgs_by_id = new_msgs

            if not all_msgs_by_id:
                log_console("No new Gmail messages found.")
                return

            log_console(f"Processing {len(all_msgs_by_id)} messages...")

            fetched = inserted = ignored = 0

            for msg in all_msgs_by_id.values():
                msg_id = msg["id"]
                try:
                    # Get basic metadata for logging
                    msg_meta = (
                        service.users()
                        .messages()
                        .get(
                            userId="me",
                            id=msg_id,
                            format="metadata",
                            metadataHeaders=["Subject", "From", "Date"],
                        )
                        .execute()
                    )
                    headers = {h["name"]: h["value"] for h in msg_meta.get("payload", {}).get("headers", [])}
                    subject = headers.get("Subject", "") or ""
                    date = headers.get("Date", "") or ""

                    # Log before processing
                    log_console(f"Processing {date}: {subject}")

                    # Let ingest_message handle full classification with body
                    ret = ingest_message(service, msg_id)
                    fetched += 1

                    # Mark as processed
                    ProcessedMessage.objects.get_or_create(gmail_id=msg_id)

                    # Track if message was inserted or ignored
                    # ingest_message returns "ignored" if the message was ignored
                    if ret == "ignored":
                        ignored += 1
                    else:
                        # Best-effort detection if an insert happened
                        inserted_flag = False
                        if isinstance(ret, bool):
                            inserted_flag = ret
                        elif isinstance(ret, int):
                            inserted_flag = ret > 0
                        elif isinstance(ret, dict):
                            inserted_flag = bool(ret.get("inserted") or ret.get("created") or ret.get("saved"))
                        else:
                            inserted_flag = True

                        if inserted_flag:
                            inserted += 1

                except Exception as e:
                    log_console(f"Failed to ingest {msg_id}: {e}")

            # Persist aggregated stats
            stats.total_fetched += fetched
            stats.total_inserted += inserted
            stats.total_ignored += ignored
            stats.save()

            log_console(
                f"Stats for {stats.date}: Fetched={stats.total_fetched}, Inserted={stats.total_inserted}, Ignored={stats.total_ignored}"
            )

            # Print metrics after if requested
            if options.get("metrics_after"):
                log_console("\n--- Parsing/ML Metrics AFTER Ingestion ---\n")
                subprocess.run([sys.executable, "manage.py", "report_parsing_metrics"])
                log_console("\n--- End AFTER Metrics ---\n")
        except Exception as e:
            log_console(f"Ingestion failed: {e}")
