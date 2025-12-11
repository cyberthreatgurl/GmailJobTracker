"""
Company Service: Business logic for company operations.

This service handles company-related operations including:
- Company merging (consolidate duplicates)
- Company deletion (with cascade cleanup)
- Alias management (approve/reject suggestions)
- Company statistics and metrics

Extracted from views.py to enable better testability and code reuse.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from django.db import models
from django.db.models import QuerySet
from django.utils.timezone import now

from tracker.models import Company, Message, ThreadTracking


class CompanyService:
    """Service layer for company-related business logic."""

    PATTERNS_PATH = Path("json/patterns.json")
    ALIAS_EXPORT_PATH = Path("json/alias_candidates.json")
    ALIAS_LOG_PATH = Path("alias_approvals.csv")
    ALIAS_REJECT_LOG_PATH = Path("alias_rejections.csv")

    @staticmethod
    def delete_company(
        company_id: int, retrain_model: bool = True
    ) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Delete a company and all related messages/applications.

        Args:
            company_id: ID of company to delete
            retrain_model: Whether to trigger model retraining after deletion

        Returns:
            Tuple of (success, error_message, stats_dict)
            stats_dict contains: company_name, total_messages, noise_messages,
                                non_noise_messages, applications, retrain_status
        """
        try:
            company = Company.objects.get(pk=company_id)
        except Company.DoesNotExist:
            return (
                False,
                f"Company with ID {company_id} not found. It may have already been deleted.",
                None,
            )

        company_name = company.name

        # Count related data before deletion
        total_message_count = Message.objects.filter(company=company).count()
        noise_message_count = Message.objects.filter(
            company=company, ml_label="noise"
        ).count()
        non_noise_message_count = total_message_count - noise_message_count
        application_count = ThreadTracking.objects.filter(company=company).count()

        # Delete all related data
        Message.objects.filter(company=company).delete()
        ThreadTracking.objects.filter(company=company).delete()
        company.delete()

        stats = {
            "company_name": company_name,
            "total_messages": total_message_count,
            "noise_messages": noise_message_count,
            "non_noise_messages": non_noise_message_count,
            "applications": application_count,
            "retrain_status": None,
        }

        # Trigger model retraining if requested
        if retrain_model:
            python_path = sys.executable
            try:
                result = subprocess.run(
                    [python_path, "train_model.py"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if result.returncode == 0:
                    stats["retrain_status"] = "success"
                else:
                    stats["retrain_status"] = "warning"
            except subprocess.TimeoutExpired:
                stats["retrain_status"] = "timeout"
            except Exception as e:
                stats["retrain_status"] = f"error: {str(e)}"

        return (True, None, stats)

    @staticmethod
    def merge_companies(
        company_ids: List[str], canonical_id: str
    ) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Merge multiple companies into one canonical company.

        Reassigns all messages and applications to the canonical company,
        updates timestamps, and deletes duplicate company records.

        Args:
            company_ids: List of company IDs to merge
            canonical_id: ID of the canonical (real) company to keep

        Returns:
            Tuple of (success, error_message, stats_dict)
            stats_dict contains: canonical_name, duplicate_names, messages_moved,
                                applications_moved
        """
        if not company_ids or len(company_ids) < 2:
            return (False, "Please select at least 2 companies to merge.", None)

        if not canonical_id or canonical_id not in company_ids:
            return (
                False,
                "Please select which company is the canonical (real) name.",
                None,
            )

        try:
            canonical_company = Company.objects.get(id=canonical_id)
            duplicate_ids = [cid for cid in company_ids if cid != canonical_id]
            duplicates = Company.objects.filter(id__in=duplicate_ids)

            # Reassign all messages and applications
            messages_moved = Message.objects.filter(company__in=duplicates).update(
                company=canonical_company
            )
            apps_moved = ThreadTracking.objects.filter(company__in=duplicates).update(
                company=canonical_company
            )

            # Update canonical company timestamps
            all_messages = Message.objects.filter(company=canonical_company).order_by(
                "timestamp"
            )
            if all_messages.exists():
                canonical_company.first_contact = all_messages.first().timestamp
                canonical_company.last_contact = all_messages.last().timestamp
                canonical_company.save()

            # Delete duplicate companies
            duplicate_names = list(duplicates.values_list("name", flat=True))
            duplicates.delete()

            stats = {
                "canonical_name": canonical_company.name,
                "duplicate_names": duplicate_names,
                "messages_moved": messages_moved,
                "applications_moved": apps_moved,
            }

            return (True, None, stats)

        except Company.DoesNotExist:
            return (False, "Canonical company not found.", None)
        except Exception as e:
            return (False, f"Merge failed: {str(e)}", None)

    @staticmethod
    def get_alias_suggestions() -> List[Dict]:
        """
        Load alias suggestions from alias_candidates.json.

        Returns:
            List of alias suggestion dictionaries
        """
        if not CompanyService.ALIAS_EXPORT_PATH.exists():
            return []

        try:
            with open(
                CompanyService.ALIAS_EXPORT_PATH, "r", encoding="utf-8"
            ) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    @staticmethod
    def approve_bulk_aliases(
        aliases: List[str], suggested: List[str], timestamp: Optional[str] = None
    ) -> Tuple[bool, Optional[str], int]:
        """
        Persist approved alias→company mappings into patterns.json.

        Args:
            aliases: List of alias names to approve
            suggested: List of corresponding company names
            timestamp: Optional timestamp for logging

        Returns:
            Tuple of (success, error_message, count_approved)
        """
        if len(aliases) != len(suggested):
            return (False, "Mismatch between aliases and suggestions.", 0)

        try:
            # Load existing patterns
            if CompanyService.PATTERNS_PATH.exists():
                with open(CompanyService.PATTERNS_PATH, "r", encoding="utf-8") as f:
                    patterns = json.load(f)
            else:
                patterns = {"aliases": {}, "ignore": []}

            # Add approved aliases
            for alias, suggestion in zip(aliases, suggested):
                patterns["aliases"][alias] = suggestion

                # Log approval
                if not CompanyService.ALIAS_LOG_PATH.exists():
                    CompanyService.ALIAS_LOG_PATH.parent.mkdir(
                        parents=True, exist_ok=True
                    )
                with open(CompanyService.ALIAS_LOG_PATH, "a", encoding="utf-8") as log:
                    log_timestamp = timestamp or now().isoformat()
                    log.write(f"{alias},{suggestion},{log_timestamp}\n")

            # Save updated patterns
            with open(CompanyService.PATTERNS_PATH, "w", encoding="utf-8") as f:
                json.dump(patterns, f, indent=2)

            return (True, None, len(aliases))

        except Exception as e:
            return (False, f"Failed to approve aliases: {str(e)}", 0)

    @staticmethod
    def reject_alias(alias: str, timestamp: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Add an alias to the ignore list in patterns.json.

        Args:
            alias: Alias name to reject
            timestamp: Optional timestamp for logging

        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Load existing patterns
            if CompanyService.PATTERNS_PATH.exists():
                with open(CompanyService.PATTERNS_PATH, "r", encoding="utf-8") as f:
                    patterns = json.load(f)
            else:
                patterns = {"aliases": {}, "ignore": []}

            # Add to ignore list if not already there
            if alias not in patterns["ignore"]:
                patterns["ignore"].append(alias)

            # Save updated patterns
            with open(CompanyService.PATTERNS_PATH, "w", encoding="utf-8") as f:
                json.dump(patterns, f, indent=2)

            # Log rejection
            if not CompanyService.ALIAS_REJECT_LOG_PATH.exists():
                CompanyService.ALIAS_REJECT_LOG_PATH.parent.mkdir(
                    parents=True, exist_ok=True
                )
            with open(
                CompanyService.ALIAS_REJECT_LOG_PATH, "a", encoding="utf-8"
            ) as log:
                log_timestamp = timestamp or now().isoformat()
                log.write(f"{alias},{log_timestamp}\n")

            return (True, None)

        except Exception as e:
            return (False, f"Failed to reject alias: {str(e)}")

    @staticmethod
    def get_company_statistics() -> Dict:
        """
        Get statistics about companies in the system.

        Returns:
            Dictionary with company counts by status, total companies,
            companies with applications, etc.
        """
        stats = {
            "total_companies": Company.objects.count(),
            "companies_with_apps": Company.objects.filter(
                threadtracking__isnull=False
            )
            .distinct()
            .count(),
            "by_status": {},
        }

        # Count by status
        status_counts = Company.objects.values("status").annotate(
            count=models.Count("id")
        )
        for item in status_counts:
            stats["by_status"][item["status"]] = item["count"]

        return stats

    @staticmethod
    def get_companies_for_labeling(
        status_filter: Optional[str] = None,
        search_query: Optional[str] = None,
    ) -> QuerySet:
        """
        Get companies filtered by status and search query.

        Args:
            status_filter: Optional status to filter by
            search_query: Optional search term for company name

        Returns:
            QuerySet of Company objects
        """
        companies = Company.objects.all()

        if status_filter:
            companies = companies.filter(status=status_filter)

        if search_query:
            companies = companies.filter(name__icontains=search_query)

        return companies.order_by("name")
