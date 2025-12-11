import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from django.core.management.base import BaseCommand, CommandError

from gmail_auth import get_gmail_service
from tracker.models import Message


def load_ignore_labels() -> Set[str]:
    """Load ignore_labels from json/patterns.json, fallback to defaults if missing."""
    import json

    patterns_path = Path(__file__).resolve().parents[3] / "json" / "patterns.json"
    try:
        with open(patterns_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ignore = set(data.get("ignore_labels", ["noise", "head_hunter"]))
        return ignore
    except Exception:
        return {"noise", "head_hunter"}


class Command(BaseCommand):
    help = (
        "Compare Gmail messages under specific labels vs app-classified messages.\n"
        "Outputs counts and optional CSVs of differences for debugging."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--gmail-label-names",
            type=str,
            default=None,
            help="Comma-separated Gmail label names to include (e.g., 'Jobs,Applications')",
        )
        parser.add_argument(
            "--gmail-label-ids",
            type=str,
            default=None,
            help="Comma-separated Gmail label IDs to include (overrides names if provided)",
        )
        parser.add_argument(
            "--gmail-query",
            type=str,
            default=None,
            help="Gmail search query (e.g., 'from:jobs@example.com OR subject:(application)')",
        )
        parser.add_argument(
            "--export-dir",
            type=str,
            default=str(Path("logs") / "label_compare"),
            help="Directory to write CSV exports for differences",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of Gmail messages fetched (for quick tests)",
        )
        parser.add_argument(
            "--include-ignored",
            action="store_true",
            help="Include ignore_labels (noise/head_hunter) in app set",
        )
        parser.add_argument(
            "--only-stats",
            action="store_true",
            help="Print only counts/stats, skip CSV exports",
        )
        parser.add_argument(
            "--app-labels",
            type=str,
            default=None,
            help="Comma-separated app ml_label values to include (e.g., 'job_application,interview_invite')",
        )
        parser.add_argument(
            "--reviewed-only",
            action="store_true",
            help="Restrict app set to reviewed=True messages",
        )

    def handle(self, *args, **options):
        export_dir = Path(options["export_dir"]).resolve()
        export_dir.mkdir(parents=True, exist_ok=True)

        # Determine target Gmail labels and/or query
        label_ids: Set[str] = set()
        label_names_req = self._split_csv(options.get("gmail_label_names"))
        label_ids_req = self._split_csv(options.get("gmail_label_ids"))
        gmail_query = options.get("gmail_query")

        service = get_gmail_service()
        if service is None:
            raise CommandError("Failed to initialize Gmail service. Check credentials in json/ and token.")

        id_to_name, name_to_id = self._fetch_label_maps(service)

        if label_ids_req:
            label_ids.update(label_ids_req)
        elif label_names_req:
            for nm in label_names_req:
                if nm in name_to_id:
                    label_ids.add(name_to_id[nm])
                else:
                    self.stdout.write(self.style.WARNING(f"Label name not found in Gmail: {nm}"))
        elif not gmail_query:
            # No labels or query specified: show available labels and exit
            self._print_label_list(id_to_name)
            raise CommandError(
                "No Gmail labels or query specified. Use --gmail-query, --gmail-label-names, or --gmail-label-ids."
            )

        if label_ids:
            self.stdout.write(
                self.style.NOTICE(f"Using Gmail labels: {', '.join([id_to_name.get(i, i) for i in label_ids])}")
            )
        if gmail_query:
            self.stdout.write(self.style.NOTICE(f"Using Gmail query: {gmail_query}"))

        # Fetch Gmail message ids under those labels and/or query
        gmail_ids = self._list_message_ids(
            service,
            label_ids=list(label_ids) if label_ids else None,
            query=gmail_query,
            limit=options.get("limit"),
        )
        self.stdout.write(f"Fetched {len(gmail_ids)} Gmail message IDs for specified labels")

        # Build app set: messages with ml_label not in ignore_labels (unless include-ignored)
        ignore_labels = load_ignore_labels()
        app_qs = Message.objects.all().only("id", "msg_id", "subject", "ml_label", "reviewed")
        if not options.get("include_ignored"):
            app_qs = app_qs.exclude(ml_label__in=list(ignore_labels))
        app_labels_req = self._split_csv(options.get("app_labels"))
        if app_labels_req:
            app_qs = app_qs.filter(ml_label__in=app_labels_req)
        if options.get("reviewed_only"):
            app_qs = app_qs.filter(reviewed=True)

        app_ids = set(app_qs.values_list("msg_id", flat=True))
        self.stdout.write(
            f"Collected {len(app_ids)} app message IDs ({'including' if options.get('include_ignored') else 'excluding'} ignored labels)"
        )

        # Compute differences
        gmail_only = gmail_ids - app_ids
        app_only = app_ids - gmail_ids
        overlap = gmail_ids & app_ids

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Comparison Results:"))
        self.stdout.write(f"  Gmail set: {len(gmail_ids)}")
        self.stdout.write(f"  App set:   {len(app_ids)}")
        self.stdout.write(f"  Overlap:   {len(overlap)}")
        self.stdout.write(self.style.WARNING(f"  Gmail only (missed by app): {len(gmail_only)}"))
        self.stdout.write(self.style.WARNING(f"  App only (not labeled in Gmail): {len(app_only)}"))

        if options.get("only_stats"):
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        gmail_only_path = export_dir / f"gmail_only_{timestamp}.csv"
        app_only_path = export_dir / f"app_only_{timestamp}.csv"

        # Export gmail_only: include subject + labels from Gmail metadata
        self._export_csv_gmail_only(gmail_only_path, gmail_only, id_to_name, service)
        self.stdout.write(self.style.SUCCESS(f"Wrote {gmail_only_path}"))

        # Export app_only: include ml_label and subject from DB
        self._export_csv_app_only(app_only_path, app_qs, app_only)
        self.stdout.write(self.style.SUCCESS(f"Wrote {app_only_path}"))

        # Show a quick breakdown by ml_label for app_only
        label_counts: Dict[str, int] = {}
        for lbl in app_qs.filter(msg_id__in=list(app_only)).values_list("ml_label", flat=True):
            label_counts[lbl or "(none)"] = label_counts.get(lbl or "(none)", 0) + 1
        if label_counts:
            self.stdout.write("\nTop app-only labels:")
            for lbl, cnt in sorted(label_counts.items(), key=lambda x: x[1], reverse=True):
                self.stdout.write(f"  {lbl}: {cnt}")

        if app_labels_req:
            self.stdout.write(self.style.NOTICE(f"Filtering app set by labels: {', '.join(app_labels_req)}"))
        if options.get("reviewed_only"):
            self.stdout.write(self.style.NOTICE("Restricting app set to reviewed=True"))

    def _split_csv(self, value: Optional[str]) -> List[str]:
        if not value:
            return []
        return [v.strip() for v in value.split(",") if v.strip()]

    def _fetch_label_maps(self, service) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Return (id_to_name, name_to_id) maps from Gmail."""
        resp = service.users().labels().list(userId="me").execute()
        id_to_name: Dict[str, str] = {}
        name_to_id: Dict[str, str] = {}
        for lab in resp.get("labels", []):
            lab_id = lab.get("id")
            lab_name = lab.get("name")
            if lab_id and lab_name:
                id_to_name[lab_id] = lab_name
                name_to_id[lab_name] = lab_id
        return id_to_name, name_to_id

    def _print_label_list(self, id_to_name: Dict[str, str]):
        self.stdout.write("Available Gmail labels:")
        for lab_id, lab_name in sorted(id_to_name.items(), key=lambda x: x[1].lower()):
            self.stdout.write(f"  {lab_name}  (ID: {lab_id})")

    def _list_message_ids(
        self,
        service,
        label_ids: Optional[List[str]] = None,
        query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Set[str]:
        """List Gmail message IDs matching labelIds and/or query (Gmail semantics)."""
        user = "me"
        msg_ids: Set[str] = set()
        page_token = None
        fetched = 0
        while True:
            req = (
                service.users()
                .messages()
                .list(
                    userId=user,
                    labelIds=label_ids,
                    q=query,
                    pageToken=page_token,
                    maxResults=500,
                )
            )
            resp = req.execute()
            for m in resp.get("messages", []) or []:
                msg_ids.add(m.get("id"))
                fetched += 1
                if limit and fetched >= limit:
                    return msg_ids
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return msg_ids

    def _export_csv_gmail_only(self, path: Path, gmail_only_ids: Set[str], id_to_name: Dict[str, str], service) -> None:
        """Write CSV for Gmail-only messages (present in Gmail or query set but missing from app set).
        Columns: msg_id, thread_id, subject, gmail_labels (names)
        """
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["msg_id", "thread_id", "subject", "gmail_labels"])  # include subject for quick review
            user = "me"
            for mid in gmail_only_ids:
                try:
                    meta = (
                        service.users()
                        .messages()
                        .get(
                            userId=user,
                            id=mid,
                            format="metadata",
                            metadataHeaders=["Subject"],
                        )
                        .execute()
                    )
                    thread_id = meta.get("threadId", "")
                    labels = [id_to_name.get(lid, lid) for lid in meta.get("labelIds", [])]
                    # Extract Subject header if present
                    subject = ""
                    for h in meta.get("payload", {}).get("headers", []) or []:
                        if h.get("name") == "Subject":
                            subject = h.get("value", "")
                            break
                    w.writerow([mid, thread_id, subject, "; ".join(labels)])
                except Exception:
                    w.writerow([mid, "", "", ""])  # fallback

    def _export_csv_app_only(self, path: Path, app_qs, app_only_ids: Set[str]) -> None:
        """Write CSV for App-only messages (classified by app but not labeled in Gmail).
        Columns: msg_id, subject, ml_label
        """
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["msg_id", "subject", "ml_label"])  # minimal fields helpful for rule tweaks
            for row in app_qs.filter(msg_id__in=list(app_only_ids)).values_list("msg_id", "subject", "ml_label"):
                w.writerow(list(row))
