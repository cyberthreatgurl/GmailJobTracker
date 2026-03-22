"""Merge leftover SQLite runtime data into PostgreSQL and optionally archive the SQLite file."""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tracker.models import ModelTrainingLabelMetric, ModelTrainingRun


class Command(BaseCommand):
    help = (
        "Merge SQLite-only runtime data into the configured PostgreSQL database and "
        "optionally archive the SQLite file."
    )

    supported_tables = {
        "auth_user",
        "django_session",
        "tracker_modeltrainingrun",
        "tracker_modeltraininglabelmetric",
    }
    ignorable_tables = {
        "auth_permission",
        "django_content_type",
        "django_migrations",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--sqlite-path",
            default=str(Path(settings.BASE_DIR) / "db" / "job_tracker.db"),
            help="Path to the SQLite database file to merge.",
        )
        parser.add_argument(
            "--archive",
            action="store_true",
            help="Rename the SQLite file to a timestamped .archived copy after a successful merge.",
        )

    def handle(self, *args, **options):
        db_engine = settings.DATABASES["default"].get("ENGINE", "")
        if "postgresql" not in db_engine and "postgres" not in db_engine:
            raise CommandError("This command must be run with PostgreSQL configured as the default database.")

        sqlite_path = Path(options["sqlite_path"]).expanduser().resolve()
        if not sqlite_path.exists():
            raise CommandError(f"SQLite database not found: {sqlite_path}")

        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
        try:
            table_counts = self._get_non_empty_table_counts(sqlite_conn)
            if not table_counts:
                self.stdout.write(self.style.WARNING(f"No SQLite rows found in {sqlite_path}"))
                return

            unsupported = [
                table
                for table in table_counts
                if table not in self.supported_tables and table not in self.ignorable_tables
            ]
            if unsupported:
                raise CommandError(
                    "SQLite contains non-empty unsupported tables: " + ", ".join(sorted(unsupported))
                )

            summary = {
                "users_created": 0,
                "users_skipped": 0,
                "sessions_created": 0,
                "sessions_skipped": 0,
                "runs_created": 0,
                "runs_skipped": 0,
                "metrics_created": 0,
                "metrics_skipped": 0,
            }

            with transaction.atomic():
                self._merge_users(sqlite_conn, summary)
                self._merge_sessions(sqlite_conn, summary)
                run_map = self._merge_training_runs(sqlite_conn, summary)
                self._merge_training_metrics(sqlite_conn, run_map, summary)

            if options["archive"]:
                archived_path = sqlite_path.with_name(
                    f"{sqlite_path.stem}.archived-{datetime.now().strftime('%Y%m%d%H%M%S')}{sqlite_path.suffix}"
                )
                shutil.move(str(sqlite_path), str(archived_path))
                self.stdout.write(self.style.SUCCESS(f"Archived SQLite database to {archived_path}"))

            for key, value in summary.items():
                self.stdout.write(f"{key}: {value}")
        finally:
            sqlite_conn.close()

    def _get_non_empty_table_counts(self, sqlite_conn):
        cursor = sqlite_conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        counts = {}
        for (table_name,) in cursor.fetchall():
            cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            row_count = cursor.fetchone()[0]
            if row_count:
                counts[table_name] = row_count
        return counts

    def _merge_users(self, sqlite_conn, summary):
        cursor = sqlite_conn.cursor()
        cursor.execute(
            """
            SELECT username, password, last_login, is_superuser, first_name, last_name,
                   email, is_staff, is_active, date_joined
            FROM auth_user
            ORDER BY id
            """
        )
        User = get_user_model()
        for row in cursor.fetchall():
            if User.objects.filter(username=row[0]).exists():
                summary["users_skipped"] += 1
                continue

            User.objects.create(
                username=row[0],
                password=row[1],
                last_login=self._normalize_datetime(row[2]),
                is_superuser=bool(row[3]),
                first_name=row[4],
                last_name=row[5],
                email=row[6],
                is_staff=bool(row[7]),
                is_active=bool(row[8]),
                date_joined=self._normalize_datetime(row[9]),
            )
            summary["users_created"] += 1

    def _merge_sessions(self, sqlite_conn, summary):
        cursor = sqlite_conn.cursor()
        cursor.execute(
            "SELECT session_key, session_data, expire_date FROM django_session ORDER BY session_key"
        )
        for session_key, session_data, expire_date in cursor.fetchall():
            _, created = Session.objects.get_or_create(
                session_key=session_key,
                defaults={
                    "session_data": session_data,
                    "expire_date": self._normalize_datetime(expire_date),
                },
            )
            summary["sessions_created" if created else "sessions_skipped"] += 1

    def _merge_training_runs(self, sqlite_conn, summary):
        cursor = sqlite_conn.cursor()
        cursor.execute(
            """
            SELECT id, trained_at, n_samples, n_classes, accuracy, macro_precision,
                   macro_recall, macro_f1, weighted_precision, weighted_recall,
                   weighted_f1, label_distribution, classification_report
            FROM tracker_modeltrainingrun
            ORDER BY id
            """
        )
        run_map = {}
        for row in cursor.fetchall():
            source_id = row[0]
            values = {
                "trained_at": self._normalize_datetime(row[1]),
                "n_samples": row[2],
                "n_classes": row[3],
                "accuracy": row[4],
                "macro_precision": row[5],
                "macro_recall": row[6],
                "macro_f1": row[7],
                "weighted_precision": row[8],
                "weighted_recall": row[9],
                "weighted_f1": row[10],
                "label_distribution": row[11],
                "classification_report": row[12],
            }
            existing = ModelTrainingRun.objects.filter(**values).first()
            if existing is None:
                existing = ModelTrainingRun.objects.create(**values)
                summary["runs_created"] += 1
            else:
                summary["runs_skipped"] += 1
            run_map[source_id] = existing.id
        return run_map

    def _merge_training_metrics(self, sqlite_conn, run_map, summary):
        cursor = sqlite_conn.cursor()
        cursor.execute(
            """
            SELECT run_id, label, precision, recall, f1, support
            FROM tracker_modeltraininglabelmetric
            ORDER BY id
            """
        )
        for source_run_id, label, precision, recall, f1_score, support in cursor.fetchall():
            target_run_id = run_map.get(source_run_id)
            if target_run_id is None:
                raise CommandError(f"Missing run mapping for SQLite training run {source_run_id}")

            _, created = ModelTrainingLabelMetric.objects.get_or_create(
                run_id=target_run_id,
                label=label,
                defaults={
                    "precision": precision,
                    "recall": recall,
                    "f1": f1_score,
                    "support": support,
                },
            )
            if not created:
                existing = ModelTrainingLabelMetric.objects.filter(
                    run_id=target_run_id,
                    label=label,
                    precision=precision,
                    recall=recall,
                    f1=f1_score,
                    support=support,
                ).exists()
                if existing:
                    summary["metrics_skipped"] += 1
                    continue

                ModelTrainingLabelMetric.objects.create(
                    run_id=target_run_id,
                    label=label,
                    precision=precision,
                    recall=recall,
                    f1=f1_score,
                    support=support,
                )
                summary["metrics_created"] += 1
                continue

            summary["metrics_created"] += 1

    @staticmethod
    def _normalize_datetime(value):
        if value in (None, ""):
            return value
        if isinstance(value, datetime):
            dt_value = value
        else:
            dt_value = parse_datetime(str(value))
            if dt_value is None:
                return value
        if timezone.is_naive(dt_value):
            return timezone.make_aware(dt_value, timezone.get_current_timezone())
        return dt_value