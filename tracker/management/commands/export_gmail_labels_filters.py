from django.core.management.base import BaseCommand
import os
import json
import datetime
from gmail_auth import get_gmail_service


class Command(BaseCommand):
    help = "Export all Gmail filters and labels to a JSON file in the /json folder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print and log all filters to console and a log file.",
        )

    def handle(self, *args, **options):
        service = get_gmail_service()
        if not service:
            self.stderr.write(
                "Failed to initialize Gmail service. Check OAuth credentials in json/."
            )
            return

        # Get root filter label from environment
        root_prefix = os.environ.get("GMAIL_ROOT_FILTER_LABEL", "#job-hunt")

        # Fetch labels
        labels_resp = service.users().labels().list(userId="me").execute()
        all_labels = labels_resp.get("labels", [])

        # Filter labels by prefix
        labels = [
            lab for lab in all_labels if lab.get("name", "").startswith(root_prefix)
        ]

        # Build label ID to name mapping (all labels for lookups)
        id_to_name = {lab.get("id"): lab.get("name") for lab in all_labels}

        # Get IDs of filtered labels
        filtered_label_ids = {lab.get("id") for lab in labels}

        # Fetch filters
        filters_resp = service.users().settings().filters().list(userId="me").execute()
        all_filters = filters_resp.get("filter", [])

        # Filter to only filters that apply our prefixed labels
        filters = []
        for filt in all_filters:
            action = filt.get("action", {})
            if action:
                add_ids = action.get("addLabelIds", [])
                # Only include if any of the addLabelIds match our prefix
                if any(lid in filtered_label_ids for lid in add_ids):
                    # Enrich with human-readable label names
                    action["addLabelNames"] = [
                        id_to_name.get(lid, lid) for lid in add_ids
                    ]
                    filters.append(filt)

        # Compose output
        out = {
            "labels": labels,
            "filters": filters,
            "exported_at": datetime.datetime.now().isoformat(),
        }
        out_path = os.path.join(
            "json",
            f"gmail_labels_filters_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.json",
        )
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        self.stdout.write(
            self.style.SUCCESS(f"Exported Gmail labels and filters to {out_path}")
        )

        if options.get("verbose"):
            log_path = os.path.join(
                "json",
                f"gmail_labels_filters_log_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.txt",
            )
            with open(log_path, "w", encoding="utf-8") as logf:
                logf.write(f"Exported at: {out['exported_at']}\n\n")
                logf.write("FILTERS:\n")
                for i, filt in enumerate(filters):
                    filt_str = json.dumps(filt, indent=2, ensure_ascii=False)
                    logf.write(f"--- Filter {i+1} ---\n{filt_str}\n\n")
                    self.stdout.write(f"--- Filter {i+1} ---\n{filt_str}\n")
            self.stdout.write(self.style.SUCCESS(f"Verbose log written to {log_path}"))
