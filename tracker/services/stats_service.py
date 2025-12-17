"""
Stats Service: Business logic for statistics and analytics calculations.

This service handles statistics-related operations including:
- Sidebar metrics calculation (weekly trends, upcoming interviews)
- Dashboard statistics (companies, applications, interviews)
- Label distribution and breakdowns
- Ingestion statistics visualization data

Extracted from views.py to enable better testability and code reuse.
"""

import json
import os
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from django.db.models import Q, QuerySet
from django.utils.timezone import now

from tracker.models import Company, IngestionStats, Message, ThreadTracking


class StatsService:
    """Service layer for statistics and analytics business logic."""

    @staticmethod
    def get_sidebar_metrics() -> Dict:
        """
        Compute sidebar metrics: companies, applications, weekly trends, upcoming interviews.

        Excludes:
        - User's own messages (from USER_EMAIL_ADDRESS env var)
        - Headhunter domains/companies (from companies.json)

        Returns:
            Dictionary with keys:
            - companies: Count of companies with applications
            - applications: Total application count
            - applications_week: Applications in last 7 days
            - rejections_week: Rejections in last 7 days
            - interviews_week: Interview invites in last 7 days (distinct companies)
            - upcoming_interviews: QuerySet of upcoming interviews
            - latest_stats: Latest IngestionStats record
        """
        # Exclude the user's own messages (replies) from counts
        user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip()

        # Load headhunter domains from companies.json
        headhunter_domains = StatsService._load_headhunter_domains()

        # Count companies with actual applications (ThreadTracking records)
        companies_count = (
            Company.objects.filter(threadtracking__isnull=False)
            .exclude(status="headhunter")
            .distinct()
            .count()
        )

        # Build Q filter for Message model headhunter senders
        msg_hh_sender_q = Q()
        for domain in headhunter_domains:
            msg_hh_sender_q |= Q(sender__icontains=f"@{domain}")

        # Total applications: count all ThreadTracking records
        applications_count = ThreadTracking.objects.exclude(
            company__status="headhunter"
        ).count()

        # Weekly application count (total applications)
        week_cutoff = now() - timedelta(days=7)
        applications_week_qs = Message.objects.filter(
            ml_label__in=["job_application", "application"],
            timestamp__gte=week_cutoff,
            company__isnull=False,
        )
        # Exclude user's own messages
        if user_email:
            applications_week_qs = applications_week_qs.exclude(
                sender__icontains=user_email
            )
        # Exclude headhunter companies and domains
        applications_week_qs = applications_week_qs.exclude(company__status="headhunter")
        if headhunter_domains:
            applications_week_qs = applications_week_qs.exclude(msg_hh_sender_q)
        applications_week = applications_week_qs.count()

        # Weekly rejection count
        rejections_qs = Message.objects.filter(
            ml_label__in=["rejected", "rejection"],
            timestamp__gte=week_cutoff,
            company__isnull=False,
        )
        if user_email:
            rejections_qs = rejections_qs.exclude(sender__icontains=user_email)
        if headhunter_domains:
            rejections_qs = rejections_qs.exclude(msg_hh_sender_q)
        rejections_qs = rejections_qs.exclude(ml_label="head_hunter")
        rejections_week = rejections_qs.count()

        # Weekly interview count (distinct companies)
        interviews_qs = Message.objects.filter(
            ml_label="interview_invite",
            timestamp__gte=week_cutoff,
            company__isnull=False,
        )
        if user_email:
            interviews_qs = interviews_qs.exclude(sender__icontains=user_email)
        if headhunter_domains:
            interviews_qs = interviews_qs.exclude(msg_hh_sender_q)
        interviews_week = interviews_qs.values("company_id").distinct().count()

        # Upcoming interviews (exclude rejected/ghosted)
        upcoming_interviews = (
            ThreadTracking.objects.filter(
                interview_date__gte=now(),
                company__isnull=False,
                interview_completed=False,
            )
            .exclude(status="ghosted")
            .exclude(status="rejected")
            .exclude(rejection_date__isnull=False)
            .select_related("company")
            .order_by("interview_date")[:10]
        )

        latest_stats = IngestionStats.objects.order_by("-date").first()

        return {
            "companies": companies_count,
            "applications": applications_count,
            "applications_count": applications_count,
            "applications_week": applications_week,
            "rejections_week": rejections_week,
            "interviews_week": interviews_week,
            "upcoming_interviews": upcoming_interviews,
            "latest_stats": latest_stats,
        }

    @staticmethod
    def get_ingestion_chart_data() -> Dict:
        """
        Get ingestion statistics for visualization.

        Returns:
            Dictionary with:
            - chart_labels: List of date strings (YYYY-MM-DD)
            - chart_inserted: List of inserted counts per day
            - chart_skipped: List of skipped counts per day
            - chart_ignored: List of ignored counts per day
        """
        earliest_stat = IngestionStats.objects.order_by("date").first()
        if not earliest_stat:
            return {
                "chart_labels": [],
                "chart_inserted": [],
                "chart_skipped": [],
                "chart_ignored": [],
            }

        start_date = earliest_stat.date
        end_date = now().date()
        num_days = (end_date - start_date).days + 1
        date_list = [start_date + timedelta(days=i) for i in range(num_days)]

        stats_qs = IngestionStats.objects.filter(date__gte=start_date).order_by("date")
        stats_map = {s.date: s for s in stats_qs}

        chart_labels = [d.strftime("%Y-%m-%d") for d in date_list]
        chart_inserted = [
            stats_map[d].total_inserted if d in stats_map else 0 for d in date_list
        ]
        chart_skipped = [
            stats_map[d].total_skipped if d in stats_map else 0 for d in date_list
        ]
        chart_ignored = [
            stats_map[d].total_ignored if d in stats_map else 0 for d in date_list
        ]

        return {
            "chart_labels": chart_labels,
            "chart_inserted": chart_inserted,
            "chart_skipped": chart_skipped,
            "chart_ignored": chart_ignored,
        }

    @staticmethod
    def get_model_metrics() -> Tuple[Dict, Optional[str], Optional[Dict]]:
        """
        Load model metrics from model_info.json and model_audit.json.

        Returns:
            Tuple of (metrics, training_output, label_breakdown)
            - metrics: Dictionary from model_info.json
            - training_output: Last training output string
            - label_breakdown: Dictionary with real_count, extra_count, real_labels, extra_labels
        """
        metrics = {}
        training_output = None
        label_breakdown = None

        # Load model metrics
        metrics_path = Path("model/model_info.json")
        if metrics_path.exists():
            try:
                with open(metrics_path, "r", encoding="utf-8") as f:
                    metrics = json.load(f)
            except Exception:
                metrics = {}

        # Load training output
        output_path = Path("model/model_audit.json")
        if output_path.exists():
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    audit = json.load(f)
                    training_output = audit.get("training_output")
            except Exception:
                training_output = None

        # Categorize labels into valid vs extra (company names that need fixing)
        valid_labels = {
            "interview",
            "interview_invite",
            "application",
            "job_application",
            "rejected",
            "offer",
            "noise",
            "referral",
            "head_hunter",
            "ghosted",
            "follow_up",
            "response",
            "unknown",
        }

        if "labels" in metrics and isinstance(metrics["labels"], list):
            real_labels = [
                label for label in metrics["labels"] if label.lower() in valid_labels
            ]
            extra_labels = [
                label for label in metrics["labels"] if label.lower() not in valid_labels
            ]
            label_breakdown = {
                "real_count": len(real_labels),
                "extra_count": len(extra_labels),
                "real_labels": real_labels,
                "extra_labels": extra_labels,
            }

        return (metrics, training_output, label_breakdown)

    @staticmethod
    def get_company_threads(company_id: int) -> Tuple[bool, Optional[str], List[Dict]]:
        """
        Get reviewed message threads grouped by subject for a company.

        Args:
            company_id: ID of company to get threads for

        Returns:
            Tuple of (success, error_message, threads_by_subject)
            threads_by_subject: List of dicts with 'subject' and 'messages' keys
        """
        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return (False, f"Company with ID {company_id} not found.", [])

        # Group messages by subject, only reviewed
        msgs = Message.objects.filter(company=company, reviewed=True).order_by(
            "thread_id", "timestamp"
        )

        threads = defaultdict(list)
        for msg in msgs:
            threads[msg.subject].append(msg)

        threads_by_subject = [
            {"subject": subj, "messages": thread} for subj, thread in threads.items()
        ]

        return (True, None, threads_by_subject)

    @staticmethod
    def get_reviewed_companies() -> QuerySet:
        """
        Get all companies that have at least one reviewed message.

        Returns:
            QuerySet of Company objects ordered by name
        """
        reviewed_company_ids = (
            Message.objects.filter(reviewed=True, company__isnull=False)
            .values_list("company_id", flat=True)
            .distinct()
        )
        return Company.objects.filter(id__in=reviewed_company_ids).order_by("name")

    @staticmethod
    def _load_headhunter_domains() -> List[str]:
        """
        Load headhunter domains from companies.json.

        Returns:
            List of headhunter domain strings (lowercase)
        """
        headhunter_domains = []
        try:
            companies_path = Path("json/companies.json")
            if companies_path.exists():
                with open(companies_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    headhunter_domains = [
                        d.strip().lower()
                        for d in data.get("headhunter_domains", [])
                        if d and isinstance(d, str)
                    ]
        except Exception:
            headhunter_domains = []
        return headhunter_domains
