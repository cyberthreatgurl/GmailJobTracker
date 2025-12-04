"""Archive audit log files into `logs/archive/`.

This command is a safe dry-run by default. Use `--apply` to actually move files.

Behavior:
- By default it targets backup files created by the importer, e.g. files containing
  `.bak.` in the filename (e.g. `logs/clear_reviewed_audit.log.bak.20251203T...`).
- You can pass `--all` to archive any file that matches the source prefix.
- Use `--older-than DAYS` to only move files older than the given number of days.
- When applying, files are moved into `logs/archive/` (created if needed). Optionally
  pass `--compress` to gzip files after moving.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from django.core.management.base import BaseCommand


def _is_older_than(path: str, days: int) -> bool:
    if days <= 0:
        return True
    mtime = os.path.getmtime(path)
    cutoff = time.time() - (days * 86400)
    return mtime < cutoff


class Command(BaseCommand):
    help = "Archive audit log files to logs/archive/ (dry-run default)."

    def add_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument("--source", dest="source", default="logs/clear_reviewed_audit.log", help="Audit log prefix/file to archive")
        parser.add_argument("--archive-dir", dest="archive_dir", default="logs/archive", help="Directory to move archived files into")
        parser.add_argument("--apply", dest="apply", action="store_true", help="Actually move files (dry-run otherwise)")
        parser.add_argument("--older-than", dest="older_than", type=int, default=0, help="Only archive files older than N days (default: 0 -> any age)")
        parser.add_argument("--all", dest="all_files", action="store_true", help="Include the main audit file and any matching prefix files, not just backups")
        parser.add_argument("--compress", dest="compress", action="store_true", help="Gzip files after moving them into the archive")

    def handle(self, *args, **opts):
        source = opts.get("source")
        archive_dir = opts.get("archive_dir")
        apply_changes = bool(opts.get("apply"))
        older_than = int(opts.get("older_than") or 0)
        include_all = bool(opts.get("all_files"))
        compress = bool(opts.get("compress"))

        self.stdout.write(f"Scanning for audit files matching: {source}*")

        pattern = f"{source}*"
        candidates = glob.glob(pattern)
        # Exclude the archive directory itself if it appears in the glob
        candidates = [p for p in candidates if not Path(p).is_dir()]

        selected: List[str] = []
        for p in candidates:
            # Skip the active source file unless user asked for --all
            if not include_all and os.path.abspath(p) == os.path.abspath(source):
                continue

            # By default only pick backup files containing '.bak.' unless --all
            if not include_all and ".bak." not in os.path.basename(p):
                continue

            if _is_older_than(p, older_than):
                selected.append(p)

        if not selected:
            self.stdout.write("No files matched the archive criteria.")
            return

        self.stdout.write(f"Found {len(selected)} files to archive (older_than={older_than} days, include_all={include_all}).")

        for p in selected:
            self.stdout.write(f" - {p}")

        if not apply_changes:
            self.stdout.write("Dry-run: no files will be moved. Use --apply to perform the archival.")
            return

        # Ensure archive dir exists
        os.makedirs(archive_dir, exist_ok=True)

        moved = 0
        failed = 0

        for p in selected:
            try:
                dest = os.path.join(archive_dir, os.path.basename(p))
                # If dest exists, append timestamp
                if os.path.exists(dest):
                    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                    dest = f"{dest}.{ts}"

                shutil.move(p, dest)
                self.stdout.write(f"Moved: {p} -> {dest}")

                if compress:
                    gz_dest = f"{dest}.gz"
                    with open(dest, "rb") as f_in, gzip.open(gz_dest, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    os.remove(dest)
                    self.stdout.write(f"Compressed: {gz_dest}")

                moved += 1
            except Exception as e:
                failed += 1
                self.stderr.write(f"Failed to move {p}: {e}")

        self.stdout.write(f"Archive complete: moved={moved} failed={failed}")