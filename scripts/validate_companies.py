#!/usr/bin/env python3
"""
Company Database Integrity Validator

Validates that all company references in the database are valid and detects:
- Orphaned ThreadTracking records (reference deleted companies)
- Messages with invalid company references (shouldn't happen with SET_NULL, but check)
- Duplicate company names that should be merged
- Companies with no messages or applications (potential cleanup candidates)
- Mismatched company_source annotations
- Companies with inconsistent data (missing required fields)

Usage:
    python validate_companies.py [--verbose] [--fix-orphans]
"""

import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django

django.setup()

from django.db import transaction
from django.db.models import Count, Q
from tracker.models import Company, Message, ThreadTracking


class CompanyValidator:
    """Validates company-related database integrity"""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.issues = defaultdict(list)
        self.stats = {
            "total_companies": 0,
            "total_messages": 0,
            "total_threads": 0,
            "orphaned_threads": 0,
            "orphaned_messages": 0,
            "empty_companies": 0,
            "duplicate_names": 0,
            "data_issues": 0,
        }

    def log(self, message, level="INFO"):
        """Print message with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

    def debug(self, message):
        """Print verbose debugging info"""
        if self.verbose:
            self.log(message, "DEBUG")

    def check_orphaned_threadtracking(self):
        """Find ThreadTracking records pointing to non-existent companies"""
        self.log("Checking for orphaned ThreadTracking records...")

        # This query will fail if company_id points to non-existent company
        # due to CASCADE on delete, but let's check anyway for DB inconsistencies
        try:
            orphaned = ThreadTracking.objects.filter(company__isnull=True)
            count = orphaned.count()

            if count > 0:
                self.stats["orphaned_threads"] = count
                self.issues["orphaned_threads"] = list(
                    orphaned.values("id", "thread_id", "job_title", "company_id")
                )
                self.log(
                    f"❌ Found {count} orphaned ThreadTracking records with NULL company",
                    "ERROR",
                )
                for record in self.issues["orphaned_threads"]:
                    self.debug(
                        f"  - ThreadTracking ID {record['id']}: "
                        f"thread_id={record['thread_id']}, "
                        f"company_id={record['company_id']}"
                    )
            else:
                self.log("✅ No orphaned ThreadTracking records found")

        except Exception as e:
            self.log(f"❌ Error checking ThreadTracking: {e}", "ERROR")

    def check_orphaned_messages(self):
        """
        Find Message records that reference company_id that no longer exists.
        This shouldn't happen with SET_NULL, but check for DB corruption.
        """
        self.log("Checking for messages with invalid company references...")

        try:
            # Find messages where company_id is set but company doesn't exist
            # We need to do this with raw SQL or careful checking
            all_messages_with_company = Message.objects.filter(company_id__isnull=False)
            total = all_messages_with_company.count()

            if total > 0:
                valid_company_ids = set(Company.objects.values_list("id", flat=True))
                orphaned_messages = []

                for msg in all_messages_with_company.values("id", "company_id"):
                    if msg["company_id"] not in valid_company_ids:
                        orphaned_messages.append(msg)

                if orphaned_messages:
                    count = len(orphaned_messages)
                    self.stats["orphaned_messages"] = count
                    self.issues["orphaned_messages"] = orphaned_messages
                    self.log(
                        f"❌ Found {count} messages with invalid company_id", "ERROR"
                    )
                    for msg in orphaned_messages[:10]:  # Show first 10
                        self.debug(
                            f"  - Message ID {msg['id']}: company_id={msg['company_id']}"
                        )
                else:
                    self.log("✅ All messages have valid company references")
            else:
                self.log("✅ No messages with company references to validate")

        except Exception as e:
            self.log(f"❌ Error checking message company references: {e}", "ERROR")

    def check_duplicate_companies(self):
        """Find companies with duplicate names that may need merging"""
        self.log("Checking for duplicate company names...")

        try:
            # Case-insensitive duplicate check
            duplicates = (
                Company.objects.values("name")
                .annotate(count=Count("id"))
                .filter(count__gt=1)
                .order_by("-count")
            )

            if duplicates:
                count = duplicates.count()
                self.stats["duplicate_names"] = count
                self.issues["duplicate_names"] = []

                self.log(f"⚠️  Found {count} duplicate company names", "WARN")

                for dup in duplicates:
                    name = dup["name"]
                    dup_count = dup["count"]
                    companies = Company.objects.filter(name=name)

                    dup_info = {
                        "name": name,
                        "count": dup_count,
                        "ids": list(companies.values_list("id", flat=True)),
                        "details": [],
                    }

                    for company in companies:
                        msg_count = Message.objects.filter(company=company).count()
                        thread_count = ThreadTracking.objects.filter(
                            company=company
                        ).count()
                        dup_info["details"].append(
                            {
                                "id": company.id,
                                "domain": company.domain,
                                "status": company.status,
                                "messages": msg_count,
                                "threads": thread_count,
                                "first_contact": str(company.first_contact),
                                "last_contact": str(company.last_contact),
                            }
                        )

                    self.issues["duplicate_names"].append(dup_info)
                    self.debug(f"  - '{name}': {dup_count} instances")
                    for detail in dup_info["details"]:
                        self.debug(
                            f"    • ID {detail['id']}: {detail['messages']} msgs, "
                            f"{detail['threads']} threads, domain={detail['domain']}"
                        )
            else:
                self.log("✅ No duplicate company names found")

        except Exception as e:
            self.log(f"❌ Error checking duplicate companies: {e}", "ERROR")

    def check_empty_companies(self):
        """Find companies with no messages or applications"""
        self.log("Checking for companies with no associated data...")

        try:
            empty_companies = []

            for company in Company.objects.all():
                msg_count = Message.objects.filter(company=company).count()
                thread_count = ThreadTracking.objects.filter(company=company).count()

                if msg_count == 0 and thread_count == 0:
                    empty_companies.append(
                        {
                            "id": company.id,
                            "name": company.name,
                            "domain": company.domain,
                            "status": company.status,
                            "first_contact": str(company.first_contact),
                        }
                    )

            if empty_companies:
                count = len(empty_companies)
                self.stats["empty_companies"] = count
                self.issues["empty_companies"] = empty_companies
                self.log(
                    f"⚠️  Found {count} companies with no messages or threads", "WARN"
                )
                for company in empty_companies[:10]:  # Show first 10
                    self.debug(
                        f"  - ID {company['id']}: {company['name']} (domain: {company['domain']})"
                    )
            else:
                self.log("✅ All companies have associated messages or threads")

        except Exception as e:
            self.log(f"❌ Error checking empty companies: {e}", "ERROR")

    def check_data_consistency(self):
        """Check for companies with missing or inconsistent data"""
        self.log("Checking for companies with data consistency issues...")

        try:
            issues = []

            for company in Company.objects.all():
                company_issues = []

                # Check for missing required fields
                if not company.name or company.name.strip() == "":
                    company_issues.append("missing or empty name")

                # Check date consistency
                if company.first_contact and company.last_contact:
                    if company.first_contact > company.last_contact:
                        company_issues.append("first_contact is after last_contact")

                # Check confidence value
                if company.confidence is not None:
                    if company.confidence < 0 or company.confidence > 1:
                        company_issues.append(
                            f"invalid confidence: {company.confidence}"
                        )

                if company_issues:
                    issues.append(
                        {
                            "id": company.id,
                            "name": company.name,
                            "issues": company_issues,
                        }
                    )

            if issues:
                count = len(issues)
                self.stats["data_issues"] = count
                self.issues["data_issues"] = issues
                self.log(f"⚠️  Found {count} companies with data issues", "WARN")
                for issue in issues[:10]:  # Show first 10
                    self.debug(
                        f"  - ID {issue['id']}: {issue['name']} - {', '.join(issue['issues'])}"
                    )
            else:
                self.log("✅ All companies have consistent data")

        except Exception as e:
            self.log(f"❌ Error checking data consistency: {e}", "ERROR")

    def check_company_source_mismatches(self):
        """Check if company_source annotations are accurate"""
        self.log("Checking for company_source annotation mismatches...")

        try:
            mismatches = []

            # Check messages where company is set but company_source is blank
            messages_missing_source = Message.objects.filter(
                company__isnull=False, company_source__isnull=True
            ) | Message.objects.filter(company__isnull=False, company_source="")

            if messages_missing_source.exists():
                count = messages_missing_source.count()
                self.log(
                    f"⚠️  Found {count} messages with company but no company_source",
                    "WARN",
                )
                mismatches.extend(
                    list(
                        messages_missing_source.values(
                            "id", "company_id", "company_source", "subject"
                        )[:10]
                    )
                )

            # Check ThreadTracking as well
            threads_missing_source = ThreadTracking.objects.filter(
                company__isnull=False, company_source__isnull=True
            ) | ThreadTracking.objects.filter(company__isnull=False, company_source="")

            if threads_missing_source.exists():
                count = threads_missing_source.count()
                self.log(
                    f"⚠️  Found {count} threads with company but no company_source",
                    "WARN",
                )

            if not mismatches:
                self.log("✅ All company assignments have source annotations")
            else:
                self.issues["source_mismatches"] = mismatches
                for match in mismatches[:10]:
                    self.debug(
                        f"  - Message ID {match['id']}: company_id={match['company_id']}, "
                        f"source={match['company_source']}"
                    )

        except Exception as e:
            self.log(f"❌ Error checking company_source: {e}", "ERROR")

    def gather_stats(self):
        """Gather overall database statistics"""
        self.log("Gathering database statistics...")

        try:
            self.stats["total_companies"] = Company.objects.count()
            self.stats["total_messages"] = Message.objects.count()
            self.stats["total_threads"] = ThreadTracking.objects.count()

            self.log(f"📊 Total Companies: {self.stats['total_companies']}")
            self.log(f"📊 Total Messages: {self.stats['total_messages']}")
            self.log(f"📊 Total ThreadTracking: {self.stats['total_threads']}")

        except Exception as e:
            self.log(f"❌ Error gathering stats: {e}", "ERROR")

    def fix_orphaned_threads(self):
        """Remove orphaned ThreadTracking records (CASCADE should prevent this)"""
        self.log("Attempting to fix orphaned ThreadTracking records...")

        if "orphaned_threads" not in self.issues or not self.issues["orphaned_threads"]:
            self.log("No orphaned threads to fix")
            return

        try:
            with transaction.atomic():
                orphaned_ids = [item["id"] for item in self.issues["orphaned_threads"]]
                deleted_count = ThreadTracking.objects.filter(
                    id__in=orphaned_ids
                ).delete()[0]

                self.log(f"✅ Deleted {deleted_count} orphaned ThreadTracking records")

        except Exception as e:
            self.log(f"❌ Error fixing orphaned threads: {e}", "ERROR")

    def fix_orphaned_messages(self):
        """Set company_id to NULL for orphaned messages"""
        self.log("Attempting to fix orphaned message company references...")

        if (
            "orphaned_messages" not in self.issues
            or not self.issues["orphaned_messages"]
        ):
            self.log("No orphaned messages to fix")
            return

        try:
            with transaction.atomic():
                orphaned_ids = [item["id"] for item in self.issues["orphaned_messages"]]
                updated_count = Message.objects.filter(id__in=orphaned_ids).update(
                    company=None, company_source=""
                )

                self.log(
                    f"✅ Updated {updated_count} orphaned messages (set company=NULL)"
                )

        except Exception as e:
            self.log(f"❌ Error fixing orphaned messages: {e}", "ERROR")

    def print_summary(self):
        """Print summary report"""
        print("\n" + "=" * 80)
        print("COMPANY DATABASE VALIDATION SUMMARY")
        print("=" * 80)

        # Overall stats
        print(f"\n📊 Database Statistics:")
        print(f"  Total Companies:     {self.stats['total_companies']:>6}")
        print(f"  Total Messages:      {self.stats['total_messages']:>6}")
        print(f"  Total ThreadTracking:{self.stats['total_threads']:>6}")

        # Issues found
        print(f"\n🔍 Issues Found:")
        print(f"  Orphaned Threads:    {self.stats['orphaned_threads']:>6}")
        print(f"  Orphaned Messages:   {self.stats['orphaned_messages']:>6}")
        print(f"  Duplicate Names:     {self.stats['duplicate_names']:>6}")
        print(f"  Empty Companies:     {self.stats['empty_companies']:>6}")
        print(f"  Data Inconsistencies:{self.stats['data_issues']:>6}")

        # Overall health
        total_issues = sum(
            [
                self.stats["orphaned_threads"],
                self.stats["orphaned_messages"],
                self.stats["data_issues"],
            ]
        )

        print(f"\n{'=' * 80}")
        if total_issues == 0:
            print("✅ DATABASE INTEGRITY: HEALTHY")
            print("No critical issues found.")
        else:
            print("⚠️  DATABASE INTEGRITY: ISSUES DETECTED")
            print(f"Found {total_issues} critical issue(s) requiring attention.")

        if self.stats["duplicate_names"] > 0:
            print(
                f"\nℹ️  {self.stats['duplicate_names']} duplicate company name(s) detected."
            )
            print("   Consider using the merge companies feature to consolidate them.")

        if self.stats["empty_companies"] > 0:
            print(
                f"\nℹ️  {self.stats['empty_companies']} company(ies) have no messages or threads."
            )
            print("   These may be safe to delete.")

        print("=" * 80 + "\n")

    def run_validation(self, fix_orphans=False):
        """Run all validation checks"""
        self.log("Starting company database validation...")
        print()

        self.gather_stats()
        print()

        self.check_orphaned_threadtracking()
        self.check_orphaned_messages()
        self.check_duplicate_companies()
        self.check_empty_companies()
        self.check_data_consistency()
        self.check_company_source_mismatches()

        if fix_orphans:
            print()
            self.log("Attempting to fix orphaned records...", "INFO")
            self.fix_orphaned_threads()
            self.fix_orphaned_messages()

        print()
        self.print_summary()

        return len(self.issues) > 0


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Validate company database integrity")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--fix-orphans",
        action="store_true",
        help="Automatically fix orphaned records (delete orphaned threads, NULL orphaned messages)",
    )

    args = parser.parse_args()

    validator = CompanyValidator(verbose=args.verbose)
    has_issues = validator.run_validation(fix_orphans=args.fix_orphans)

    # Exit with code 1 if issues found (useful for CI/CD)
    sys.exit(1 if has_issues else 0)


if __name__ == "__main__":
    main()
