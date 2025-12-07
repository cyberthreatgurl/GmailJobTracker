"""Django management command to initialize legacy database tables.

This command creates the legacy SQLite tables (email_text, applications, etc.)
that are not managed by Django migrations but are still used by the codebase.
"""

from django.core.management.base import BaseCommand

from db import init_db


class Command(BaseCommand):
    """Initialize legacy database schema (email_text, applications tables)."""

    help = "Initialize legacy database tables (email_text, applications, etc.)"

    def handle(self, *args, **options):
        """Execute the command."""
        self.stdout.write("Initializing legacy database schema...")
        init_db()
        self.stdout.write(
            self.style.SUCCESS("✅ Legacy database schema initialized successfully")
        )
        self.stdout.write(
            "Created tables: email_text, applications, follow_ups, meta"
        )
