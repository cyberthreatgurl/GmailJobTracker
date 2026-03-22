"""Gmail message parsing and ingestion engine.

This module handles the core email processing pipeline:
- Extracts metadata (subject, sender, body, timestamps) from Gmail API responses
- Applies hybrid ML + regex-based classification (interview/rejection/application/noise)
- Resolves company names via 4-tier fallback (whitelist → domain mapping → ML → regex)
- Creates/updates Django ORM records (Message, Application, Company)
- Tracks ingestion statistics and handles duplicate detection

Architecture:
    Phase 3 (Refactoring): Consolidated parser classes from parser_refactored/ package
    into this single file for simpler architecture and easier maintenance.

    Previously, these classes were separated in parser_refactored/:
    - CompanyValidator: Company name validation and normalization
    - DomainMapper: Domain-to-company mapping and ATS detection
    - RuleClassifier: Rule-based classification using regex patterns
    - CompanyResolver: Company name extraction strategies
    - EmailBodyParser: Email body extraction and MIME decoding
    - MetadataExtractor: Date/metadata extraction from emails

    Now all classes are defined inline in this module, maintaining the same APIs
    and functionality while eliminating the need for a separate package.

    Phase 4 (Utility Refactoring): Extracted utility functions into tracker/utils/ modules
    for better organization and reusability:
    - tracker/utils/validation.py: Company validation utilities (is_valid_company_name, etc.)
    - tracker/utils/email_parsing.py: Email/MIME parsing utilities (decode_mime_part, etc.)
    - tracker/utils/helpers.py: General helpers (should_ignore, extract_confidence, etc.)

    Backward-compatible wrapper functions remain in this file; new code can import from
    tracker.utils modules for cleaner dependencies.
"""

# pylint: disable=broad-exception-caught

import base64
import hashlib
import html
import json
import os
from typing import Any, cast

# from joblib import load  # not needed here
import re
from datetime import datetime, timedelta, date
from email.utils import parseaddr, parsedate_to_datetime
from email.header import decode_header as eml_decode_header
from pathlib import Path

import django
import joblib
from bs4 import BeautifulSoup
from django.utils import timezone
from django.utils.timezone import now

from db import (
    COMPANIES_PATH,
    PATTERNS_PATH,
    is_valid_company,
)
from tracker_logger import log_console
from ml_entity_extraction import extract_entities
from ml_subject_classifier import predict_subject_type
from parser_helpers import (
    is_cancelled_position,
    is_withdrawn_position,
    _increment_stat,
    _is_headhunter_source,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from tracker.models import (
    Company,
    IgnoredMessage,
    IngestionStats,
    Message,
    ThreadTracking,
    UnresolvedCompany,
)

import logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()
logger = logging.getLogger("parser")


# ======================================================================================
# PHASE 3: CONSOLIDATED PARSER CLASSES
# CompanyValidator and CompanyResolver extracted to company_resolver.py
# RuleClassifier extracted to rule_classifier.py
# Remaining classes: DomainMapper, EmailBodyParser, MetadataExtractor
# ======================================================================================

# Import extracted classes (backward-compatible re-exports)
from company_resolver import CompanyValidator, CompanyResolver  # noqa: E402
from rule_classifier import RuleClassifier  # noqa: E402
from email_parser import EmailBodyParser, MetadataExtractor  # noqa: E402

def build_company_job_index(company, job_title, job_id):
    def normalize(text):
        if not text:
            return ""
        return re.sub(r"\s+", " ", text.strip().lower())
    return f"{normalize(company)}::{normalize(job_title)}::{normalize(job_id)}"


def _normalize_job_match_text(text: str | None) -> str:
    """Normalize job identifiers/titles for exact duplicate checks."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _application_identity_matches(application_obj, company_obj, job_title: str, job_id: str) -> bool:
    """Return True when parsed application metadata matches an existing ThreadTracking."""
    if not application_obj or not company_obj or application_obj.company_id != company_obj.id:
        return False

    parsed_job_id = _normalize_job_match_text(job_id)
    existing_job_id = _normalize_job_match_text(application_obj.job_id)
    if parsed_job_id and existing_job_id:
        return parsed_job_id == existing_job_id

    parsed_job_title = _normalize_job_match_text(job_title)
    existing_job_title = _normalize_job_match_text(application_obj.job_title)
    if parsed_job_title and existing_job_title:
        return parsed_job_title == existing_job_title

    return False


def _should_enrich_existing_application(application_obj, company_obj, job_title: str, job_id: str) -> bool:
    """Return True when a same-thread application should enrich the existing record."""
    if _application_identity_matches(application_obj, company_obj, job_title, job_id):
        return True

    if not application_obj or not company_obj or application_obj.company_id != company_obj.id:
        return False

    parsed_job_title = _normalize_job_match_text(job_title)
    parsed_job_id = _normalize_job_match_text(job_id)
    if not parsed_job_title and not parsed_job_id:
        return False

    existing_job_title = _normalize_job_match_text(application_obj.job_title)
    existing_job_id = _normalize_job_match_text(application_obj.job_id)
    return not existing_job_title and not existing_job_id


def _find_existing_application_by_identity(
    company_obj,
    job_title: str,
    job_id: str,
    *,
    exclude_thread_ids=None,
    sent_date=None,
):
    """Find an existing application for the same company/job across threads."""
    if not company_obj:
        return None

    normalized_job_id = _normalize_job_match_text(job_id)
    normalized_job_title = _normalize_job_match_text(job_title)
    if not normalized_job_id and not normalized_job_title:
        return None

    queryset = ThreadTracking.objects.filter(company=company_obj).order_by("-sent_date", "-id")
    if exclude_thread_ids:
        queryset = queryset.exclude(thread_id__in=set(exclude_thread_ids))

    candidates = list(queryset)
    if sent_date:
        candidates = [
            candidate for candidate in candidates
            if not candidate.sent_date or candidate.sent_date <= sent_date
        ]
        recent_cutoff = sent_date - timedelta(days=3)
        recent_candidates = [
            candidate for candidate in candidates
            if candidate.sent_date and candidate.sent_date >= recent_cutoff
        ]
        if recent_candidates:
            candidates = recent_candidates

    for candidate in candidates:
        candidate_job_id = _normalize_job_match_text(candidate.job_id)
        if normalized_job_id and candidate_job_id == normalized_job_id:
            return candidate

    for candidate in candidates:
        candidate_job_title = _normalize_job_match_text(candidate.job_title)
        if normalized_job_title and candidate_job_title == normalized_job_title:
            return candidate

    return None


def _find_existing_milestone_application(
    company_obj,
    metadata,
    parsed_subject,
):
    """Find an existing application record for prescreen/interview milestones."""
    if not company_obj:
        return None

    thread_id = metadata.get("thread_id")
    if thread_id:
        application_obj = ThreadTracking.objects.filter(thread_id=thread_id).first()
        if application_obj:
            return application_obj

    exact_match = _find_existing_application_by_identity(
        company_obj,
        parsed_subject.get("job_title", "") if isinstance(parsed_subject, dict) else "",
        parsed_subject.get("job_id", "") if isinstance(parsed_subject, dict) else "",
        exclude_thread_ids={thread_id} if thread_id else None,
        sent_date=timezone.localtime(metadata["timestamp"]).date() if metadata.get("timestamp") else None,
    )
    if exact_match is not None:
        return exact_match

    if _is_compliance_prescreen_message(
        metadata.get("subject", ""),
        metadata.get("body", ""),
    ):
        return _find_unique_active_prior_application(
            company_obj,
            exclude_thread_ids={thread_id} if thread_id else None,
            sent_date=timezone.localtime(metadata["timestamp"]).date() if metadata.get("timestamp") else None,
        )

    return None


def _is_compliance_prescreen_message(subject: str | None, body: str | None) -> bool:
    """Return True for compliance/pre-screen workflow messages that lack job identity."""
    text = " ".join(part for part in (subject or "", body or "") if part).lower()
    if not text:
        return False

    return any(
        marker in text
        for marker in (
            "compliance",
            "pre-screen",
            "pre screen",
            "complete the form",
            "asked to complete a form",
            "threatswitch",
        )
    )


def _is_application_like_threadtracking(application_obj) -> bool:
    """Return True when a ThreadTracking row represents a canonical application target."""
    if not application_obj:
        return False

    return bool(
        application_obj.ml_label == "job_application"
        or _normalize_job_match_text(application_obj.job_title)
        or _normalize_job_match_text(application_obj.job_id)
    )


def _find_unique_prior_application(company_obj, *, exclude_thread_ids=None, sent_date=None):
    """Return a unique prior application candidate when identity matching is unavailable."""
    if not company_obj:
        return None

    queryset = ThreadTracking.objects.filter(company=company_obj).order_by("-sent_date", "-id")
    if exclude_thread_ids:
        queryset = queryset.exclude(thread_id__in=set(exclude_thread_ids))

    candidates = [candidate for candidate in queryset if _is_application_like_threadtracking(candidate)]
    if sent_date:
        candidates = [
            candidate for candidate in candidates
            if not candidate.sent_date or candidate.sent_date <= sent_date
        ]

    if len(candidates) == 1:
        return candidates[0]
    return None


def _find_unique_active_prior_application(company_obj, *, exclude_thread_ids=None, sent_date=None):
    """Return a unique prior application candidate that is still active."""
    if not company_obj:
        return None

    queryset = ThreadTracking.objects.filter(company=company_obj).order_by("-sent_date", "-id")
    if exclude_thread_ids:
        queryset = queryset.exclude(thread_id__in=set(exclude_thread_ids))

    candidates = [
        candidate for candidate in queryset
        if _is_application_like_threadtracking(candidate)
        and not candidate.rejection_date
        and not candidate.cancelled
        and not candidate.withdrew
        and (not sent_date or not candidate.sent_date or candidate.sent_date <= sent_date)
    ]

    if len(candidates) == 1:
        return candidates[0]
    return None


def _find_existing_offer_application(
    company_obj,
    metadata,
    parsed_subject,
):
    """Find the canonical application that should receive an offer milestone."""
    if not company_obj:
        return None

    milestone_date = (
        timezone.localtime(metadata["timestamp"]).date()
        if metadata.get("timestamp") else None
    )
    thread_id = metadata.get("thread_id")

    if thread_id:
        current_tt = ThreadTracking.objects.filter(thread_id=thread_id).first()
        if current_tt and _is_application_like_threadtracking(current_tt):
            if not milestone_date or not current_tt.sent_date or current_tt.sent_date <= milestone_date:
                return current_tt

    exact_match = _find_existing_application_by_identity(
        company_obj,
        parsed_subject.get("job_title", "") if isinstance(parsed_subject, dict) else "",
        parsed_subject.get("job_id", "") if isinstance(parsed_subject, dict) else "",
        exclude_thread_ids={thread_id} if thread_id else None,
        sent_date=milestone_date,
    )
    if exact_match is not None:
        return exact_match

    return _find_unique_prior_application(
        company_obj,
        exclude_thread_ids={thread_id} if thread_id else None,
        sent_date=milestone_date,
    )


def _is_generic_application_reminder(subject: str | None) -> bool:
    """Return True when the subject is a dashboard/reminder acknowledgement."""
    normalized_subject = _normalize_job_match_text(subject)
    if not normalized_subject:
        return False

    reminder_markers = (
        "keep track of your application",
        "your application dashboard",
        "application status update",
    )
    return any(marker in normalized_subject for marker in reminder_markers)


def _is_duplicate_application_acknowledgement(msg_id, metadata, company_obj, parsed_subject) -> bool:
    """Return True when a job_application message is only a duplicate acknowledgement."""
    if not company_obj:
        return False

    thread_id = metadata.get("thread_id")
    if not thread_id:
        return False

    parsed_job_title = parsed_subject.get("job_title", "") if isinstance(parsed_subject, dict) else ""
    parsed_job_id = parsed_subject.get("job_id", "") if isinstance(parsed_subject, dict) else ""
    if msg_id != thread_id:
        existing_application = ThreadTracking.objects.filter(
            thread_id=thread_id,
            company=company_obj,
        ).first()
        if existing_application and _should_enrich_existing_application(
            existing_application,
            company_obj,
            parsed_job_title,
            parsed_job_id,
        ):
            return True

    cross_thread_match = _find_existing_application_by_identity(
        company_obj,
        parsed_job_title,
        parsed_job_id,
        exclude_thread_ids={thread_id, msg_id},
        sent_date=timezone.localtime(metadata["timestamp"]).date() if metadata.get("timestamp") else None,
    )
    if cross_thread_match is None:
        return False

    if msg_id == thread_id:
        return _is_generic_application_reminder(metadata.get("subject", ""))

    return True


def extract_application_job_id_from_body(body: str | None) -> str:
    """Extract job ID from application email body text or embedded job URLs."""
    if not body:
        return ""

    text = re.sub(r'&nbsp;', ' ', body)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    patterns = [
        r'\b(?:ID|Job ID|Position ID|Req(?:uisition)? ID)\s*[:#]?\s*([A-Z0-9\-]{4,})\b',
        r'\b/jobs/([0-9]{4,})\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


class DomainMapper:
    """Maps email domains to companies and detects ATS/job board domains.

    This class encapsulates domain resolution logic, company data loading,
    and automatic reloading when the companies.json file changes.
    """


    def __init__(self, companies_path: Path):
        """Initialize DomainMapper with path to companies.json.

        Args:
            companies_path: Path to companies.json configuration file
        """
        self.companies_path = companies_path
        self._domain_map_mtime = None

        # Company data structures
        self.ats_domains = []
        self.headhunter_domains = []
        self.job_board_domains = []
        self.known_companies = set()
        self.known_companies_cased = []
        self.domain_to_company = {}
        self.aliases = {}
        self.company_data = {}

        # Load initial data
        self._load_company_data()

    def _load_company_data(self):
        """Load company data from companies.json file."""
        if not self.companies_path.exists():
            logger.debug(f"[WARNING] companies.json not found at {self.companies_path}")
            return

        try:
            with open(self.companies_path, "r", encoding="utf-8") as f:
                self.company_data = json.load(f)

            # Extract all company configuration data
            self.ats_domains = [
                d.lower() for d in self.company_data.get("ats_domains", [])
            ]
            self.headhunter_domains = [
                d.lower() for d in self.company_data.get("headhunter_domains", [])
            ]
            self.job_board_domains = [
                d.lower() for d in self.company_data.get("job_boards", [])
            ]
            self.known_companies = {
                c.lower() for c in self.company_data.get("known", [])
            }
            self.known_companies_cased = self.company_data.get("known", [])
            self.domain_to_company = {
                k.lower(): v
                for k, v in self.company_data.get("domain_to_company", {}).items()
            }
            self.aliases = self.company_data.get("aliases", {})

            # Load new configurable patterns (with fallback defaults)
            self.ats_heuristic_patterns = [
                p.lower() for p in self.company_data.get("ats_heuristic_patterns", [
                    "workday", "greenhouse", "lever", "icims", "taleo",
                    "brassring", "smartrecruiters", "jobvite", "successfactors",
                    "bamboohr", "paylocity", "ultipro", "ashby", "rippling",
                    "applicantpro", "jazzhr", "recruitee", "workable",
                ])
            ]
            self.display_name_noise_words = self.company_data.get("display_name_noise_words", [
                "Workday", "Recruiting Team", "Careers", "Talent Acquisition Team",
                "HR", "Hiring", "Notification", "Notifications", "Team", "Portal",
            ])
            self.ats_platform_suffixes = [
                s.lower() for s in self.company_data.get("ats_platform_suffixes", [
                    "icims", "workday", "greenhouse", "lever", "indeed",
                ])
            ]
            self.job_board_sender_patterns = [
                p.lower() for p in self.company_data.get("job_board_sender_patterns", [
                    "indeedapply",
                ])
            ]

            # Track file modification time for auto-reload
            try:
                self._domain_map_mtime = self.companies_path.stat().st_mtime
            except Exception:
                self._domain_map_mtime = None

            logger.debug(
                f"[INFO] Loaded companies.json: {len(self.domain_to_company)} domains, "
                f"{len(self.known_companies)} companies"
            )
        except json.JSONDecodeError as e:
            print(f"[Error] Failed to parse companies.json: {e}")
            self.company_data = {}
        except Exception as e:
            print(f"[Error] Unable to read companies.json: {e}")
            self.company_data = {}

    def reload_if_needed(self):
        """Reload company data from companies.json if the file has been modified.

        This allows companies.json edits to be picked up at runtime without
        restarting the process.
        """
        try:
            if not self.companies_path.exists():
                return

            mtime = self.companies_path.stat().st_mtime
            if self._domain_map_mtime != mtime:
                self._load_company_data()
                logger.debug(f"[INFO] Reloaded companies.json (mtime changed)")
        except Exception as e:
            # If reload fails, keep the existing mapping silently
            logger.debug(f"[WARNING] Failed to reload companies.json: {e}")
    def is_ats_domain(self, domain: str) -> bool:
        """Return True if domain equals or is a subdomain of any ATS root domain.

        First checks the static list from companies.json, then falls back to
        heuristic detection based on common ATS URL patterns.

        Args:
            domain: Email domain to check (e.g., 'myworkday.com', 'talent.icims.com')

        Returns:
            True if domain is an ATS domain, False otherwise
        """
        if not domain:
            return False
        d = domain.lower()

        # Check static list first
        for ats in self.ats_domains:
            if d == ats or d.endswith("." + ats):
                return True

        # Heuristic fallback: detect ATS from configurable patterns
        for pattern in self.ats_heuristic_patterns:
            if pattern in d:
                logger.debug(f"[ATS HEURISTIC] Domain {domain} matched pattern '{pattern}'")
                return True

        return False

    def map_company_by_domain(self, domain: str):
        """Resolve company by exact or subdomain match from domain_to_company mapping.

        Example: if mapping contains 'nsa.gov' -> 'National Security Agency', then
        'uwe.nsa.gov' will also map to that company.

        Args:
            domain: Email domain to resolve (e.g., 'careers.company.com')

        Returns:
            Company name if domain maps to a known company, None otherwise
        """
        # Ensure we have the latest mapping
        self.reload_if_needed()

        if not domain:
            return None

        d = domain.lower()

        # Exact match first
        if d in self.domain_to_company:
            return self.domain_to_company[d]

        # Subdomain suffix match
        for root, company in self.domain_to_company.items():
            if d.endswith("." + root):
                return company

        return None

    def is_job_board_domain(self, domain: str) -> bool:
        """Return True if domain is a known job board domain.

        Args:
            domain: Email domain to check

        Returns:
            True if domain is a job board, False otherwise
        """
        if not domain:
            return False
        return domain.lower() in self.job_board_domains

    def is_headhunter_domain(self, domain: str) -> bool:
        """Return True if domain is a known headhunter/recruiting agency domain.

        Args:
            domain: Email domain to check

        Returns:
            True if domain is a headhunter domain, False otherwise
        """
        if not domain:
            return False
        return domain.lower() in self.headhunter_domains

    def get_domain_for_company(self, company_name: str) -> str | None:
        """Look up the domain for a known company name.

        Reverse lookup in domain_to_company mapping to find the primary domain
        for a company. Returns the shortest domain (most likely the primary).

        Args:
            company_name: Company name to look up

        Returns:
            Domain string if found, None otherwise
        """
        if not company_name:
            return None
        company_lower = company_name.lower()
        # Find all domains that map to this company
        matching_domains = [
            domain
            for domain, name in self.domain_to_company.items()
            if name.lower() == company_lower
        ]
        if not matching_domains:
            return None
        # Return shortest domain (most likely primary, not subdomain)
        return min(matching_domains, key=len)


# END OF CONSOLIDATED PARSER CLASSES
# ======================================================================================

# --- Load patterns.json ---
if PATTERNS_PATH.exists():
    with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
        patterns_data = json.load(f)
    PATTERNS = patterns_data
else:
    PATTERNS = {}

# Initialize refactored components
COMPANIES_PATH = Path(__file__).parent / "json" / "companies.json"
_company_validator = CompanyValidator(PATTERNS)
_rule_classifier = RuleClassifier(PATTERNS)
_domain_mapper = DomainMapper(COMPANIES_PATH)
_company_resolver = CompanyResolver(
    company_data=_domain_mapper.company_data,
    domain_mapper=_domain_mapper,
    company_validator=_company_validator,
    known_companies=_domain_mapper.known_companies,
    job_board_domains=_domain_mapper.job_board_domains,
    ats_domains=_domain_mapper.ats_domains,
)
_metadata_extractor = MetadataExtractor(_rule_classifier)

# --- Load personal_domains.json ---
PERSONAL_DOMAINS_PATH = Path(__file__).parent / "json" / "personal_domains.json"
if PERSONAL_DOMAINS_PATH.exists():
    with open(PERSONAL_DOMAINS_PATH, "r", encoding="utf-8") as f:
        personal_domains_data = json.load(f)
    PERSONAL_DOMAINS = set(personal_domains_data.get("domains", []))
else:
    # Fallback to default list if file doesn't exist
    PERSONAL_DOMAINS = {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "aol.com",
        "icloud.com",
    }

# Compile application patterns for efficient matching
# Include application confirmations, rejections, and interview invites
# to prevent ATS emails with List-Unsubscribe headers from being marked as newsletters
APPLICATION_PATTERNS = []
app_pattern_sources = []
if "message_labels" in PATTERNS and "application" in PATTERNS["message_labels"]:
    app_pattern_sources.extend(PATTERNS["message_labels"]["application"])
if (
    "early_detection" in PATTERNS
    and "application_confirmation" in PATTERNS["early_detection"]
):
    app_pattern_sources.extend(PATTERNS["early_detection"]["application_confirmation"])

# Also include rejection and interview patterns to prevent false newsletter detection
if "message_labels" in PATTERNS:
    if "rejection" in PATTERNS["message_labels"]:
        app_pattern_sources.extend(PATTERNS["message_labels"]["rejection"])
    if "interview" in PATTERNS["message_labels"]:
        app_pattern_sources.extend(PATTERNS["message_labels"]["interview"])
    if "cancelled" in PATTERNS["message_labels"]:
        app_pattern_sources.extend(PATTERNS["message_labels"]["cancelled"])
    if "head_hunter" in PATTERNS["message_labels"]:
        app_pattern_sources.extend(PATTERNS["message_labels"]["head_hunter"])

# Add early detection patterns for rejections and interviews
if "early_detection" in PATTERNS:
    if "rejection_override" in PATTERNS["early_detection"]:
        app_pattern_sources.extend(PATTERNS["early_detection"]["rejection_override"])
    if "scheduling_language" in PATTERNS["early_detection"]:
        app_pattern_sources.extend(PATTERNS["early_detection"]["scheduling_language"])
    if "cancelled_position" in PATTERNS["early_detection"]:
        app_pattern_sources.extend(PATTERNS["early_detection"]["cancelled_position"])

if app_pattern_sources:
    APPLICATION_PATTERNS = [
        re.compile(pattern, re.IGNORECASE) for pattern in app_pattern_sources
    ]
# Map from label names used in code to JSON keys
LABEL_MAP = {
    "interview_invite": ["interview", "interview_invite"],
    "job_application": ["application", "job_application"],
    "rejection": [
        "rejection",
        "rejected",
    ],  # Consolidated: use 'rejection' as canonical
    "offer": ["offer"],
    "noise": ["noise"],
    "ignore": ["ignore"],
    "response": ["response"],
    "follow_up": ["follow_up"],
    "ghosted": ["ghosted"],
    "referral": ["referral"],
    "head_hunter": ["head_hunter"],
    "other": ["other"],  # Explicitly support 'other' patterns
}

# Note: Pattern compilation moved to RuleClassifier class
# _MSG_LABEL_PATTERNS and _MSG_LABEL_EXCLUDES are now maintained by _rule_classifier


def rule_label(
    subject: str, body: str = "", sender_domain: str | None = None
) -> str | None:
    """Return a rule-based label from compiled regex patterns (delegates to RuleClassifier).

    Checks message text against label patterns in a prioritized order to
    reduce false positives (e.g., prefer noise over rejected for newsletters).
    Returns one of the known labels or None if no rule matches.
    """
    return _rule_classifier.classify(
        subject=subject,
        body=body,
        sender_domain=sender_domain,
        headhunter_domains=set(HEADHUNTER_DOMAINS),
        job_board_domains=set(JOB_BOARD_DOMAINS),
        is_ats_domain_fn=_is_ats_domain,
        map_company_by_domain_fn=_map_company_by_domain,
    )


def predict_with_fallback(
    predict_subject_type_fn,
    subject: str,
    body: str = "",
    threshold: float = 0.55,
    sender: str = "",
):
    """
    Wrap ML predictor; if low confidence or empty features, fall back to rules.
    ALWAYS check high-priority noise patterns (newsletter, digest, OTP) to override ML.
    Expects ML to return dict with keys: label, confidence (or proba).
    """
    ml = predict_subject_type_fn(subject, body, sender=sender)
    conf = float(ml.get("confidence", ml.get("proba", 0.0)) if ml else 0.0)

    # CRITICAL: Always check for noise patterns FIRST (even if ML has high confidence)
    # Newsletters, digests, OTPs are definitive noise and should override any ML prediction
    # Extract sender domain (if provided) and pass to rule-based checks
    sender_domain = ""
    if sender:
        try:
            parsed = parseaddr(sender)
            email_addr = parsed[1] if len(parsed) == 2 else ""
            m = re.search(r"@([A-Za-z0-9.-]+)$", email_addr)
            sender_domain = m.group(1).lower() if m else ""
        except Exception:
            sender_domain = ""

    rl = rule_label(subject, body, sender_domain)
    logger.debug(
        f"[DEBUG predict_with_fallback] ML label={ml.get('label')}, confidence={conf}"
    )
    logger.debug(f"[DEBUG predict_with_fallback] rule_label result={rl}")
    logger.debug(
        "[DEBUG predict_with_fallback] body length=%s, contains 'newsletter'=%s, "
        "contains 'digest'=%s",
        len(body),
        "newsletter" in body.lower(),
        "digest" in body.lower(),
    )
    if body:
        logger.debug(f"[DEBUG predict_with_fallback] body first 500 chars: {body[:500]}")

    # If rule_label returned a result, use it authoritatively (skip ML overrides)
    # BUT preserve the original ML prediction for downstream override logic
    if rl is not None:
        logger.debug(f"[DEBUG predict_with_fallback] Using rule-based label '{rl}' authoritatively")
        return {
            "label": rl,
            "confidence": 1.0,
            "fallback": "rule",
            "ml_label": ml.get("label") if ml else None,
        }

    # If ML confidence is low, use rules as fallback
    if not ml or conf < threshold:
        if rl:
            logger.debug(f"[DEBUG predict_with_fallback] Using rules fallback (low confidence): {rl}")
            return {
                "label": rl,
                "confidence": conf,
                "fallback": "rules",
                "ml_label": ml.get("label") if ml else None,
            }

    if ml and "confidence" not in ml and "proba" in ml:
        ml = {**ml, "confidence": float(ml["proba"])}
    return ml

def get_stats():
    """Get or create today's IngestionStats row and return it."""
    today = now().date()
    stats, _ = IngestionStats.objects.get_or_create(date=today)
    return stats


def is_application_related(subject, body):
    """Check if message is job-related (application, rejection, interview) using patterns from patterns.json.

    This prevents ATS emails with List-Unsubscribe headers from being incorrectly marked as newsletters.
    ATS systems (Workday, Greenhouse, etc.) add List-Unsubscribe headers to ALL automated emails
    for legal compliance, including rejections, interview invites, and application confirmations.

    Args:
        subject: Email subject line
        body: Email body text (first 500 chars recommended)

    Returns:
        True if any job-related pattern matches (application/rejection/interview), False otherwise
    """
    if not APPLICATION_PATTERNS:
        return False
    text = f"{subject or ''} {body or ''}".lower()
    return any(pattern.search(text) for pattern in APPLICATION_PATTERNS)


# Phase 8: decode_part, extract_body, extract_body_from_parts, _decode_header_value
# wrappers removed — callers now use EmailBodyParser class methods directly.


def parse_raw_message(raw_text: str) -> dict:
    """Parse a raw EML (RFC 822) message string (delegates to EmailBodyParser)."""
    return EmailBodyParser.parse_raw_eml(raw_text, now)


# Phase 4: Also available in tracker/utils/helpers.py
def log_ignored_message(msg_id, metadata, reason):
    """Upsert IgnoredMessage with reason for auditability and metrics."""
    IgnoredMessage.objects.update_or_create(
        msg_id=msg_id,
        defaults={
            "subject": metadata["subject"],
            "body": metadata["body"],
            "sender": metadata["sender"],
            "sender_domain": metadata["sender_domain"],
            "date": metadata["timestamp"],
            "reason": reason,
        },
    )


# Phase 4: Validation utilities moved to tracker/utils/validation.py
# Keeping wrapper functions for backward compatibility
def is_valid_company_name(name):
    """Reject company names that match known invalid prefixes from patterns.json.

    Delegates to CompanyValidator class (refactored).
    """
    return _company_validator.is_valid_company_name(name)


def normalize_company_name(name: str) -> str:
    """Normalize common subject-derived artifacts from company names.

    - Strip whitespace and trailing punctuation
    - Remove suffix fragments like "- Application ..." or trailing "Application"
    - Collapse repeated whitespace
    - Map known pseudo-companies like "Indeed Application" -> "Indeed"

    Delegates to CompanyValidator class (refactored).
    """
    return _company_validator.normalize_company_name(name)


def normalize_company_name_for_matching(name: str) -> str:
    """Normalize company name for fuzzy matching.

    Removes punctuation variations (commas, periods) and standardizes spacing
    to catch near-duplicates like "Network Designs, Inc." vs "Network Designs Inc".

    Args:
        name: Company name to normalize

    Returns:
        Normalized lowercase string for comparison

    Examples:
        "Network Designs, Inc." -> "network designs inc"
        "Network Designs Inc"   -> "network designs inc"
        "ABC Corp."             -> "abc corp"
    """
    if not name:
        return ""
    # Remove common punctuation that causes mismatches
    normalized = re.sub(r'[,.]', '', name)
    # Collapse multiple spaces to single space
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip().lower()


def get_or_create_company_iexact(name: str, defaults: dict | None = None) -> tuple:
    """Get or create a Company with case-insensitive and punctuation-insensitive name matching.

    Prevents duplicate companies that differ only in case or punctuation:
    - Case differences: 'AMERICAN SYSTEMS' vs 'American Systems'
    - Punctuation differences: 'Network Designs, Inc.' vs 'Network Designs Inc'

    Resolution order:
    1. Exact case-insensitive match on Company.name
    2. Normalized match (removes commas, periods, standardizes spacing)

    Args:
        name: Company name to look up or create
        defaults: Default values for new company creation

    Returns:
        Tuple of (company_obj, created) like get_or_create
    """
    if not name:
        return None, False

    # Try case-insensitive lookup first
    existing = Company.objects.filter(name__iexact=name).first()
    if existing:
        return existing, False

    # Try normalized match (handles punctuation differences)
    normalized_input = normalize_company_name_for_matching(name)
    for company in Company.objects.all():
        if normalize_company_name_for_matching(company.name) == normalized_input:
            logger.debug(f"[DEBUG] Normalized match: '{name}' -> existing '{company.name}'")
            return company, False

    # No match found, create new company
    if defaults is None:
        defaults = {}
    company_obj, created = Company.objects.get_or_create(
        name=name,
        defaults=defaults
    )
    return company_obj, created


def update_company_domain_and_ats(
    company_obj, sender_domain: str, company_name: str | None = None
) -> bool:
    """Update company's domain and ATS fields based on sender domain.

    This is shared logic used by both Gmail API ingestion and EML file imports.

    Args:
        company_obj: Company model instance to update
        sender_domain: Email sender domain (lowercase)
        company_name: Company name for logging (optional, uses company_obj.name if not provided)

    Returns:
        True if company was modified and saved, False otherwise
    """
    if not company_obj or not sender_domain:
        return False

    company_name = company_name or company_obj.name
    needs_save = False

    # Set the primary domain if not already set
    if not company_obj.domain:
        # First try to look up the company's domain from companies.json
        known_domain = _get_domain_for_company(company_name)
        if known_domain:
            company_obj.domain = known_domain
            needs_save = True
            logger.debug(f"Set domain for {company_name} from companies.json: {known_domain}")
        elif sender_domain and not _is_ats_domain(sender_domain):
            # Only set domain from sender if it's not an ATS domain
            company_obj.domain = sender_domain
            needs_save = True
            logger.debug(f"Set domain for {company_name}: {sender_domain}")
    # Set ATS domain if sender is an ATS and ATS field is empty
    if not company_obj.ats and sender_domain and _is_ats_domain(sender_domain):
        company_obj.ats = sender_domain
        needs_save = True
        logger.debug(f"Set ATS domain for {company_name}: {sender_domain}")
    if needs_save:
        company_obj.save()

    return needs_save


def resolve_company_alias(company_name: str) -> str:
    """Resolve company alias to canonical company name.

    Checks the CompanyAlias model to see if the provided company name
    is an alias for another company. If found, returns the canonical
    company name. Otherwise, returns the original name.

    Args:
        company_name: Company name to check for alias

    Returns:
        Canonical company name if alias found, otherwise original name
    """
    if not company_name:
        return company_name

    from tracker.models import CompanyAlias

    # Check if this name is an alias
    alias_obj = CompanyAlias.objects.filter(alias__iexact=company_name).first()
    if alias_obj:
        logger.debug(f"[ALIAS] Resolved '{company_name}' -> '{alias_obj.company}'")
        return alias_obj.company

    return company_name


def looks_like_person(name: str) -> bool:
    """Heuristic: return True if the string looks like an individual person's name.

    Criteria (intentionally conservative so we *reject* obvious person names):
    - 1–3 tokens, each starting with capital then lowercase letters only
    - No token contains digits, '&', '@', '.', or corporate suffix markers
    - Contains no common company suffix words (Inc, LLC, Corp, Company, Technologies, Systems)
    - If exactly two tokens and both are common first/last name shapes (<=12 chars) treat as person

    Delegates to CompanyValidator class (refactored).
    """
    return _company_validator.looks_like_person(name)


PARSER_VERSION = "1.0.12"

# --- ML Model Paths ---
# Message classification is handled by ml_subject_classifier.py (imported on line 27)
# Company classification is handled locally in predict_company() function
MODEL_DIR = Path(__file__).parent / "model"

# Company-level classifier artifacts (optional, used by predict_company())
_COMP_MODEL_PATH = MODEL_DIR / "company_classifier.pkl"
_COMP_VEC_PATH = MODEL_DIR / "vectorizer.pkl"
_COMP_LABELS_PATH = MODEL_DIR / "label_encoder.pkl"

# Company classifier handles company name prediction (optional)
COMPANY_CLASSIFIER = None
COMPANY_VECTORIZER = None
COMPANY_LABEL_ENCODER = None

# Load optional company classifier artifacts (non-fatal if missing)
if _COMP_MODEL_PATH.exists() and _COMP_VEC_PATH.exists() and _COMP_LABELS_PATH.exists():
    try:
        COMPANY_CLASSIFIER = joblib.load(_COMP_MODEL_PATH)
        COMPANY_VECTORIZER = joblib.load(_COMP_VEC_PATH)
        COMPANY_LABEL_ENCODER = joblib.load(_COMP_LABELS_PATH)
        logger.debug("🤖 Parser: company classifier artifacts loaded (optional).")
    except Exception:
        COMPANY_CLASSIFIER = None
        COMPANY_VECTORIZER = None
        COMPANY_LABEL_ENCODER = None




def predict_company(subject, body):
    """Predict company name using the trained ML model."""
    # Use optional company-specific classifier if available; otherwise skip
    if not (COMPANY_CLASSIFIER and COMPANY_VECTORIZER):
        return None
    text = (subject or "") + " " + (body or "")
    try:
        X = COMPANY_VECTORIZER.transform([text])
        pred = COMPANY_CLASSIFIER.predict(X)[0]
        if COMPANY_LABEL_ENCODER is not None and hasattr(
            COMPANY_LABEL_ENCODER, "inverse_transform"
        ):
            try:
                return COMPANY_LABEL_ENCODER.inverse_transform([pred])[0]
            except Exception:
                pass
        # Fallback to string conversion
        return str(pred)
    except Exception:
        return None


# Phase 4: Also available in tracker/utils/helpers.py
def should_ignore(subject, _body):
    """Return True if subject/body matches ignore patterns."""
    subj_lower = subject.lower()
    ignore_patterns = PATTERNS.get("ignore", [])
    return any(p.lower() in subj_lower for p in ignore_patterns)


def extract_metadata(service, msg_id, raw_message=None):
    """Extract subject, date, thread_id, labels, sender, sender_domain, and body text from a Gmail message."""
    body_html = ""
    if raw_message is not None:
        msg = raw_message
    else:
        msg = (
            service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        )
    headers = msg["payload"]["headers"]

    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
    date_raw = next((h["value"] for h in headers if h["name"] == "Date"), "")
    date_obj = timezone.now()
    try:
        date_obj = parsedate_to_datetime(date_raw)
        if timezone.is_naive(date_obj):
            date_obj = timezone.make_aware(date_obj)  # assume settings.TIME_ZONE
        date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        date_str = date_raw

    sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
    parsed = parseaddr(sender)
    email_addr = parsed[1] if len(parsed) == 2 else ""
    match = re.search(r"@([A-Za-z0-9.-]+)$", email_addr)
    sender_domain = match.group(1).lower() if match else ""

    # Extract "To" header for user-sent message company mapping
    to_header = next((h["value"] for h in headers if h["name"].lower() == "to"), "")

    thread_id = msg["threadId"]
    label_ids = msg.get("labelIds", [])
    labels = ",".join(label_ids)  # raw IDs unless you re-add get_label_map()

    body = ""
    parts = msg["payload"].get("parts", [])
    extracted_html = EmailBodyParser.extract_from_gmail_parts(parts)
    body = extracted_html

    # Ensure raw HTML is saved and body is converted to plain text
    # extract_from_gmail_parts prefers HTML, so if we got content, treat it as HTML
    if body and body != "Empty Body":
        body_html = body  # Save raw HTML for metadata
        try:
            # Convert to plain text using BeautifulSoup to strip tags/scripts
            soup = BeautifulSoup(body, "html.parser")
            for script in soup(["script", "style"]):
                script.extract()
            text = soup.get_text(separator=" ", strip=True)
            if text:
                body = text
        except Exception as e:
            logger.debug(f"Failed to convert HTML body to text: {e}")
            # fall back to keeping raw HTML in body if conversion fails

    for part in parts:
        mime_type = part.get("mimeType")
        data = part["body"].get("data")
        if not data:
            continue
        # decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        encoding = part.get("body", {}).get("encoding", "base64").lower()
        data = part.get("body", {}).get("data")
        decoded = ""
        if data:
            decoded = EmailBodyParser.decode_mime_part(data, encoding)

        if mime_type == "text/plain" and body == "Empty Body" and decoded:
            body = decoded.strip()
        elif mime_type == "text/html" and body != "Empty Body" and decoded:
            body_html = html.unescape(decoded)
            # also provide a plain-text fallback
            body = BeautifulSoup(body_html, "html.parser").get_text(
                separator=" ", strip=True
            )

    # Fallback if no parts
    if not body and "body" in msg["payload"]:
        data = msg["payload"]["body"].get("data")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    # Extract and analyze headers for improved classification and metadata
    header_hints = {
        "is_newsletter": False,
        "is_automated": False,
        "is_bulk": False,
        "is_noreply": False,
        "reply_to": None,
        "organization": None,
        "auto_submitted": False,
    }

    # Classification-relevant headers
    classification_headers = [
        "List-Id",
        "List-Unsubscribe",
        "Precedence",
        "X-Campaign",
        "X-Mailer",
        "X-Newsletter",
        "Auto-Submitted",
        "X-Auto-Response-Suppress",
        "Return-Path",
        "Reply-To",
        "Organization",
        "X-Entity-Ref-ID",
        "X-Sender",
    ]

    header_text = []
    for h in headers:
        h_name = h["name"]
        h_value = h["value"].lower()

        # Collect headers for classification
        if h_name in classification_headers:
            header_text.append(f"{h_name}: {h['value']}")

        # Detect newsletter indicators (avoid List-Unsubscribe false positives)
        if h_name in ("List-Id", "X-Newsletter"):
            header_hints["is_newsletter"] = True

        # Detect automated/bulk mail
        if h_name == "Precedence" and "bulk" in h_value:
            header_hints["is_bulk"] = True
        if h_name == "Auto-Submitted" and h_value != "no":
            header_hints["auto_submitted"] = True

        # Detect no-reply addresses
        if h_name == "From" and (
            "noreply" in h_value or "no-reply" in h_value or "donotreply" in h_value
        ):
            header_hints["is_noreply"] = True

        # Extract alternate reply-to for contact info
        if h_name == "Reply-To":
            header_hints["reply_to"] = h["value"]

        # Extract organization for company hints
        if h_name == "Organization":
            header_hints["organization"] = h["value"]

    # RFC 5322 compliance: Keep body and classification_text separate
    # body = actual message body (RFC 5322 compliant, no headers)
    # classification_text = body + relevant headers for ML/pattern matching
    classification_text = body
    if header_text:
        classification_text = "\n".join(header_text) + "\n\n" + body

    return {
        "thread_id": thread_id,
        "subject": subject,
        "body": body,  # RFC 5322 compliant body only
        "body_html": body_html,
        "classification_text": classification_text,  # Body + headers for classification
        "date": date_str,
        "timestamp": date_obj,
        "labels": labels,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sender": sender,
        "sender_domain": sender_domain,
        "to": to_header,  # For user-sent message company mapping
        "parser_version": PARSER_VERSION,
        "header_hints": header_hints,  # NEW: Pass header analysis to caller
    }


def extract_status_dates(body, received_date):
    """Extract status dates from body (delegates to MetadataExtractor)."""
    return _metadata_extractor.extract_status_dates(body, received_date)


def classify_message(body):
    """Classify message body into a status category based on patterns.json."""
    body_lower = body.lower()
    if any(p in body_lower for p in PATTERNS.get("rejection", [])):
        return "rejected"
    if any(p in body_lower for p in PATTERNS.get("interview", [])):
        return "interview_invite"
    if any(p in body_lower for p in PATTERNS.get("follow_up", [])):
        return "follow_up"
    if any(p in body_lower for p in PATTERNS.get("application", [])):
        return "job_application"
    if any(p in body_lower for p in PATTERNS.get("response", [])):
        return "response"
    # removed job_alert label
    return ""


def extract_organizer_from_icalendar(body):
    """Extract organizer from iCalendar (delegates to MetadataExtractor)."""
    return MetadataExtractor.extract_organizer_from_icalendar(body)


def parse_subject(subject, body="", sender=None, sender_domain=None):
    """Extract company, job title, and job ID from subject line, sender, and optionally sender domain."""

    # Reload companies.json if it has changed
    _domain_mapper.reload_if_needed()

    logger.debug(f"[DEBUG] parse_subject called with:")
    logger.debug(f"[DEBUG]   subject={subject[:60]}...")
    logger.debug(f"[DEBUG]   sender={sender}")
    logger.debug(f"[DEBUG]   sender_domain={sender_domain}")
    logger.debug(f"[DEBUG]   body_length={len(body) if body else 0}")
    RESUME_NOISE_PATTERNS = [
        r"\bresume\b",
        r"\bcv\b",
        r"\bcover letter\b",
        r"\bmuch more\b",
        r"\bnow available\b",
        r"\bgift card\b",
        r"\bcyberattack\b",
    ]

    # --- ML classification ---
    # Use ML with rule fallback
    result = predict_with_fallback(
        predict_subject_type, subject, body, threshold=0.55, sender=sender or ""
    )
    confidence = float(result.get("confidence", result.get("proba", 0.0))) if result else 0.0
    label = result["label"]

    logger.debug(f"[DEBUG parse_subject] subject='{subject[:80]}'")
    logger.debug(f"[DEBUG parse_subject] sender='{sender}'")
    logger.debug(f"[DEBUG parse_subject] sender_domain='{sender_domain}'")
    logger.debug(f"[DEBUG parse_subject] label={label}, confidence={confidence}")
    # --- Initialize variables ---
    company = ""
    job_title = ""
    job_id = ""
    ats_display_name_fallback = None  # initialize early to satisfy linters

    # --- Continue with original logic for fallback or enrichment ---
    subject_clean = subject.strip()
    # Strip common email reply/forward prefixes that interfere with company extraction
    subject_clean = re.sub(
        r"^(Re|RE|Fwd|FW|Fw):\s*", "", subject_clean, flags=re.IGNORECASE
    ).strip()
    subj_lower = subject_clean.lower()
    domain_lower = sender_domain.lower() if sender_domain else None

    # --- Check for Teams/Zoom meeting invites with iCalendar data ---
    # Extract organizer email from iCalendar ORGANIZER field (more reliable than sender for calendar invites)
    _organizer_email, organizer_domain = extract_organizer_from_icalendar(body)
    if organizer_domain and not domain_lower:
        # Use organizer domain if sender domain not available
        domain_lower = organizer_domain
        logger.debug(f"[DEBUG] Using organizer domain from iCalendar: {organizer_domain}")
    elif organizer_domain and organizer_domain != domain_lower:
        # Prefer organizer domain for meeting invites (more accurate than relay servers)
        if re.search(
            r"meeting id|passcode|join\s+(?:\S+\s+){0,3}meeting|zoom\.us|teams\.microsoft", body, re.I
        ):
            domain_lower = organizer_domain
            logger.debug(
                "[DEBUG] Overriding sender domain with organizer domain for "
                "meeting invite: %s",
                organizer_domain,
            )
    # --- Post-ML downgrade: certain subjects should not be interview_invite ---
    if label == "interview_invite":
        # Offer-related subjects (not interviews)
        offer_patterns = [
            r"\boffer\b",
            r"\bcompensation\b",
            r"\bsalary\b",
            r"\brate\b",
            r"\bnegotiat",
        ]
        is_offer_related = any(
            re.search(pattern, subj_lower) for pattern in offer_patterns
        )

        if is_offer_related:
            logger.debug("[DEBUG] Downgrading label interview_invite -> other (offer-related subject)")
            label = "other"
        # Meeting invites without "interview" keyword - only downgrade generic low-confidence meetings
        # Keep high-confidence ones as they're likely actual interview invites
        elif (
            ("meeting with" in subj_lower or "meeting invitation" in subj_lower)
            and "interview" not in subj_lower
            and confidence < 0.65
            and not (
                body and re.search(r"meeting id|passcode|join\s+(?:\S+\s+){0,3}meeting", body, re.I)
            )
        ):
            logger.debug("[DEBUG] Downgrading label interview_invite -> other (generic meeting, low confidence)")
            label = "other"

    # Upgrade: Calendar meeting invites with meeting details should be interview_invite
    # if they're from a company domain and have meeting/interview/call language
    if label in ("other", "response"):
        has_meeting_details = bool(
            re.search(
                r"meeting id|passcode|join\s+(?:\S+\s+){0,3}meeting|zoom\.us|meet\.google|teams\.microsoft",
                body,
                re.I,
            )
        )
        has_interview_language = bool(
            re.search(
                r"\b(interview|meeting|call|discussion|screen|chat)\b", subj_lower
            )
        )

        # Check if sender is from a company domain (not personal - use loaded PERSONAL_DOMAINS)
        is_company_domain = domain_lower and domain_lower not in PERSONAL_DOMAINS

        if has_meeting_details and has_interview_language and is_company_domain:
            logger.debug(f"[DEBUG] Upgrading {label} -> interview_invite (meeting invite with details)")
            label = "interview_invite"
            confidence = max(0.85, confidence)  # Boost confidence

    # PRIORITY 1: ATS domain with known sender prefix (most reliable)
    # Support subdomains of known ATS domains (e.g., talent.icims.com -> icims.com)
    is_ats_domain = _is_ats_domain(domain_lower) if domain_lower else False
    logger.debug(f"[DEBUG] is_ats_domain={is_ats_domain}, company={repr(company)}, sender={repr(sender)}")
    if not company and is_ats_domain and sender:
        company = _company_resolver.extract_from_ats_sender(sender, domain_lower) or ""
    # Job board application confirmations - extract actual employer from body
    # Works for Indeed, LinkedIn, Dice, etc. - any job board where subject contains "Application"
    if not company and body and subject:
        # Need to get sender_email for job board body extraction
        if sender:
            _, sender_email = parseaddr(sender)
        else:
            sender_email = ""
        extracted = _company_resolver.extract_from_job_board_body(
            body, subject, sender_email or "", domain_lower
        )
        if extracted:
            company = extracted
    # Generic ATS body patterns - look for company name in application confirmation text
    # Also trigger for ATS domains even without application keywords in subject
    if not company and body:
        extracted = _company_resolver.extract_from_ats_body_patterns(
            body, subject, domain_lower
        )
        if extracted:
            company = extracted
    # Save display name as a fallback candidate (defer until after subject patterns)
    ats_display_name_fallback = None
    if not company and sender:
        ats_display_name_fallback = _company_resolver.extract_from_ats_display_name(
            sender, check_known=False
        )
        if ats_display_name_fallback:
            logger.debug(
                f"[DEBUG] ATS display name candidate: {ats_display_name_fallback} "
                f"(will use if subject patterns fail)"
            )
    # PRIORITY 2: Domain mapping (direct company domains) with subdomain support
    # Skip if domain is (or is under) a known ATS platform; ATS handled separately above.
    company_from_domain = False
    if not company and domain_lower and not _is_ats_domain(domain_lower):
        mapped = _map_company_by_domain(domain_lower)
        if mapped:
            company = mapped
            company_from_domain = (
                True  # Mark that we have a reliable domain-based company
            )
            logger.debug(f"[DEBUG] Domain mapping (subdomain aware) used: {domain_lower} -> {company}")
    # PRIORITY 3: Known companies in subject
    if not company and KNOWN_COMPANIES:
        # Sort by length descending to match "Northrop Grumman" before "Northrop"
        sorted_companies = sorted(KNOWN_COMPANIES, key=len, reverse=True)
        for known in sorted_companies:
            if known in subj_lower:
                # Find original casing from known list
                for orig in _domain_mapper.company_data.get("known", []):
                    if orig.lower() == known:
                        company = orig
                        break
                if not company:  # fallback to title case
                    company = known.title()
                break

    # PRIORITY 3.5: ATS display name (if known company or clearly not a person name)
    # Use this before generic subject patterns to avoid matching locations like "at Hampton, VA"
    if not company and ats_display_name_fallback:
        validated = _company_resolver.extract_from_ats_display_name(
            sender or "", check_known=True
        )
        if validated:
            company = validated
            logger.debug(f"[DEBUG] ATS display name used (validated): {company}")

    # PRIORITY 4: Entity extraction (spaCy NER)
    if not company:
        entities = extract_entities(subject)
        company = entities.get("company", "")
        if not job_title:
            job_title = entities.get("job_title", "")

    # PRIORITY 5: Colon-prefix pattern
    if not company:
        m = re.match(r"^([A-Z][A-Za-z0-9&.\- ]+):", subject_clean)
        if m:
            company = m.group(1).strip()

    # PRIORITY 6: Regex patterns (delegated to CompanyResolver)
    # Skip subject pattern matching if we already have a reliable domain-mapped company
    # (prevents subject patterns from overwriting domain mappings with false positives)
    if not company_from_domain and not company:
        subj_company, subj_title = _company_resolver.extract_from_subject_patterns(
            subject_clean
        )
        if subj_company:
            company = subj_company
        if subj_title and not job_title:
            job_title = subj_title

    # Canonicalize: prefer known company names / aliases over raw regex captures
    if company:
        company = _company_resolver.canonicalize_company_name(company, subject_clean)

    if company and not is_valid_company_name(company):
        logger.debug(f"[DEBUG] Clearing invalid company candidate after canonicalization: {company}")
        company = ""

    # 🧼 Sanity checks
    if company and re.search(
        r"\b(CTO|Engineer|Manager|Director|Intern|Analyst)\b", company, re.I
    ):
        logger.debug(f"[DEBUG] Clearing company captured as job title: {company}")
        company = ""

    # Check if company name matches ATS sender display name (trusted source)
    ats_sender_match = False
    if company and is_ats_domain and sender:
        display_name, _ = parseaddr(sender)
        if display_name and company.lower() == display_name.lower():
            ats_sender_match = True
            logger.debug(f"[DEBUG] Company matches ATS sender display name: {company}")
    # Check if company name appears in subject with trusted pattern "with [Company]"
    subject_with_match = False
    if company and re.search(
        rf"\bwith\s+{re.escape(company)}\s*$", subject, re.IGNORECASE
    ):
        subject_with_match = True
        logger.debug(f"[DEBUG] Company matches 'with [Company]' pattern in subject: {company}")
    company_in_ats_context = bool(
        company
        and is_ats_domain
        and any(
            company.lower() in (text or "").lower()
            for text in (subject, body, sender or "")
        )
    )
    if (
        company
        and looks_like_person(company)
        and company.lower() not in {c.lower() for c in KNOWN_COMPANIES}
        and company.lower() not in {v.lower() for v in DOMAIN_TO_COMPANY.values()}
        and not company_from_domain  # Trust domain-mapped companies
        and not ats_sender_match  # Trust ATS sender display name
        and not subject_with_match  # Trust "with [Company]" subject pattern
        and not company_in_ats_context  # Trust ATS-derived companies echoed in message context
    ):
        logger.debug(f"[DEBUG] Clearing company captured as person name (post-pass): {company}")
        company = ""

    # PRIORITY 7: ATS display name fallback (only if subject patterns found nothing)
    if not company and sender:
        fallback = _company_resolver.display_name_last_resort(sender)
        if fallback:
            company = fallback

    # Sender-domain safety net for recurring ATS domains whose config mappings have drifted.
    if not company and domain_lower and (
        domain_lower == "mail.amazon.jobs"
        or domain_lower.endswith(".amazon.jobs")
        or domain_lower == "amazonaws.com"
        or domain_lower.endswith(".amazonaws.com")
    ):
        company = "Amazon"

    # Job title fallback
    if not job_title:
        title_match = re.search(
            r"job\s+(?:submission\s+for|application\s+for|title\s+is)?\s*([\w\s\-]+)",
            subject_clean,
            re.IGNORECASE,
        )
        if title_match:
            job_title = title_match.group(1).strip()
        else:
            withdraw_match = re.search(
                r"\bconfirmation\s+of\s+withdraw(?:al)?\s+from\s+(.+)$",
                subject_clean,
                re.IGNORECASE,
            )
            if withdraw_match:
                job_title = withdraw_match.group(1).strip(" .:-")

    # Job ID (delegate to MetadataExtractor)
    job_id = MetadataExtractor.extract_job_id(subject_clean)

    if label in ("job_application", "application"):
        if not job_title:
            job_title = extract_job_title_from_body(body)
        if not job_id:
            job_id = extract_application_job_id_from_body(body)

    # --- Hard-ignore check AFTER company extraction ---
    # If a valid company was found but the classifier still says noise, salvage the likely job label.
    if company and label == "noise":
        text_lower = f"{subject or ''} {body or ''}".lower()
        body_status = classify_message(body or "")

        if body_status in ("rejected", "rejection") or re.search(
            r"\banother candidate has been selected\b|\bnot to move forward\b",
            text_lower,
        ):
            label = "rejection"
            confidence = max(confidence, 0.8)
        elif body_status == "interview_invite" or re.search(
            r"\bresponse requested\b|\bprovide me with your availability\b|\bpress forward with a call\b",
            text_lower,
        ):
            label = "other"
            confidence = max(confidence, 0.75)
        elif body_status == "response":
            label = "other"
            confidence = max(confidence, 0.7)
        elif body_status == "job_application" or is_application_related(subject, body):
            label = "job_application"
            confidence = max(confidence, 0.7)

    # Hard-ignore for resume or known noise patterns (only if no valid company)
    # BUT skip ignore if body contains explicit application confirmation language
    if not company and (
        label == "noise"
        or should_ignore(subject, "")
        or any(re.search(p, subject, re.I) for p in RESUME_NOISE_PATTERNS)
    ):
        # Check body for application-related language before ignoring
        if not is_application_related(subject, body):
            return {
                "company": "",
                "job_title": "",
                "job_id": "",
                "predicted_company": "",
                "label": "noise",
                "confidence": 0.9,
                "ignore": True,
            }
        else:
            logger.debug(
                f"[DEBUG] Hard-ignore skipped: body contains application-related language"
            )

    if label == "cancelled" and not re.search(
        r"\b(cancelled|canceled|closed)\b",
        f"{subject or ''} {body or ''}",
        re.IGNORECASE,
    ):
        label = "rejection"

    # Override internal introductions: If label is "referral" or "interview_invite" but sender domain
    # matches company domain AND it's a networking introduction (not a job referral), label as "other"
    # Examples:
    #   - "I'd like to introduce you to..." = internal introduction = other
    #   - "Someone at [Company] has referred you for a job" = employee referral = referral (keep it)
    if label in ("referral", "interview_invite") and sender_domain and company:
        # Check if sender domain matches company domain
        company_domain = _map_company_by_domain(sender_domain)
        if company_domain and company_domain.lower() == company.lower():
            body_lower = (body or "").lower()
            subject_lower = (subject or "").lower()

            # Check if this is a networking introduction vs. job referral
            is_networking_intro = (
                "like to introduce" in body_lower
                or "i'd like to introduce" in body_lower
                or "would like to introduce" in body_lower
                or "want to introduce" in body_lower
                or "introducing you" in body_lower
            )

            # Check if this is explicitly a job referral (should NOT be overridden)
            is_job_referral = (
                "employee referral" in subject_lower
                or "has referred you for" in body_lower
                or "referred you for consideration" in body_lower
                or "referred you for a position" in body_lower
                or "referred you for an open position" in body_lower
                or "referred you for this position" in body_lower
            )

            # Only override if it's a networking intro and NOT a job referral
            if is_networking_intro and not is_job_referral:
                logger.debug(
                    "[DEBUG] Internal introduction detected: sender domain %s "
                    "matches company %s, overriding to 'other'",
                    sender_domain,
                    company,
                )
                label = "other"
            elif is_job_referral:
                logger.debug(
                    f"[DEBUG] Employee job referral detected: keeping as 'referral' (from {sender_domain} at {company})"
                )

    return {
        "company": normalize_company_name(company),
        "job_title": job_title,
        "job_id": job_id,
        "predicted_company": normalize_company_name(company),
        "label": label,
        "confidence": confidence,
        "ignore": False,
    }


# ====================================================================================
# Phase 7: Shared helpers extracted from ingest_message / ingest_message_from_eml
# ====================================================================================


def _check_newsletter_auto_ignore(metadata, header_hints, msg_id, stats,
                                  *, delete_existing=False, log_prefix=""):
    """Check if a message should be auto-ignored as newsletter/bulk mail.

    Returns "ignored" if the message should be skipped, or None to continue processing.
    Only auto-ignores if the message is NOT application-related (ATS systems add
    List-Unsubscribe headers even to application confirmations).

    Args:
        metadata: Message metadata dict with subject, body, classification_text, etc.
        header_hints: Dict with is_newsletter, is_bulk, is_noreply flags.
        msg_id: Gmail or EML message ID.
        stats: IngestionStats instance for counters.
        delete_existing: If True, delete any existing Message record (re-ingestion case).
        log_prefix: Prefix for log messages (e.g. "[EML]").
    """
    body = metadata.get("body", "")
    classification_text = metadata.get("classification_text", body)
    app_text = body if body and body.strip() else classification_text
    # Check full text (or larger snippet) to ensure we catch application patterns even in HTML-heavy bodies
    is_app_related = is_application_related(metadata["subject"], app_text[:10000])

    logger.debug(
        f"{log_prefix}[HEADER HINTS] is_application_related={is_app_related}, "
        f"is_newsletter={header_hints.get('is_newsletter')}, "
        f"is_bulk={header_hints.get('is_bulk')}, "
        f"is_noreply={header_hints.get('is_noreply')}"
    )

    if not is_app_related:
        if header_hints.get("is_newsletter") or (
            header_hints.get("is_bulk") and header_hints.get("is_noreply")
        ):
            logger.debug(f"{log_prefix}[HEADER HINTS] Auto-ignoring newsletter/bulk mail: {metadata['subject']}")
            if delete_existing:
                existing = Message.objects.filter(msg_id=msg_id).first()
                if existing:
                    logger.debug(f"{log_prefix}[RE-INGEST] Deleting existing Message record for newsletter: {msg_id}")
                    existing.delete()
            log_ignored_message(msg_id, metadata, reason="newsletter_headers")
            _increment_stat(stats, "total_ignored")
            return "ignored"
    elif header_hints.get("is_newsletter"):
        logger.debug(
            f"{log_prefix}[HEADER HINTS] Newsletter header found but application-related "
            f"(patterns.json), not ignoring: {metadata['subject']}"
        )
    return None


def _apply_label_overrides(result, metadata, company, parse_result, *, log_prefix=""):
    """Apply post-classification label overrides shared by both ingestion paths.

    Handles:
    1. Internal introduction override (referral/interview_invite → other)
    2. Internal recruiter override (head_hunter → other when from company domain)
    3. Personal domain override (→ noise)

    Args:
        result: ML classification result dict (modified in-place for ingest_message path).
        metadata: Message metadata dict.
        company: Resolved company name string (may be None).
        parse_result: Result from parse_subject() (dict or str).
        log_prefix: Prefix for log messages.

    Returns:
        (label, result_dict) — the final label string and (possibly modified) result dict.
    """
    label = result.get("label", "noise") if result else "noise"

    # 1. Internal introduction override
    if (
        isinstance(parse_result, dict)
        and parse_result.get("label") == "other"
        and label in ("referral", "interview_invite")
    ):
        sender_domain = metadata.get("sender_domain")
        if sender_domain and company:
            mapped_domain_company = _map_company_by_domain(sender_domain)
            if mapped_domain_company and mapped_domain_company.lower() == company.lower():
                label = "other"
                if isinstance(result, dict):
                    result = dict(result)
                    result["label"] = "other"
                logger.debug(
                    f"{log_prefix}[INTERNAL INTRODUCTION] Overriding label to 'other': "
                    f"{sender_domain} matches {company}"
                )

    # 2. Internal recruiter override
    original_ml_label = result.get("ml_label") or result.get("label") if result else None
    if original_ml_label == "head_hunter":
        sender_domain = metadata.get("sender_domain")
        if sender_domain and sender_domain not in HEADHUNTER_DOMAINS:
            mapped_company = _map_company_by_domain(sender_domain)
            if mapped_company:
                if label not in ("interview_invite", "rejection", "job_application", "offer"):
                    label = "other"
                    if isinstance(result, dict):
                        result = dict(result)
                        result["label"] = "other"
                    logger.debug(
                        f"{log_prefix}[INTERNAL RECRUITER] Overriding to 'other' for "
                        f"internal recruiter: {sender_domain} → {mapped_company}"
                    )
                else:
                    logger.debug(
                        f"{log_prefix}[INTERNAL RECRUITER] Preserving meaningful label "
                        f"'{label}' from internal recruiter: {sender_domain} → {mapped_company}"
                    )

    # 3. Personal domain override
    sender_domain = metadata.get("sender_domain", "").lower()
    if sender_domain and sender_domain in PERSONAL_DOMAINS:
        if label != "head_hunter":
            logger.debug(
                "%s[PERSONAL DOMAIN] Detected personal domain: %s, overriding to 'noise'",
                log_prefix,
                sender_domain,
            )
            label = "noise"
            if isinstance(result, dict):
                result = dict(result)
                result["label"] = "noise"
        else:
            logger.debug(
                f"{log_prefix}[PERSONAL DOMAIN] Detected personal domain: {sender_domain}, "
                f"but keeping head_hunter label"
            )

    return label, result


def _resolve_company_obj(company_name, metadata, confidence=0.0, *, log_prefix=""):
    """Resolve alias → get_or_create Company → set domain/ATS fields.

    Args:
        company_name: Raw company name string (may be None/empty).
        metadata: Message metadata dict (needs sender_domain, timestamp/date).
        confidence: ML confidence score for defaults.
        log_prefix: Prefix for log messages.

    Returns:
        (company_obj, canonical_name) — Company instance (or None) and canonical name.
    """
    _ = log_prefix
    if not company_name or not company_name.strip():
        return None, company_name

    canonical = resolve_company_alias(company_name)
    # Accept either 'timestamp' (Gmail) or 'date' (EML) for datetime field
    ts = metadata.get("timestamp") or metadata.get("date")
    company_obj, _ = get_or_create_company_iexact(
        name=canonical,
        defaults={
            "first_contact": ts,
            "last_contact": ts,
            "confidence": confidence,
        },
    )

    if company_obj:
        sender_domain = metadata.get("sender_domain", "").lower()
        update_company_domain_and_ats(company_obj, sender_domain, canonical)

    return company_obj, canonical


def _check_duplicates(msg_id, subject, metadata, company_source, stats, body_hash):
    """Check for duplicate messages using body hash, exact match, and near-duplicate detection.

    Three-tier check:
    1. Body hash match (most reliable — catches exact content duplicates)
    2. Exact timestamp match (for messages with empty/malformed bodies)
    3. Near-duplicate (within 5-second window for quick re-sends)

    Returns "ignored" if duplicate found, None otherwise.
    """
    ts = metadata["timestamp"]
    sender_domain = (
        metadata["sender"].split("@", 1)[-1] if "@" in metadata["sender"] else ""
    )
    ignored_defaults = {
        "subject": subject,
        "body": metadata["body"],
        "company_source": company_source or "",
        "sender": metadata["sender"],
        "sender_domain": sender_domain,
        "date": ts,
    }

    # First check: Body hash match
    if body_hash:
        hash_dup = Message.objects.filter(body_hash=body_hash).first()
        if hash_dup:
            logger.debug(f"⚠️ BODY HASH duplicate detected: subject='{subject[:60]}...'")
            logger.debug(f"   Existing msg_id: {hash_dup.msg_id}, New msg_id: {msg_id}")
            logger.debug(f"   Body hash: {body_hash[:16]}...")
            IgnoredMessage.objects.get_or_create(
                msg_id=msg_id,
                defaults={**ignored_defaults, "reason": "duplicate_body_hash"},
            )
            _increment_stat(stats, "total_ignored")
            return "ignored"

    # Second check: Exact timestamp match
    exact_dup = Message.objects.filter(
        subject=subject, sender=metadata["sender"], timestamp=ts
    ).first()
    if exact_dup:
        logger.debug(f"⚠️ EXACT duplicate detected: subject='{subject}', sender='{metadata['sender']}', ts={ts}")
        logger.debug(f"   Existing msg_id: {exact_dup.msg_id}, New msg_id: {msg_id}")
        IgnoredMessage.objects.get_or_create(
            msg_id=msg_id,
            defaults={**ignored_defaults, "reason": "duplicate_exact"},
        )
        _increment_stat(stats, "total_ignored")
        return "ignored"

    # Third check: Near-duplicate (within 5-second window)
    window_start = ts - timedelta(seconds=5)
    window_end = ts + timedelta(seconds=5)
    near_dup = Message.objects.filter(
        subject=subject,
        sender=metadata["sender"],
        timestamp__gte=window_start,
        timestamp__lte=window_end,
    ).first()
    if near_dup:
        logger.debug(f"⚠️ Near duplicate detected: subject='{subject}', sender='{metadata['sender']}'")
        logger.debug(f"   Existing timestamp: {near_dup.timestamp}, New timestamp: {ts}")
        logger.debug(f"   Delta: {abs((near_dup.timestamp - ts).total_seconds())} seconds")
        IgnoredMessage.objects.get_or_create(
            msg_id=msg_id,
            defaults={**ignored_defaults, "reason": "duplicate_near"},
        )
        _increment_stat(stats, "total_ignored")
        return "ignored"

    return None


def _create_or_update_thread_tracking(
    msg_id, metadata, result, company_obj, company_source,
    parsed_subject, status_dates, status, reviewed, stats
):
    """Create or update ThreadTracking records after Message creation.

    Handles:
    - ML-derived date fallbacks (rejection/interview/prescreen dates)
    - ThreadTracking creation for applications, interviews, prescreens
    - ThreadTracking updates for existing records (rejection/interview updates)
    - Fallback company recovery from Message when company_obj is missing
    - Headhunter guard (skip ThreadTracking for headhunter sources)
    - TF-IDF job-title matching for rejections without matching threads
    """
    ml_label = result.get("label") if result else None
    rejection_date_final = status_dates["rejection_date"]
    interview_date_final = status_dates["interview_date"]

    # Treat both 'rejection' and 'rejected' as rejection outcomes
    # Also treat 'cancelled' as a rejection (position was cancelled)
    if not rejection_date_final and ml_label in ("rejected", "rejection", "cancelled"):
        rejection_date_final = timezone.localtime(metadata["timestamp"]).date()
        logger.debug(f"✓ Set rejection_date from ML label: {rejection_date_final}")
    # If ML indicates an interview and confidence is sufficient, set a conservative interview_date
    if not interview_date_final and ml_label and "interview" in str(ml_label).lower():
        try:
            ml_conf = float(result.get("confidence", 0.0)) if result else 0.0
        except Exception:
            ml_conf = 0.0
        if ml_conf >= 0.7:
            interview_date_final = timezone.localtime(metadata["timestamp"]).date()
            logger.debug(f"✓ Set interview_date from ML label (message date): {interview_date_final}")
    # If ML indicates a prescreen, set prescreen_date from message timestamp
    prescreen_date_final = None
    if ml_label == "prescreen":
        prescreen_date_final = timezone.localtime(metadata["timestamp"]).date()
        logger.debug(f"✓ Set prescreen_date from ML label: {prescreen_date_final}")

    try:
        message_obj = Message.objects.get(msg_id=msg_id)

        # Guard: If company_obj is missing but message was created, log it
        if not company_obj:
            logger.debug(f"⚠️  Warning: Message created without company_obj for {msg_id}")
            logger.debug(f"   Subject: {metadata.get('subject', '')[:60]}")
            logger.debug(f"   ML Label: {ml_label}")
            logger.debug(f"   ThreadTracking creation will be skipped")
        if not message_obj:
            logger.debug(f"⚠️  Warning: Could not retrieve Message object for {msg_id}")
            logger.debug(f"   ThreadTracking creation will be skipped")

        if company_obj and message_obj:
            _update_thread_tracking_for_company(
                msg_id, metadata, result, company_obj, company_source, parsed_subject,
                status, reviewed, stats, ml_label,
                rejection_date_final, interview_date_final, prescreen_date_final
            )
        else:
            _fallback_thread_tracking_creation(
                msg_id, metadata, result, company_obj, company_source,
                parsed_subject, status, reviewed, stats, ml_label,
                rejection_date_final, interview_date_final, prescreen_date_final
            )

    except Exception as e:
        logger.debug(f"❌ Failed to create ThreadTracking: {e}", exc_info=True)
        _increment_stat(stats, "total_skipped")


def _update_thread_tracking_for_company(
    msg_id, metadata, result, company_obj, company_source, parsed_subject,
    status, reviewed, stats, ml_label,
    rejection_date_final, interview_date_final, prescreen_date_final
):
    """Create/update ThreadTracking when both company and message are available."""
    sender_domain = (metadata.get("sender_domain") or "").lower()
    skip_application_creation = _is_headhunter_source(
        sender_domain, company_obj, HEADHUNTER_DOMAINS, ml_label=ml_label
    )

    if skip_application_creation:
        logger.debug("↩️ Skipping ThreadTracking creation for headhunter source/company")
        return

    if ml_label in ("job_application", "cancelled"):
        _create_thread_tracking_for_application(
            msg_id, metadata, result, company_obj, company_source, parsed_subject,
            status, reviewed, stats, ml_label,
            rejection_date_final, interview_date_final, prescreen_date_final
        )
    else:
        _update_existing_thread_tracking(
            metadata, result, company_obj, company_source, parsed_subject,
            stats, ml_label,
            rejection_date_final, interview_date_final, prescreen_date_final
        )


def _create_thread_tracking_for_application(
    msg_id, metadata, result, company_obj, company_source, parsed_subject,
    status, reviewed, stats, ml_label,
    rejection_date_final, interview_date_final, prescreen_date_final
):
    """Create ThreadTracking for application/interview/prescreen/cancelled labels.

    Handles the case where multiple distinct job_application messages share the
    same Gmail thread_id (e.g., identical ATS confirmation subjects causing Gmail
    to group them). When a second application arrives on an existing thread, a
    separate ThreadTracking is created using the message's msg_id as thread_id.
    """
    tt_defaults = {
        "company": company_obj,
        "company_source": company_source,
        "job_title": parsed_subject.get("job_title", ""),
        "job_id": parsed_subject.get("job_id", ""),
        "status": status,
        "sent_date": timezone.localtime(metadata["timestamp"]).date(),
        "rejection_date": rejection_date_final,
        "interview_date": interview_date_final,
        "prescreen_date": prescreen_date_final,
        "ml_label": ml_label,
        "ml_confidence": (
            float(result.get("confidence", 0.0)) if result else 0.0
        ),
        "reviewed": reviewed,
        "cancelled": ml_label == "cancelled",
        "withdrew": ml_label == "withdrew",
    }

    cross_thread_match = None
    if ml_label == "job_application":
        cross_thread_match = _find_existing_application_by_identity(
            company_obj,
            parsed_subject.get("job_title", ""),
            parsed_subject.get("job_id", ""),
            exclude_thread_ids={metadata["thread_id"], msg_id},
            sent_date=timezone.localtime(metadata["timestamp"]).date(),
        )
    if cross_thread_match is not None:
        _update_existing_application_dates(
            cross_thread_match,
            company_obj,
            company_source,
            result,
            metadata,
            ml_label,
            rejection_date_final,
            interview_date_final,
            prescreen_date_final,
            parsed_subject,
        )
        logger.debug(
            "✓ Reused existing ThreadTracking (id=%s) for duplicate application acknowledgement "
            "across threads (msg_id=%s, thread_id=%s)",
            cross_thread_match.pk,
            msg_id,
            metadata["thread_id"],
        )
        logger.debug("Stats: ignored++ (duplicate application acknowledgement)")
        _increment_stat(stats, "total_ignored")
        return

    application_obj, created = ThreadTracking.objects.get_or_create(
        thread_id=metadata["thread_id"],
        defaults=tt_defaults,
    )

    if not created:
        parsed_job_title = parsed_subject.get("job_title", "")
        parsed_job_id = parsed_subject.get("job_id", "")
        # Check if this is a DIFFERENT application message on the same Gmail thread.
        # Gmail groups messages with identical subjects into one thread, but each
        # may be a separate job application (e.g., two roles at the same company
        # with the same ATS confirmation subject).
        if (
            ml_label == "job_application"
            and application_obj.ml_label == "job_application"
            and msg_id != metadata["thread_id"]
        ):
            # This msg_id differs from the thread_id, so it's a distinct message.
            # Check if we already created a TT for this specific message.
            existing_for_msg = ThreadTracking.objects.filter(
                thread_id=msg_id
            ).exists()
            same_application = _should_enrich_existing_application(
                application_obj,
                company_obj,
                parsed_job_title,
                parsed_job_id,
            )
            if not existing_for_msg and not same_application:
                tt_defaults["sent_date"] = timezone.localtime(
                    metadata["timestamp"]
                ).date()
                new_tt = ThreadTracking.objects.create(
                    thread_id=msg_id,
                    **tt_defaults,
                )
                logger.debug(
                    f"✓ Created separate ThreadTracking (id={new_tt.pk}) for "
                    f"additional application on same Gmail thread "
                    f"(msg_id={msg_id}, original thread_id={metadata['thread_id']})"
                )
                _increment_stat(stats, "total_inserted")
                return

        _update_existing_application_dates(
            application_obj, company_obj, company_source, result, metadata,
            ml_label, rejection_date_final, interview_date_final, prescreen_date_final,
            parsed_subject,
        )

    if created:
        logger.debug("Stats: inserted++ (new application)")
        _increment_stat(stats, "total_inserted")
    else:
        logger.debug("Stats: ignored++ (duplicate application)")
        _increment_stat(stats, "total_ignored")


def _update_existing_thread_tracking(
    metadata, result, company_obj, company_source, parsed_subject,
    _stats, ml_label,
    rejection_date_final, interview_date_final, prescreen_date_final
):
    """Update existing ThreadTracking for non-application labels (rejection, offer, etc.)."""
    try:
        application_obj = ThreadTracking.objects.get(
            thread_id=metadata["thread_id"]
        )
        if ml_label == "offer" and company_obj:
            offer_target = _find_existing_offer_application(
                company_obj,
                metadata,
                parsed_subject,
            )
            if offer_target is not None:
                application_obj = offer_target
        _update_existing_application_dates(
            application_obj, company_obj, company_source, result, metadata,
            ml_label, rejection_date_final, interview_date_final, prescreen_date_final,
            parsed_subject,
        )
    except ThreadTracking.DoesNotExist:
        # No ThreadTracking with this thread_id - for rejections, try to find by company
        if ml_label in ("rejected", "rejection", "cancelled", "withdrew") and company_obj:
            _find_and_update_rejection_by_company(
                metadata, company_obj, parsed_subject,
                rejection_date_final, ml_label
            )
        elif ml_label in ("interview_invite", "prescreen", "offer") and company_obj:
            if ml_label == "offer":
                application_obj = _find_existing_offer_application(
                    company_obj,
                    metadata,
                    parsed_subject,
                )
            else:
                application_obj = _find_existing_milestone_application(
                    company_obj,
                    metadata,
                    parsed_subject,
                )
            if application_obj is not None:
                _update_existing_application_dates(
                    application_obj,
                    company_obj,
                    company_source,
                    result,
                    metadata,
                    ml_label,
                    rejection_date_final,
                    interview_date_final,
                    prescreen_date_final,
                    parsed_subject,
                )
            else:
                logger.debug(
                    "ℹ️ No application anchor found for %s milestone; manual creation required",
                    ml_label,
                )
        else:
            logger.debug(
                "ℹ️ No existing ThreadTracking for this thread; not creating "
                "because this is not a job_application email"
            )


def _update_existing_application_dates(
    application_obj, company_obj, company_source, _result, metadata,
    ml_label, rejection_date_final, interview_date_final, prescreen_date_final,
    parsed_subject=None
):
    """Update dates/company on an existing ThreadTracking record."""
    updated = False
    parsed_subject = parsed_subject or {}
    if application_obj.company != company_obj and company_obj is not None:
        application_obj.company = company_obj
        application_obj.company_source = company_source
        updated = True
        logger.debug(f"✓ Updated application company: {company_obj.name}")
    parsed_job_title = parsed_subject.get("job_title", "")
    parsed_job_id = parsed_subject.get("job_id", "")
    if parsed_job_title and not application_obj.job_title:
        application_obj.job_title = parsed_job_title
        updated = True
    if parsed_job_id and not application_obj.job_id:
        application_obj.job_id = parsed_job_id
        updated = True
    if ml_label in ("rejected", "rejection", "cancelled", "withdrew"):
        if not application_obj.rejection_date:
            application_obj.rejection_date = rejection_date_final
            application_obj.status = "rejected"
            updated = True
        # Check for cancelled/withdrew position indicators in email text even if rejection_date was already set
        if is_cancelled_position(metadata.get("subject", ""), metadata.get("body", "")) or ml_label == "cancelled":
            if not application_obj.cancelled:
                application_obj.cancelled = True
                updated = True
        if is_withdrawn_position(metadata.get("subject", ""), metadata.get("body", "")) or ml_label == "withdrew":
            if not application_obj.withdrew:
                application_obj.withdrew = True
                updated = True
    if not application_obj.interview_date and ml_label == "interview_invite":
        application_obj.interview_date = interview_date_final
        updated = True
    if not application_obj.prescreen_date and ml_label == "prescreen":
        application_obj.prescreen_date = prescreen_date_final
        updated = True
    if not application_obj.offer_date and ml_label == "offer":
        application_obj.offer_date = timezone.localtime(metadata["timestamp"]).date()
        application_obj.status = "offer"
        updated = True
    if updated:
        application_obj.save()
        logger.debug("✓ Updated existing application with ML-derived dates")


def _find_and_update_rejection_by_company(
    metadata, company_obj, parsed_subject, rejection_date_final, ml_label=None
):
    """Find ThreadTracking by company (TF-IDF matching) and update with rejection."""
    job_title = parsed_subject.get("job_title", "") if isinstance(parsed_subject, dict) else ""
    if not job_title:
        job_title = extract_rejection_job_title(
            metadata.get("subject", ""), metadata.get("body", "")
        )

    include_rejected = ml_label in ("withdrew", "cancelled")
    existing_tt = find_best_matching_application(
        company_obj, job_title, metadata.get("subject", ""), include_rejected=include_rejected
    )
    if existing_tt:
        if not existing_tt.rejection_date:
            existing_tt.rejection_date = rejection_date_final
        existing_tt.status = "rejected"
        if is_cancelled_position(metadata.get("subject", ""), metadata.get("body", "")) or ml_label == "cancelled":
            existing_tt.cancelled = True
            logger.debug("✓ Detected 'cancelled' in email text, setting cancelled=True")
        if is_withdrawn_position(metadata.get("subject", ""), metadata.get("body", "")) or ml_label == "withdrew":
            existing_tt.withdrew = True
            logger.debug("✓ Detected 'withdrew' in email text, setting withdrew=True")
        existing_tt.save()
        logger.debug(
            "✓ Updated existing ThreadTracking for %s (job: '%s') with "
            "rejection_date=%s",
            company_obj.name,
            existing_tt.job_title,
            rejection_date_final,
        )
        return existing_tt
    else:
        logger.debug(
            "ℹ️ No existing ThreadTracking found for %s to update with rejection",
            company_obj.name,
        )
        return None


def _fallback_thread_tracking_creation(
    msg_id, metadata, result, company_obj, company_source,
    parsed_subject, status, reviewed, stats, ml_label,
    rejection_date_final, interview_date_final, prescreen_date_final
):
    """Attempt fallback ThreadTracking creation when company_obj or message_obj is missing."""
    if ml_label in ("job_application", "interview_invite", "prescreen") and not company_obj:
        logger.debug("⚠️  job_application/interview_invite/prescreen without company - attempting fallback")
        try:
            fallback_msg = Message.objects.get(msg_id=msg_id)
            if fallback_msg.company:
                company_obj = fallback_msg.company
                company_source = fallback_msg.company_source
                logger.debug(f"✓ Retrieved company from Message: {company_obj.name}")
                _application_obj, created = ThreadTracking.objects.get_or_create(
                    thread_id=metadata["thread_id"],
                    defaults={
                        "company": company_obj,
                        "company_source": company_source,
                        "job_title": parsed_subject.get("job_title", ""),
                        "job_id": parsed_subject.get("job_id", ""),
                        "status": status,
                        "sent_date": timezone.localtime(metadata["timestamp"]).date(),
                        "rejection_date": rejection_date_final,
                        "interview_date": interview_date_final,
                        "prescreen_date": prescreen_date_final,
                        "ml_label": ml_label,
                        "ml_confidence": (
                            float(result.get("confidence", 0.0))
                            if result
                            else 0.0
                        ),
                        "reviewed": reviewed,
                        "cancelled": ml_label == "cancelled",
                        "withdrew": ml_label == "withdrew",
                    },
                )
                if created:
                    logger.debug(
                        f"✓ Created ThreadTracking via fallback for {company_obj.name}"
                    )
            else:
                logger.debug("⚠️  Message exists but also has no company - cannot create ThreadTracking")
        except Message.DoesNotExist:
            logger.debug("⚠️  Fallback failed: Message not found")
    logger.debug("Stats: skipped++ (missing company/message)")
    _increment_stat(stats, "total_skipped")


def _handle_reingest(
    existing, msg_id, metadata, result, company_obj, company_source, company,
    skip_company_assignment, parsed_subject, stats
):
    """Handle re-ingestion of an existing message.

    Updates the existing Message record with new ML classification, company resolution,
    and propagates changes to ThreadTracking. Preserves manual review state unless
    OVERWRITE_REVIEWED env var is set.

    Handles:
    - User-sent message detection (initiated vs reply/forward)
    - Personal domain noise classification
    - Headhunter enforcement
    - Forwarded message detection
    - Auto-review criteria
    - Reviewed message protection (snapshot/restore)
    - Company domain/ATS updates
    - ThreadTracking date propagation

    Returns "skipped" always.
    """
    # Snapshot original fields so we can avoid overwriting reviewed messages
    orig_ml_label = existing.ml_label
    orig_confidence = getattr(existing, "confidence", None)
    orig_company = getattr(existing, "company", None)
    orig_company_source = getattr(existing, "company_source", None)
    orig_reviewed = getattr(existing, "reviewed", False)

    overwrite_reviewed = os.environ.get("OVERWRITE_REVIEWED", "").lower() in (
        "1", "true", "yes",
    )
    logger.debug(f"Updating existing message: {msg_id}")
    logger.debug("Stats: skipped++ (re-ingest)")

    # Extract user email info for user-sent detection
    user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip().lower()
    sender_full = (metadata.get("sender") or "").lower()
    sender_email = sender_full
    if "<" in sender_full and ">" in sender_full:
        sender_email = sender_full[
            sender_full.index("<") + 1 : sender_full.index(">")
        ]

    subject = metadata.get("subject", "")
    is_reply_or_forward = subject.lower().startswith(("re:", "fwd:", "fw:"))

    # Determine recipient domain (used in multiple branches)
    recipient_email = metadata.get("to", "").lower()
    if not recipient_email:
        body = metadata.get("body", "")
        m = re.search(
            r"^To:\s*([\w.\-+]+@[\w.\-]+)", body, re.MULTILINE | re.IGNORECASE
        )
        if m:
            recipient_email = m.group(1).strip().lower()
    recipient_domain = (
        recipient_email.split("@", 1)[-1] if "@" in recipient_email else ""
    )

    # CRITICAL: Only override label for user-initiated messages, NOT replies/forwards
    if (
        user_email
        and sender_email.startswith(user_email)
        and not is_reply_or_forward
    ):
        _reingest_user_initiated(
            existing, metadata, result, company_obj, recipient_domain
        )
    elif user_email and sender_email.startswith(user_email) and is_reply_or_forward:
        _reingest_user_reply(
            existing, metadata, result, company_obj, company_source,
            skip_company_assignment, recipient_domain
        )
    elif skip_company_assignment:
        existing.company = None
        existing.company_source = ""
    elif company_obj:
        existing.company = company_obj
        existing.company_source = company_source

    # Headhunter enforcement for re-ingestion
    if result:
        sender_domain = (metadata.get("sender_domain") or "").lower()
        if _is_headhunter_source(sender_domain, company_obj, HEADHUNTER_DOMAINS):
            logger.debug(f"[RE-INGEST HEADHUNTER] Forcing label to head_hunter (was: {result.get('label')})")
            result["label"] = "head_hunter"
            existing.company = None
            existing.company_source = "headhunter_domain"

    # Forwarded message detection for re-ingestion
    subject_for_check = metadata.get("subject", "").strip()
    if (
        re.match(r"^(Fwd|FW|Fw):\s*", subject_for_check, re.IGNORECASE)
        and company_obj
    ):
        logger.debug(
            "[RE-INGEST FORWARD] Subject starts with Fwd/FW and company resolved: %s",
            company_obj.name,
        )
        logger.debug(
            "[RE-INGEST FORWARD] Original label: %s, overriding to 'other'",
            result.get("label") if result else "N/A",
        )
        if result:
            result["label"] = "other"
            result["confidence"] = 0.95

    duplicate_application_ack = bool(
        result
        and result.get("label") in ("job_application", "application")
        and _is_duplicate_application_acknowledgement(
            msg_id,
            metadata,
            company_obj,
            parsed_subject,
        )
    )
    if duplicate_application_ack and result:
        result = dict(result)
        result["label"] = "other"
        result["confidence"] = max(float(result.get("confidence", 0.0)), 0.95)

    # Update label/confidence for non-user messages
    if result and not (user_email and sender_email.startswith(user_email)):
        existing.ml_label = result["label"]
        existing.confidence = result["confidence"]
        existing.classification_source = result.get("fallback") or "ml"

    # Auto-review criteria
    if not existing.reviewed and (
        result
        and result.get("confidence", 0.0) >= 0.85
        and result.get("label") not in ("noise", "other")
        and company_obj is not None
        and is_valid_company(company)
    ):
        if os.environ.get("SUPPRESS_AUTO_REVIEW", "").lower() not in (
            "1", "true", "yes",
        ):
            existing.reviewed = True

    # Restore originals if message was reviewed and overwrite not requested
    # EXCEPTION: Allow rejection/withdrew to override job_application for reviewed messages
    # — a rejection/withdrawal is a definitive status change that must always be applied.
    new_label = result.get("label") if result else None
    rejection_upgrade = (
        new_label in ("rejection", "rejected", "cancelled", "withdrew")
        and orig_ml_label in ("job_application", "other", "response", "rejection", "rejected", None)
    )
    if orig_reviewed and not overwrite_reviewed and not rejection_upgrade:
        existing.ml_label = orig_ml_label
        if orig_confidence is not None:
            existing.confidence = orig_confidence
        existing.company = orig_company
        existing.company_source = orig_company_source
    elif rejection_upgrade:
        logger.debug(
            f"[RE-INGEST] Allowing rejection upgrade for reviewed message: "
            f"{orig_ml_label} → {new_label}"
        )

    # Update company domain/ATS fields
    if existing.company:
        sender_domain = metadata.get("sender_domain", "").lower()
        company_name = existing.company.name if existing.company else ""
        update_company_domain_and_ats(existing.company, sender_domain, company_name)

    existing.save()

    # Propagate ml_label to ThreadTracking
    try:
        from tracker.utils import propagate_message_label_to_thread
        propagate_message_label_to_thread(existing)
    except Exception:
        pass

    # Update ThreadTracking dates during re-ingestion
    _update_thread_tracking_on_reingest(
        metadata,
        result,
        company_obj,
        stats,
        parsed_subject,
    )

    _increment_stat(stats, "total_skipped")

    # Log reingest activity to tracker log file
    final_label = existing.ml_label or (result.get("label") if result else "unknown")
    final_confidence = existing.confidence if existing.confidence is not None else 0.0
    company_name = existing.company.name if existing.company else "N/A"
    changed = final_label != orig_ml_label
    log_console(
        f"  → Re-ingested [{msg_id}]: label={final_label}"
        f"{' (was ' + str(orig_ml_label) + ')' if changed else ''}"
        f", confidence={final_confidence:.2f}"
        f", company={company_name}"
    )

    return {
        "status": "re-ingested",
        "label": final_label,
        "confidence": float(final_confidence),
        "company": company_name,
        "source": existing.company_source or "none",
        "changed": changed,
        "prev_label": orig_ml_label,
    }


def _reingest_user_initiated(existing, metadata, result, _company_obj, recipient_domain):
    """Handle re-ingestion of user-initiated (non-reply) messages."""
    ml_predicted_label = result.get("label") if result else None
    ml_confidence = float(result.get("confidence", 0)) if result else 0

    if ml_predicted_label == "noise" and ml_confidence > 0.5:
        existing.ml_label = "noise"
        existing.confidence = ml_confidence
        logger.debug(f"[RE-INGEST] User-initiated message classified as noise by ML (confidence={ml_confidence:.2f})")
    else:
        if recipient_domain:
            mapped_company = _map_company_by_domain(recipient_domain)
            if mapped_company:
                canonical_company = resolve_company_alias(normalize_company_name(mapped_company))
                company_obj_local, _ = get_or_create_company_iexact(
                    name=canonical_company,
                    defaults={
                        "first_contact": metadata["timestamp"],
                        "last_contact": metadata["timestamp"],
                    },
                )
                existing.company = company_obj_local
                existing.company_source = "user_sent_to_company"
        existing.ml_label = "other"
        existing.confidence = 1.0
        logger.debug(
            "[RE-INGEST] User-initiated message: label='other', company=%s",
            existing.company.name if existing.company else "None",
        )


def _reingest_user_reply(
    existing, _metadata, result, company_obj, company_source,
    skip_company_assignment, recipient_domain
):
    """Handle re-ingestion of user reply/forward messages."""
    if recipient_domain in PERSONAL_DOMAINS:
        existing.ml_label = "noise"
        existing.confidence = 0.85
        existing.company = None
        existing.company_source = ""
        logger.debug(f"[RE-INGEST] User reply to personal domain ({recipient_domain}), classified as noise")
    else:
        if result:
            existing.ml_label = result["label"]
            existing.confidence = result["confidence"]
            existing.classification_source = result.get("fallback") or "ml"
        if skip_company_assignment and existing.reviewed:
            existing.company = None
            existing.company_source = ""
        elif company_obj:
            existing.company = company_obj
            existing.company_source = company_source
        logger.debug(
            "[RE-INGEST] User reply/forward to job domain updated: label=%s, "
            "company=%s",
            result["label"] if result else "N/A",
            company_obj.name if company_obj else "None",
        )


def _update_thread_tracking_on_reingest(metadata, result, company_obj, _stats, parsed_subject=None):
    """Update ThreadTracking dates during re-ingestion.

    Handles:
    - Setting rejection_date for rejection/cancelled labels
    - Body-based cancellation detection via is_cancelled_position()
    - Cross-thread rejection propagation via TF-IDF matching when the
      thread_id-matched TT appears to be a spurious record (no job_title)
    """
    ml_label = result.get("label") if result else None
    if not (company_obj and ml_label and ml_label != "head_hunter"):
        return
    try:
        app = ThreadTracking.objects.filter(
            thread_id=metadata["thread_id"]
        ).first()
        logger.debug(
            "[Re-ingest] Looking for Application with thread_id=%s, found: %s",
            metadata["thread_id"],
            app is not None,
        )
        if app:
            logger.debug(
                "[Re-ingest] App ml_label=%s, rejection_date=%s, "
                "ml_label_param=%s",
                app.ml_label,
                app.rejection_date,
                ml_label,
            )
            updated = False
            parsed_subject = parsed_subject or {}

            # Update company if different (and valid)
            if company_obj and app.company != company_obj:
                app.company = company_obj
                # If we have a source, use it, otherwise keep existing
                # (Can't easily plumb company_source here without changing signature,
                # but company update is the priority)
                updated = True
                logger.debug(f"✓ Updated ThreadTracking company during re-ingest: {company_obj.name}")

            parsed_job_title = parsed_subject.get("job_title", "")
            parsed_job_id = parsed_subject.get("job_id", "")
            if parsed_job_title and not app.job_title:
                app.job_title = parsed_job_title
                updated = True
            if parsed_job_id and not app.job_id:
                app.job_id = parsed_job_id
                updated = True

            matched_other_application = False


            if (
                ml_label in ("rejected", "rejection", "cancelled", "withdrew")
                and not app.job_title
            ):
                rejection_date = timezone.localtime(metadata["timestamp"]).date()
                logger.debug(
                    f"[Re-ingest] TT id={app.pk} has no job_title — "
                    f"attempting targeted cross-thread match for {company_obj.name}"
                )
                matched_target = _find_and_update_rejection_by_company(
                    metadata, company_obj, {}, rejection_date, ml_label
                )
                matched_other_application = bool(
                    matched_target and matched_target.pk != app.pk
                )

            if ml_label in ("rejected", "rejection", "cancelled", "withdrew"):
                if not app.rejection_date:
                    if matched_other_application:
                        logger.debug(
                            f"[Re-ingest] Skipping rejection update on placeholder TT id={app.pk}; "
                            "matched another application by role title"
                        )
                    else:
                        rejection_date = timezone.localtime(metadata["timestamp"]).date()
                        app.rejection_date = rejection_date
                        updated = True
                        logger.debug(f"✓ Set rejection_date during re-ingest: {app.rejection_date}")

                if not matched_other_application:
                    # Body-based cancellation detection
                    if is_cancelled_position(
                        metadata.get("subject", ""), metadata.get("body", "")
                    ) or ml_label == "cancelled":
                        if not app.cancelled:
                            app.cancelled = True
                            updated = True
                            logger.debug("✓ Detected 'cancelled' in email text during re-ingest")
                    if is_withdrawn_position(
                        metadata.get("subject", ""), metadata.get("body", "")
                    ) or ml_label == "withdrew":
                        if not app.withdrew:
                            app.withdrew = True
                            updated = True
                            logger.debug("✓ Detected 'withdrew' in email text during re-ingest")
            if (
                not app.interview_date
                and ml_label == "interview_invite"
            ):
                try:
                    ml_conf = (
                        float(result.get("confidence", 0.0)) if result else 0.0
                    )
                except Exception:
                    ml_conf = 0.0
                if ml_conf >= 0.7:
                    app.interview_date = timezone.localtime(metadata["timestamp"]).date()
                    updated = True
                    logger.debug(f"✓ Set interview_date during re-ingest: {app.interview_date}")
            if not app.ml_label or app.ml_label != ml_label:
                app.ml_label = ml_label
                app.ml_confidence = (
                    float(result.get("confidence", 0.0)) if result else 0.0
                )
                updated = True
            if updated:
                app.save()
                logger.debug("✓ Updated Application during re-ingest")
                log_console(
                    f"  → ThreadTracking updated: ml_label={app.ml_label}"
                    f", rejection_date={app.rejection_date}"
                    f", cancelled={app.cancelled}"
                    f", thread_id={metadata['thread_id']}"
                )

        else:
            # No TT for this thread_id — for rejections, try TF-IDF matching
            if ml_label in ("rejected", "rejection", "cancelled", "withdrew") and company_obj:
                rejection_date = timezone.localtime(metadata["timestamp"]).date()
                logger.debug(
                    f"[Re-ingest] No TT for thread_id={metadata['thread_id']}"
                    f" — attempting TF-IDF match for {company_obj.name}"
                )
                _find_and_update_rejection_by_company(
                    metadata, company_obj, {}, rejection_date, ml_label
                )
            else:
                logger.debug(f"[Re-ingest] No Application found for thread_id={metadata['thread_id']}")
    except Exception as e:
        logger.debug(f"Warning: Could not update Application during re-ingest: {e}")


def _build_final_record(
    msg_id, metadata, result, company, company_source,
    parsed_subject, status_dates, status, follow_up_str, labels_str,
    subject, body, stats
):
    """Assemble final record, log unresolved companies, and insert/update application.

    Handles:
    - Record dict assembly for applications table
    - Unresolved company logging (UnresolvedCompany model)
    - Early ignore for missing company/title/id
    - Pattern-based ignore check

    Returns:
        "ignored" if message should be skipped, or a dict with insertion details.
    """
    record = {
        "thread_id": metadata["thread_id"],
        "company": company,
        "predicted_company": parsed_subject.get("predicted_company", ""),
        "job_title": parsed_subject.get("job_title", ""),
        "job_id": parsed_subject.get("job_id", ""),
        "first_sent": metadata["date"],
        "response_date": status_dates["response_date"],
        "follow_up_dates": follow_up_str,
        "rejection_date": status_dates["rejection_date"],
        "interview_date": status_dates["interview_date"],
        "status": status,
        "labels": labels_str,
        "subject": metadata["subject"],
        "sender": metadata["sender"],
        "sender_domain": metadata["sender_domain"],
        "last_updated": metadata["last_updated"],
        "company_source": company_source,
    }

    # Log unresolved companies for manual review
    if not company and not should_ignore(subject, body):
        UnresolvedCompany.objects.update_or_create(
            msg_id=msg_id,
            defaults={
                "subject": metadata["subject"],
                "body": metadata["body"],
                "sender": metadata["sender"],
                "sender_domain": metadata["sender_domain"],
                "timestamp": metadata["timestamp"],
            },
        )
        logger.debug(f"Logged unresolved company for manual review: {msg_id}")

    # Check if record has enough data to be useful
    if not record["company"] and not record["job_title"] and not record["job_id"]:
        reason = "unclassified"
        if not metadata["body"]:
            reason = "missing_body"
        elif metadata["body"] and not record["company"]:
            reason = "missing_company"
        logger.debug(f"Ignored due to: {reason} -> {metadata['subject']}")
        logger.debug("Stats: ignored++ (unclassified)")
        log_ignored_message(msg_id, metadata, reason=reason)
        _increment_stat(stats, "total_ignored")
        return "ignored"

    record["company_job_index"] = build_company_job_index(
        record.get("company", ""), record.get("job_title", ""), record.get("job_id", "")
    )

    logger.debug(f"company: {record['company']}")
    logger.debug(f"job_title: {record['job_title']}")
    logger.debug(f"job_id: {record['job_id']}")
    logger.debug(f"company_source: {record['company_source']}")
    logger.debug(f"company_job_index: {record['company_job_index']}")

    if should_ignore(metadata["subject"], metadata["body"]):
        logger.debug(f"Ignored by pattern: {metadata['subject']}")
        logger.debug("Stats: ignored++ (pattern ignore)")
        log_ignored_message(msg_id, metadata, reason="pattern_ignore")
        _increment_stat(stats, "total_ignored")
        return "ignored"

    logger.debug(f"Logged: {metadata['subject']}")

    final_label = result.get("label") if result else "unknown"
    confidence = float(result.get("confidence", 0.0)) if result else 0.0
    return {
        "status": "inserted",
        "label": final_label,
        "confidence": confidence,
        "company": company or "N/A",
        "source": company_source or "none",
    }


def ingest_message(service, msg_id, raw_message=None):
    """Ingest a single Gmail message by id into the local database.

    Pipeline: metadata extraction → ML+rules classification → company resolution →
    Message/Application ORM writes → ingestion stats and dedupe checks.
    Returns one of: 'inserted' | 'skipped' | 'ignored' | None on failure.
    """
    # Reload company data if companies.json has been modified
    _reload_domain_map_if_needed()

    stats = get_stats()

    try:
        metadata = extract_metadata(service, msg_id, raw_message=raw_message)
        body = metadata["body"]  # RFC 5322 compliant body (no headers)
        classification_text = metadata.get(
            "classification_text", body
        )  # Body + headers for classification
        result = None  #  Prevent UnboundLocalError

        # --- PATCH: Skip and log blank/whitespace-only bodies ---
        if not body or not body.strip():
            logger.debug(f"[BLANK BODY] Skipping message {msg_id}: {metadata.get('subject','(no subject)')}")
            logger.debug("Stats: ignored++ (blank body)")
            log_ignored_message(msg_id, metadata, reason="blank_body")
            _increment_stat(stats, "total_ignored")
            return {"status": "ignored", "reason": "blank_body"}

    except Exception as e:
        logger.debug(f"Failed to extract data for {msg_id}: {e}")
        return

    # Use header hints to improve classification
    header_hints = metadata.get("header_hints", {})

    # Auto-ignore newsletters and bulk mail (shared helper)
    newsletter_result = _check_newsletter_auto_ignore(
        metadata, header_hints, msg_id, stats, delete_existing=True
    )
    if newsletter_result:
        return {"status": "ignored", "reason": "newsletter_headers"}

    # --- PATCH: User-sent message to company domain ---
    user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip().lower()
    sender_email = metadata.get("sender", "").lower()
    # Robust recipient extraction: try 'to', else parse from body for forwarded messages
    recipient_email = ""
    if metadata.get("to"):
        recipient_email = metadata.get("to", "").lower()
    else:
        # Try to extract 'To:' from body for forwarded messages
        body = metadata.get("body", "")
        m = re.search(r"^To:\s*([\w.\-+]+@[\w.\-]+)", body, re.MULTILINE)
        if m:
            recipient_email = m.group(1).strip().lower()
    # Extract just the email address from "Display Name <email@domain.com>" format
    if "<" in recipient_email and ">" in recipient_email:
        match = re.search(r"<([^>]+)>", recipient_email)
        if match:
            recipient_email = match.group(1).strip().lower()
    recipient_domain = recipient_email.split("@")[-1] if "@" in recipient_email else ""
    company = ""
    company_source = ""
    # Determine if this is a user-sent message and its context
    subject = metadata.get("subject", "")
    is_reply_or_forward = subject.lower().startswith(("re:", "fwd:", "fw:"))

    # Check ML classification to detect noise BEFORE overriding
    ml_predicted_label = result.get("label") if result else None
    ml_confidence = float(result.get("confidence", 0)) if result else 0

    # Only force 'other' for user-INITIATED messages that are NOT noise
    # Allow ML to classify user replies/forwards, and even user-initiated noise (personal emails)
    if user_email and sender_email.startswith(user_email):
        # IGNORE user messages to/from personal domains (personal emails, not job-related)
        if recipient_domain in PERSONAL_DOMAINS or (
            is_reply_or_forward and recipient_domain in PERSONAL_DOMAINS
        ):
            logger.debug(f"[USER EMAIL] Ignoring user message to personal domain: {recipient_domain}")
            # Delete if re-ingesting
            existing = Message.objects.filter(msg_id=msg_id).first()
            if existing:
                existing.delete()

            log_ignored_message(msg_id, metadata, reason="user_personal_email")
            _increment_stat(stats, "total_ignored")
            return {"status": "ignored", "reason": "user_personal_email"}

        # If ML classifies as noise with reasonable confidence, trust it
        if ml_predicted_label == "noise" and ml_confidence > 0.5:
            logger.debug(
                "[PATCH] User message classified as noise by ML "
                "(confidence=%.2f), keeping noise label.",
                ml_confidence,
            )
            # Don't override - let it stay as noise
        elif not is_reply_or_forward:
            # User-INITIATED, non-noise message → likely job application outreach
            mapped_company = None
            if recipient_domain:
                mapped_company = _map_company_by_domain(recipient_domain)
                if mapped_company:
                    company = mapped_company
                    company_source = "user_sent_to_company"
            # Force label to 'other' for user-INITIATED job outreach
            if isinstance(result, dict):
                result = dict(result)
                result["label"] = "other"
                if mapped_company:
                    result["company"] = mapped_company
                    result["predicted_company"] = mapped_company
            logger.debug(
                "[PATCH] User-initiated message: label set to 'other', company "
                "set to %s.",
                mapped_company if mapped_company else "N/A",
            )
        else:
            # User reply/forward to job-related domains → use ML classification
            logger.debug(
                "[PATCH] User reply/forward to job domain, using ML "
                "classification: %s",
                ml_predicted_label,
            )
    parsed_subject = (
        parse_subject(
            metadata["subject"],
            metadata.get("body", ""),
            sender=metadata.get("sender"),
            sender_domain=metadata.get("sender_domain"),
        )
        or {}
    )
    # If user-sent logic matched, override company and force label 'other' in result
    if company and company_source == "user_sent_to_company":
        parsed_subject["company"] = company
        parsed_subject["predicted_company"] = company
        # Patch: override result label and company before persistence
        if isinstance(result, dict):
            result = dict(result)
            result["label"] = "other"
            result["company"] = company
            result["predicted_company"] = company
        logger.debug(
            "[PATCH] Overriding label to 'other' and company to %s for "
            "user-sent message.",
            company,
        )
    # If parse_subject detected internal introduction and overrode label to 'other', apply to result
    if (
        parsed_subject.get("label") == "other"
        and isinstance(result, dict)
        and result.get("label") in ("referral", "interview_invite")
    ):
        sender_domain = metadata.get("sender_domain")
        if sender_domain:
            from_company = parsed_subject.get("company") or parsed_subject.get(
                "predicted_company"
            )
            if from_company:
                mapped_domain_company = _map_company_by_domain(sender_domain)
                if (
                    mapped_domain_company
                    and mapped_domain_company.lower() == from_company.lower()
                ):
                    result = dict(result)  # Create mutable copy
                    result["label"] = "other"
                    logger.debug(
                        "[INTERNAL INTRODUCTION] Overriding result label to "
                        "'other' for internal introduction: %s matches %s",
                        sender_domain,
                        from_company,
                    )
    if parsed_subject.get("ignore"):
        logger.debug(f"Ignored by ML: {metadata['subject']}")
        logger.debug("Stats: ignored++ (ML ignore)")
        # Check if this message already exists in Message table (re-ingestion case)
        existing = Message.objects.filter(msg_id=msg_id).first()
        if existing:
            logger.debug(f"[RE-INGEST] Deleting existing Message record for ignored message: {msg_id}")
            existing.delete()

        ignore_reason = parsed_subject.get("ignore_reason", "ml_ignore")
        log_ignored_message(
            msg_id,
            metadata,
            reason=ignore_reason,
        )
        _increment_stat(stats, "total_ignored")
        return {"status": "ignored", "reason": ignore_reason}

    status = classify_message(body)
    # Pass actual datetime object for date arithmetic (fixes timedelta concat on str)
    status_dates = extract_status_dates(
        body, metadata["timestamp"]
    )  # was metadata['date'] (string)

    def to_date(value):
        """Normalize mixed date inputs to date objects.

        Accepts:
          - datetime/date objects (returned directly as date)
          - string timestamps in common formats (not auto-parsed — prefer structured dates)
        Returns None on failure or when value is a string (preserve caller semantics).
        """
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):  # already a date
            return value
        # Preserve None for string inputs; callers may prefer raw strings or None
        # rather than attempting to guess formats here.
        return None

    status_dates = {
        "response_date": to_date(status_dates.get("response_date")),
        "rejection_date": to_date(status_dates.get("rejection_date")),
        "interview_date": to_date(status_dates.get("interview_date")),
        "follow_up_dates": status_dates.get("follow_up_dates", []),
    }

    # Normalize follow_up_dates and labels to strings
    follow_up_raw = status_dates.get("follow_up_dates", [])
    follow_up_str = (
        ", ".join(follow_up_raw)
        if isinstance(follow_up_raw, list)
        else str(follow_up_raw)
    )

    labels_raw = metadata.get("labels", [])
    labels_str = (
        ", ".join(labels_raw) if isinstance(labels_raw, list) else str(labels_raw)
    )

    logger.debug(f"Inserting message: {metadata['subject']}")

    subject = metadata["subject"]
    sender = metadata.get("sender", "")
    # Use the rule-aware wrapper so authoritative regex rules take precedence
    # over the raw ML prediction during ingestion/re-ingestion. This ensures
    # that matches from `rule_label` (via `predict_with_fallback`) are
    # respected when deciding final labels stored in the DB.
    # Use classification_text (body + headers) for classification
    classification_text = metadata.get("classification_text", body)
    result = predict_with_fallback(
        predict_subject_type,
        subject,
        classification_text,
        threshold=0.55,
        sender=sender,
    )

    # Apply internal recruiter override - check if ML originally predicted head_hunter
    # Only override to 'other' for generic recruiting spam, preserve meaningful labels
    if isinstance(result, dict):
        ml_label = result.get("ml_label") or result.get(
            "label"
        )  # Check original ML prediction
        final_label = result.get("label")

        if ml_label == "head_hunter":
            sender_domain = metadata.get("sender_domain")
            if sender_domain and sender_domain not in HEADHUNTER_DOMAINS:
                mapped_company = _map_company_by_domain(sender_domain)
                if mapped_company:
                    # Check if this is a meaningful application lifecycle event
                    # For job_application: only preserve if it has ATS markers (real application confirmation)
                    # Otherwise it's likely just a generic email mentioning "job submission" in subject
                    if final_label == "job_application":
                        # Check for ATS markers to confirm it's a real application
                        # Use classification_text to check headers for ATS markers
                        classification_text_lower = (classification_text or "").lower()
                        ats_markers = [
                            "workday",
                            "myworkday",
                            "taleo",
                            "icims",
                            "indeed",
                            "list-unsubscribe",
                            "one-click",
                        ]
                        has_ats_marker = any(
                            marker in classification_text_lower
                            for marker in ats_markers
                        )

                        if not has_ats_marker:
                            # No ATS markers - this is generic recruiter communication, not real application
                            result = dict(result)
                            result["label"] = "other"
                            logger.debug(
                                "[INTERNAL RECRUITER] Overriding job_application "
                                "to 'other' (no ATS markers) for internal "
                                "recruiter: %s -> %s",
                                sender_domain,
                                mapped_company,
                            )
                        else:
                            logger.debug(
                                "[INTERNAL RECRUITER] Preserving job_application "
                                "(has ATS markers) from internal recruiter: %s "
                                "-> %s",
                                sender_domain,
                                mapped_company,
                            )
                    elif final_label not in ("interview_invite", "rejection", "offer"):
                        # Override generic labels to 'other'
                        result = dict(result)
                        result["label"] = "other"
                        logger.debug(
                            "[INTERNAL RECRUITER] Overriding %s to 'other' for "
                            "internal recruiter from company domain: %s -> %s",
                            final_label,
                            sender_domain,
                            mapped_company,
                        )
                    else:
                        logger.debug(
                            "[INTERNAL RECRUITER] Preserving meaningful label "
                            "'%s' from internal recruiter: %s -> %s",
                            final_label,
                            sender_domain,
                            mapped_company,
                        )

    # Check if sender domain is in personal domains list - override to noise
    # EXCEPT for head_hunter (headhunters legitimately use personal domains)
    sender_domain = metadata.get("sender_domain", "").lower()
    if sender_domain and sender_domain in PERSONAL_DOMAINS:
        final_label = result.get("label") if result else None
        if final_label != "head_hunter":
            logger.debug(
                "[PERSONAL DOMAIN] Detected personal domain: %s, overriding "
                "to 'noise'",
                sender_domain,
            )
            result = dict(result)
            result["label"] = "noise"
        else:
            logger.debug(
                f"[PERSONAL DOMAIN] Detected personal domain: {sender_domain}, but keeping head_hunter label"
            )

    # Apply downgrade/upgrade logic for consistency with parse_subject
    subject_clean = re.sub(
        r"^(Re|RE|Fwd|FW|Fw):\s*", "", subject, flags=re.IGNORECASE
    ).strip()
    subj_lower = subject_clean.lower()

    if result and result.get("label") == "interview_invite":
        # Offer-related subjects should not be interview_invite
        offer_patterns = [
            r"\boffer\b",
            r"\bcompensation\b",
            r"\bsalary\b",
            r"\brate\b",
            r"\bnegotiat",
        ]
        if any(re.search(pattern, subj_lower) for pattern in offer_patterns):
            logger.debug(
                "[RE-INGEST] Downgrading interview_invite -> other "
                "(offer-related: %s)",
                subject,
            )
            result["label"] = "other"

        # Classification adjustments should be driven by patterns.json, not hard-coded here.
        # We intentionally avoid duplicating application-confirmation logic in code.

    # Upgrade: Calendar meeting invites with meeting details should be interview_invite
    # if they're from a company and have meeting/interview/call language
    # NOTE: Do NOT include job_application here — application confirmations
    # (e.g. "Thanks for applying") must never be upgraded to interview_invite,
    # especially when the body contains resume text with incidental words like
    # "meeting" or "joint" that can trigger false positives.
    if result and result.get("label") in ("other", "response"):
        has_meeting_details = bool(
            re.search(
                (
                    r"meeting id|passcode|join\s+(?:\S+\s+){0,3}meeting|"
                    r"zoom\.us|meet\.google|teams\.microsoft|ms teams|"
                    r"microsoft teams"
                ),
                body,
                re.I,
            )
        )
        # Check subject AND body for interview language (sometimes subject is generic like "Job Submission")
        has_interview_language = bool(
            re.search(
                r"\b(interview|meeting|call|discussion|screen|chat)\b", subj_lower
            )
        ) or bool(
            re.search(
                r"\b(interview|meeting|call|discussion|screen|chat)\b", body, re.I
            )
        )

        # Check if sender is from a company domain (not personal - use loaded PERSONAL_DOMAINS)
        sender_domain = metadata.get("sender_domain", "").lower()
        is_company_domain = sender_domain and sender_domain not in PERSONAL_DOMAINS

        if has_meeting_details and has_interview_language and is_company_domain:
            logger.debug(
                "[RE-INGEST] Upgrading %s -> interview_invite (meeting invite "
                "with details: %s)",
                result["label"],
                subject,
            )
            result["label"] = "interview_invite"
            result["confidence"] = max(
                0.85, result.get("confidence", 0.85)
            )  # Boost confidence

    # --- NEW LOGIC: Robust company extraction order ---
    # Add guard: skip company assignment for noise and head_hunter labels
    label_guard = result.get("label") if result else None
    skip_company_assignment = label_guard in ("noise", "head_hunter")
    company_obj = None
    # For user-sent messages, use recipient-mapped company if available
    # Extract just the email address from "Display Name <email@domain.com>" format
    sender_email_only = sender_email
    if "<" in sender_email and ">" in sender_email:
        match = re.search(r"<([^>]+)>", sender_email)
        if match:
            sender_email_only = match.group(1).strip().lower()
    if user_email and sender_email_only.startswith(user_email):
        mapped_company = None
        if recipient_domain:
            mapped_company = _map_company_by_domain(recipient_domain)
        if mapped_company:
            company = mapped_company
            company_source = "user_sent_to_company"
        else:
            company = ""
            company_source = "user_sent_to_company"
        # Force label to 'other' UNLESS already set to 'noise' by personal domain override
        if result:
            current_label = result.get("label")
            if current_label != "noise":
                result["label"] = "other"
            if mapped_company:
                result["company"] = mapped_company
                result["predicted_company"] = mapped_company
        if company:
            # Resolve alias to canonical company name
            company = resolve_company_alias(company)
            company_obj, _ = get_or_create_company_iexact(
                name=company,
                defaults={
                    "first_contact": metadata["timestamp"],
                    "last_contact": metadata["timestamp"],
                    "confidence": (
                        float(result.get("confidence", 0.0)) if result else 0.0
                    ),
                },
            )
            if company_obj and not company_obj.domain and recipient_domain:
                company_obj.domain = recipient_domain
                company_obj.save()
        # Skip normal company extraction for user-sent messages
        skip_company_assignment = True

    # Use Organization header as company fallback if needed
    org_fallback = None
    if header_hints.get("organization"):
        org = header_hints["organization"]
        if not looks_like_person(org):
            org_fallback = org
            logger.debug(f"[HEADER HINTS] Organization header available: {org}")
    if not skip_company_assignment:
        sender_domain = metadata.get("sender_domain", "").lower()
        is_headhunter = sender_domain in HEADHUNTER_DOMAINS
        is_job_board = sender_domain in JOB_BOARD_DOMAINS
        is_personal = sender_domain in PERSONAL_DOMAINS

        # Personal domain check - completely ignore these messages UNLESS they're user-sent
        # (User-sent messages from personal domains like gmail.com going to recruiters are legitimate)
        # Extract just the email address from "Display Name <email@domain.com>" format
        sender_email_only = sender_email
        if "<" in sender_email and ">" in sender_email:
            match = re.search(r"<([^>]+)>", sender_email)
            if match:
                sender_email_only = match.group(1).strip().lower()
        is_user_sent = user_email and sender_email_only.startswith(user_email)
        if is_personal and not is_user_sent:
            logger.debug(f"[PERSONAL DOMAIN] Ignoring message from personal domain: {sender_domain}")
            # Delete existing message if re-ingesting
            existing = Message.objects.filter(msg_id=msg_id).first()
            if existing:
                logger.debug(f"[PERSONAL DOMAIN] Deleting existing message: {msg_id}")
                existing.delete()

            # Log as ignored
            log_ignored_message(msg_id, metadata, reason="personal_domain")
            _increment_stat(stats, "total_ignored")
            return "ignored"

        # Job-board messages should be treated as noise (similar to job_alert)
        # EXCEPT application confirmations where user applied through the job board
        if is_job_board:
            # Check if this is an application confirmation (subject contains "Application")
            is_application_confirmation = subject and re.search(
                r"\bapplication\b", subject, re.IGNORECASE
            )

            if not is_application_confirmation:
                logger.debug(f"[JOB BOARD] Marking message from job-board domain as noise: {sender_domain}")
                if not result:
                    result = {"label": "noise", "confidence": 1.0}
                else:
                    result["label"] = "noise"
                    result["confidence"] = 1.0
                skip_company_assignment = True
            else:
                logger.debug(f"[JOB BOARD] Application confirmation detected, will extract company from body")
                # Don't skip company assignment for application confirmations
                skip_company_assignment = False

        # 0. Headhunter domain check (highest priority)
        if is_headhunter:
            company = None
            company_source = "headhunter_domain"
            logger.debug(f"Headhunter domain detected: {sender_domain} → (no company)")
        # 1. Domain mapping (applies to all non-headhunter domains, including ATS)
        #    Some ATS send confirmations from vendor domains; we still want
        #    to resolve to the hiring company's domain mapping when available.
        if not company and sender_domain:
            mapped = _map_company_by_domain(sender_domain)
            if mapped:
                company = mapped
                company_source = "domain_mapping"
                logger.debug(f"Domain mapping (subdomain aware) used: {sender_domain} → {company}")
        # 1.5. USAStaffing.gov job board special case - extract agency/organization from body
        if not company and sender_domain == "usastaffing.gov":
            # Extract plain text body for pattern matching
            body_plain = body
            try:
                if body and ("<html" in body.lower() or "<style" in body.lower()):
                    soup = BeautifulSoup(body, "html.parser")
                    for tag in soup(["style", "script"]):
                        tag.decompose()
                    body_plain = soup.get_text(separator=" ", strip=True)
            except Exception:
                body_plain = body

            # Look for "at the ORGANIZATION, in the Department of" pattern
            if body_plain:
                usastaffing_pattern = re.search(
                    r"at the\s+([A-Z][A-Za-z0-9\s&.,'-]+?),\s+in the Department of",
                    body_plain,
                    re.IGNORECASE,
                )
                if usastaffing_pattern:
                    extracted = usastaffing_pattern.group(1).strip()
                    if extracted and is_valid_company_name(extracted):
                        company = normalize_company_name(extracted)
                        company_source = "usastaffing_body_extraction"
                        logger.debug(f"USAStaffing organization extraction: {company}")
        # 1.6. Indeed job board special case - extract actual employer from body
        if not company and sender_domain == "indeed.com":
            # Check for Indeed Apply confirmation pattern (using configurable sender patterns)
            sender_lower = metadata.get("sender", "").lower()
            job_board_sender_match = any(
                pattern in sender_lower
                for pattern in _domain_mapper.job_board_sender_patterns
            )
            if "Indeed Application:" in subject or job_board_sender_match:
                # Extract plain text body for pattern matching
                body_plain = body
                try:
                    if body and ("<html" in body.lower() or "<style" in body.lower()):
                        soup = BeautifulSoup(body, "html.parser")
                        for tag in soup(["style", "script"]):
                            tag.decompose()
                        body_plain = soup.get_text(separator=" ", strip=True)
                except Exception:
                    body_plain = body

                # Look for "The following items were sent to COMPANY" pattern
                if body_plain:
                    indeed_pattern = re.search(
                        (
                            r"(?:the following items were sent to|about your "
                            r"application.*?with)\s+([A-Z][A-Za-z0-9\s&.,'-]+?)"
                            r"(?:\s+(?:and|About|Your application|Resume|Cover "
                            r"letter|\n|$))"
                        ),
                        body_plain,
                        re.IGNORECASE,
                    )
                    if indeed_pattern:
                        extracted = indeed_pattern.group(1).strip()
                        # Clean up common trailing words
                        extracted = re.sub(
                            r"\s+(and|About|Your)$", "", extracted, flags=re.IGNORECASE
                        ).strip()
                        if extracted and is_valid_company_name(extracted):
                            company = normalize_company_name(extracted)
                            company_source = "indeed_body_extraction"
                            logger.debug(f"Indeed employer extraction: {company}")
        # 2. Subject/body parse (if not resolved by domain or Indeed extraction)
        # Skip for headhunters - they should not have a company assigned
        if not company and not is_headhunter:
            parsed_company = parsed_subject.get("company", "") or ""
            if parsed_company and is_valid_company_name(parsed_company):
                company = normalize_company_name(parsed_company)
                company_source = "subject_parse"
                logger.debug(f"Subject/body parse used: {company}")
        # 3. ML/NER extraction (if still unresolved)
        # Skip for headhunters - they should not have a company assigned
        if not company and not is_headhunter:
            try:
                predicted = predict_company(subject, body)
                if (
                    predicted
                    and predicted.lower() not in {"job_application", "noise"}
                    and is_valid_company_name(predicted)
                ):
                    # Extra guard: require presence in subject/body (plain text) to avoid artifacts like 'Font'
                    body_plain = body
                    try:
                        if body and (
                            "<html" in body.lower() or "<style" in body.lower()
                        ):
                            soup = BeautifulSoup(body, "html.parser")
                            for tag in soup(["style", "script"]):
                                tag.decompose()
                            body_plain = soup.get_text(separator=" ", strip=True)
                    except Exception:
                        body_plain = body

                    if predicted.lower() in subject.lower() or (
                        body_plain and predicted.lower() in body_plain.lower()
                    ):
                        company = normalize_company_name(predicted)
                        company_source = "ml_prediction"
                        logger.debug(f"ML prediction used: {predicted}")
                    else:
                        logger.debug(
                            f"ML prediction discarded (not in subject/body): {predicted}"
                        )
            except NameError:
                logger.debug(" ML prediction function not available.")
        # 4. Regex/body fallback (if still unresolved)
        # Strip HTML tags from body to avoid matching CSS @import, @media, etc.
        if not company:
            # Remove HTML tags and CSS to get plain text
            body_plain = body
            if body and ("<html" in body.lower() or "<style" in body.lower()):
                try:
                    soup = BeautifulSoup(body, "html.parser")
                    # Remove style and script tags entirely
                    for tag in soup(["style", "script"]):
                        tag.decompose()
                    body_plain = soup.get_text(separator=" ", strip=True)
                except Exception:
                    body_plain = body  # fallback to original if parsing fails

            # Now search in plain text body
            at_match = re.search(
                r"(?:position|role|opportunity)\s+@\s*([A-Za-z][\w\s&\-]+?)(?=[\W]|$)",
                body_plain,
                flags=re.IGNORECASE,
            )
            if at_match:
                company = at_match.group(1).strip().title()
                company_source = "body_at_symbol"
                logger.debug(f"'@' symbol match used: {company}")
        if not company:
            body_match = re.search(
                (
                    r"(?:apply(?:ing)? to|application to|interest in|position "
                    r"at|role at|opportunity with)\s+([A-Z][\w\s&\-]+)"
                ),
                body,
                re.IGNORECASE,
            )
            if body_match:
                company = body_match.group(1).strip()
                company_source = "body_regex"
                logger.debug(f" Body regex used: {company}")
        # 5. Sender name fallback (rare, last resort)
        if not company:
            sender_name = metadata.get("sender", "").split("<")[0].strip().lower()
            for known in KNOWN_COMPANIES:
                if known.lower() in sender_name:
                    company = known
                    company_source = "sender_name_match"
                    logger.debug(f" Sender name match: {sender_name} → {company}")
                    break

        # 6. Organization header fallback
        if not company and org_fallback:
            company = org_fallback
            company_source = "organization_header"
            logger.debug(f"[HEADER HINTS] Using Organization header: {company}")
        # 7. Final fallback
        if not company:
            company_source = "unresolved"

        # Normalize casing for known companies
        if company:
            for known in KNOWN_COMPANIES_CASED:
                if company.lower() == known.lower():
                    company = known
                    break
        # Sanity check: does subject contain a conflicting company name?
        subject_lower = metadata["subject"].lower()
        if company and company.lower() not in subject_lower:
            for known in KNOWN_COMPANIES:
                if known.lower() in subject_lower and known.lower() != company.lower():
                    print(
                        f"Subject mentions different company: {known} vs resolved {company}"
                    )
                    break

    confidence = float(result.get("confidence", 0.0)) if result else 0.0

    # For user-sent messages, guarantee company_obj and label 'other' are set using recipient domain
    if user_email and sender_email.startswith(user_email):
        mapped_company = None
        if recipient_domain:
            mapped_company = _map_company_by_domain(recipient_domain)
        if mapped_company:
            company = normalize_company_name(mapped_company)
            # Resolve alias to canonical company name
            company = resolve_company_alias(company)
            company_obj, _ = get_or_create_company_iexact(
                name=company,
                defaults={
                    "first_contact": metadata["timestamp"],
                    "last_contact": metadata["timestamp"],
                    "confidence": confidence,
                },
            )
            if company_obj and not company_obj.domain:
                company_obj.domain = recipient_domain
                company_obj.save()
                logger.debug(f"Set domain for {company}: {recipient_domain}")
        else:
            company_obj = None
        # Always force label to 'other'
        if result:
            result["label"] = "other"
            if mapped_company:
                result["company"] = mapped_company
                result["predicted_company"] = mapped_company
    else:
        # Skip company assignment if message is labeled as noise
        if company and not skip_company_assignment:
            # Final normalization before persistence
            company = normalize_company_name(company)
            # Resolve alias, create company, set domain/ATS (shared helper)
            company_obj, company = _resolve_company_obj(
                company, metadata, confidence
            )
        elif skip_company_assignment:
            logger.debug(f"Skipping company assignment for {label_guard} message")

    confidence = result.get("confidence", 0.0) if result else 0.0
    logger.debug(f"Final company: {company}")
    logger.debug(f"company_obj: {company_obj}")
    logger.debug(f"ML label: {result.get('label') if result else 'unknown'}")
    logger.debug(f"confidence: {confidence}")

    #
    # Re-ingest logic: update existing message if already in DB
    #
    existing = Message.objects.filter(msg_id=msg_id).first()
    if existing:
        return _handle_reingest(
            existing, msg_id, metadata, result, company_obj, company_source, company,
            skip_company_assignment, parsed_subject, stats
        )

    reviewed = (
        result
        and result.get("confidence", 0.0) >= 0.85
        and result.get("label") != "noise"
        and company_obj is not None
        and is_valid_company(company)
    )
    # or whatever threshold you trust
    if not reviewed:
        logger.debug(
            "Not reviewed: confidence=%.2f, label=%s, company=%s",
            result.get("confidence", 0.0),
            result.get("label"),
            company,
        )

    # ✅ Enhanced duplicate detection (extracted helper)
    body = metadata["body"]
    normalized_body = re.sub(r"\s+", " ", body or "").strip()
    body_hash = hashlib.sha256(normalized_body.encode("utf-8")).hexdigest()

    dup_result = _check_duplicates(msg_id, subject, metadata, company_source, stats, body_hash)
    if dup_result:
        return dup_result

    # Headhunter enforcement: ALL messages from headhunter domains/companies should be labeled head_hunter
    duplicate_application_ack = False
    thread_tracking_result = dict(result) if result else None
    if result:
        sender_domain = (metadata.get("sender_domain") or "").lower()
        if _is_headhunter_source(sender_domain, company_obj, HEADHUNTER_DOMAINS):
            logger.debug(f"[HEADHUNTER ENFORCEMENT] Forcing label to head_hunter (was: {result.get('label')})")
            result["label"] = "head_hunter"

        # Forwarded message detection: if subject starts with "Fwd:" or "FW:" and company is resolved,
        # automatically label as "other" to prevent counting forwards as actual interview invites/applications
        subject_for_check = metadata.get("subject", "").strip()
        if (
            re.match(r"^(Fwd|FW|Fw):\s*", subject_for_check, re.IGNORECASE)
            and company_obj
        ):
            logger.debug(f"[FORWARD DETECTION] Subject starts with Fwd/FW and company resolved: {company_obj.name}")
            logger.debug(f"[FORWARD DETECTION] Original label: {result.get('label')}, overriding to 'other'")
            result["label"] = "other"
            result["confidence"] = 0.95  # High confidence for forward detection

        duplicate_application_ack = bool(
            result.get("label") in ("job_application", "application")
            and _is_duplicate_application_acknowledgement(
                msg_id,
                metadata,
                company_obj,
                parsed_subject,
            )
        )
        if duplicate_application_ack:
            result = dict(result)
            result["label"] = "other"
            result["confidence"] = max(float(result.get("confidence", 0.0)), 0.95)

        # ✅ Now safe to insert Message with enriched company
        # Use safe fallback for body_html because unit tests' mocked metadata may omit it
        # For user-INITIATED messages (not replies/forwards), use company_obj from recipient domain and label 'other'
        if (
            user_email
            and sender_email.startswith(user_email)
            and not is_reply_or_forward
        ):
            mapped_company = None
            if recipient_domain:
                mapped_company = _map_company_by_domain(recipient_domain)
            if mapped_company:
                # Resolve alias to canonical company name
                canonical_company = resolve_company_alias(normalize_company_name(mapped_company))
                company_obj, _ = get_or_create_company_iexact(
                    name=canonical_company,
                    defaults={
                        "first_contact": metadata["timestamp"],
                        "last_contact": metadata["timestamp"],
                        "confidence": (
                            float(result.get("confidence", 0.0)) if result else 0.0
                        ),
                    },
                )
            Message.objects.create(
                msg_id=msg_id,
                thread_id=metadata["thread_id"],
                subject=subject,
                sender=metadata["sender"],
                body=metadata.get("body", ""),
                body_html=metadata.get("body_html", metadata.get("body", "")),
                body_hash=body_hash,
                timestamp=metadata["timestamp"],
                ml_label="other",
                confidence=result["confidence"] if result else 0.0,
                classification_source="rule",
                reviewed=reviewed,
                company=company_obj if mapped_company else None,
                company_source="user_sent_to_company",
            )
        else:
            Message.objects.create(
                msg_id=msg_id,
                thread_id=metadata["thread_id"],
                subject=subject,
                sender=metadata["sender"],
                body=metadata.get("body", ""),
                body_html=metadata.get("body_html", metadata.get("body", "")),
                body_hash=body_hash,
                timestamp=metadata["timestamp"],
                ml_label=result["label"],
                confidence=result["confidence"],
                classification_source=result.get("fallback") or "ml",
                reviewed=reviewed,
                company=company_obj,
                company_source=company_source,
            )
    # ✅ Create or update ThreadTracking record using extracted helper
    _create_or_update_thread_tracking(
        msg_id, metadata,
        thread_tracking_result if result and duplicate_application_ack else result,
        company_obj, company_source,
        parsed_subject, status_dates, status, reviewed, stats
    )

    # Refresh stats before printing
    if hasattr(stats, "refresh_from_db"):
        stats.refresh_from_db()
    logger.debug(
        f"Stats updated: inserted={stats.total_inserted}, ignored={stats.total_ignored}, skipped={stats.total_skipped}"
    )

    # ✅ Build final record and insert/update application
    return _build_final_record(
        msg_id, metadata, result, company, company_source,
        parsed_subject, status_dates, status, follow_up_str, labels_str,
        subject, body, stats
    )


# Note: Company data loading moved to DomainMapper class
# Access via _domain_mapper attributes for backward compatibility
ATS_DOMAINS = _domain_mapper.ats_domains
HEADHUNTER_DOMAINS = set(_domain_mapper.headhunter_domains)
JOB_BOARD_DOMAINS = set(_domain_mapper.job_board_domains)
KNOWN_COMPANIES = _domain_mapper.known_companies
KNOWN_COMPANIES_CASED = _domain_mapper.known_companies_cased
DOMAIN_TO_COMPANY = _domain_mapper.domain_to_company
company_data = _domain_mapper.company_data


# Note: Domain map reloading moved to DomainMapper class


def _reload_domain_map_if_needed():
    """Reload all company data if companies.json has changed (delegates to DomainMapper)."""
    global DOMAIN_TO_COMPANY, ATS_DOMAINS, HEADHUNTER_DOMAINS, JOB_BOARD_DOMAINS
    global KNOWN_COMPANIES, KNOWN_COMPANIES_CASED, company_data

    _domain_mapper.reload_if_needed()

    # Update global references for backward compatibility
    DOMAIN_TO_COMPANY = _domain_mapper.domain_to_company
    ATS_DOMAINS = _domain_mapper.ats_domains
    HEADHUNTER_DOMAINS = set(_domain_mapper.headhunter_domains)
    JOB_BOARD_DOMAINS = set(_domain_mapper.job_board_domains)
    KNOWN_COMPANIES = _domain_mapper.known_companies
    KNOWN_COMPANIES_CASED = _domain_mapper.known_companies_cased
    company_data = _domain_mapper.company_data


def extract_job_title_from_body(body: str | None) -> str:
    """Extract job title from rejection email body text.

    Rejection emails often contain the job title in the body rather than the subject.
    Common patterns:
      - "the position of <TITLE> has been filled"
      - "Re: Req #1234-<TITLE>"
      - "regarding the <TITLE> position"
      - "for the <TITLE> role"
      - "application for <TITLE>"

    Args:
        body: Plain text or HTML body of the email

    Returns:
        Extracted job title string, or empty string if none found
    """
    if not body:
        return ""

    # Clean HTML entities and tags for pattern matching
    text = re.sub(r'&nbsp;', ' ', body)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Ordered list of patterns - first match wins
    patterns = [
        # "the position of X has been filled/closed"
        r'(?:the\s+)?position\s+of\s+(.+?)\s+has\s+(?:been\s+)?(?:filled|closed)',
        # "Req #1234-Title" or "Req #1234 - Title" (stops at Dear, sentence end, or </tag)
        r'Req\s*#?\d+\s*[-–]\s*(.+?)(?:\s*(?:Dear|</|\.|$|\n))',
        # "apply to the R12345 Title role" (Capital One / ATS pattern)
        r'apply\s+to\s+(?:the\s+)?(?:R\d+\s+)?(.+?)\s+(?:role|position)\b',
        # "regarding the X position/role"
        r'regarding\s+(?:the\s+)?(.+?)\s+(?:position|role|opening)',
        # "for the X position/role"
        r'for\s+the\s+(.+?)\s+(?:position|role|opening)',
        # "interest in X (ID: 12345)"
        r'interest\s+in\s+(.+?)\s+\(\s*ID\s*:\s*[A-Z0-9\-]+\s*\)',
        # "interest in X (ID: 12345)"
        r'interest\s+in\s+(?:the\s+)?(.+?)(?:\s*\(\s*ID\s*:\s*[A-Z0-9\-]+\s*\)|\s+(?:position|role)\b|\s*[.,])',
        # "your application for X"
        r'application\s+for\s+(?:the\s+)?(.+?)(?:\s+has|\s+was|\s*[.,])',
        # "applied for X"
        r'applied\s+for\s+(?:the\s+)?(.+?)(?:\s+position|\s+role|\s*[.,])',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            # Clean up: remove trailing punctuation and common noise
            title = re.sub(r'[\s.,:;]+$', '', title)
            # Reject if too short or looks like noise
            if len(title) >= 3 and not title.lower().startswith(('the ', 'a ', 'an ')):
                logger.debug(f"[BODY JOB TITLE] Extracted '{title}' via pattern: {pattern}")
                return title

    return ""


def extract_rejection_job_title(subject: str | None, body: str | None) -> str:
    """Extract a rejection-related job title, preferring subject evidence first."""
    normalized_subject = re.sub(r"\s+", " ", (subject or "").replace("\xa0", " ")).strip()
    subject_patterns = [
        r'application\s+status\s+for\s+(.+)$',
        r'rejection\s+for\s+(.+)$',
        r'confirmation\s+of\s+withdraw(?:al)?\s+from\s+(.+)$',
        r'withdraw(?:al)?\s+from\s+(.+)$',
    ]

    for pattern in subject_patterns:
        match = re.search(pattern, normalized_subject, re.IGNORECASE)
        if match:
            return re.sub(r'[\s.,:;]+$', '', match.group(1).strip())

    return extract_job_title_from_body(body)


def find_best_matching_application(
    company_obj,
    rejection_job_title: str,
    rejection_subject: str,
    threshold: float = 0.3,
    include_rejected: bool = False,
):
    """Find the best matching ThreadTracking record for a rejection email using TF-IDF similarity.

    When a rejection email comes in on a different thread, we need to match it to the correct
    application. This function uses TF-IDF cosine similarity to compare job titles.

    Args:
        company_obj: Company model instance to filter applications by
        rejection_job_title: Job title extracted from the rejection email
        rejection_subject: Full subject line from the rejection email (fallback if no job_title)
        threshold: Minimum similarity score to consider a match (default 0.3)
        include_rejected: Whether to include already rejected applications in the search

    Returns:
        ThreadTracking object if a match is found, None otherwise
    """
    all_applications = list(
        ThreadTracking.objects.filter(company=company_obj).order_by("-sent_date", "-id")
    )
    if not all_applications:
        return None

    if include_rejected:
        open_applications = all_applications
    else:
        open_applications = [
            app for app in all_applications
            if not app.rejection_date and app.status != "rejected"
        ]
    if not open_applications:
        return None

    if len(open_applications) == 1:
        only_app = open_applications[0]
        total_company_apps = ThreadTracking.objects.filter(company=company_obj).count()
        rejection_text = (rejection_job_title or rejection_subject or "").strip()
        app_text = (only_app.job_title or "").strip()

        # If this company has/had multiple applications, avoid auto-matching the
        # last unrejected record unless title similarity is still confident.
        if total_company_apps > 1:
            if not rejection_text or not app_text:
                logger.debug(
                    "[EML JOB MATCH] Single open app but multi-app history and"
                    " missing title evidence; skipping match"
                )
                return None
            try:
                vectorizer = TfidfVectorizer(
                    analyzer='char_wb',
                    ngram_range=(2, 4),
                    lowercase=True,
                    min_df=1
                )
                matrix = cast(Any, vectorizer.fit_transform([rejection_text, app_text]))
                score = cosine_similarity(matrix[0:1], matrix[1:2]).flatten()[0]
                if score < max(threshold, 0.55):
                    logger.debug(
                        "[EML JOB MATCH] Single open app rejected: weak title"
                        " similarity %.3f for multi-app company",
                        score,
                    )
                    return None
            except Exception as exc:
                logger.debug(
                    "[EML JOB MATCH] Single open app similarity check failed (%s);"
                    " skipping match",
                    exc,
                )
                return None

        logger.debug(
            f"[EML JOB MATCH] Single application found for {company_obj.name}, using it directly"
        )

        # If best title match across all company applications is already rejected,
        # this is likely a re-processing of the same rejection/withdrawal.
        if total_company_apps > 1 and rejection_text:
            all_titles = [rejection_text] + [app.job_title or "" for app in all_applications]
            if any(text.strip() for text in all_titles[1:]):
                try:
                    vectorizer = TfidfVectorizer(
                        analyzer='char_wb',
                        ngram_range=(2, 4),
                        lowercase=True,
                        min_df=1
                    )
                    matrix = cast(Any, vectorizer.fit_transform(all_titles))
                    all_scores = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
                    best_any_idx = all_scores.argmax()
                    best_any = all_applications[best_any_idx]
                    best_any_score = all_scores[best_any_idx]
                    if (
                        best_any.pk != only_app.pk
                        and (best_any.rejection_date or best_any.status == "rejected")
                        and best_any_score >= max(threshold, 0.55)
                    ):
                        logger.debug(
                            "[EML JOB MATCH] Best overall match already rejected"
                            " (%.3f); returning it to prevent spillover",
                            best_any_score,
                        )
                        return best_any
                except Exception as exc:
                    logger.debug(
                        "[EML JOB MATCH] Best-overall comparison failed (%s);"
                        " skipping single-open fallback",
                        exc,
                    )
                    return None

        return only_app

    # Multiple applications - use TF-IDF to find best match
    # Build corpus: rejection text + all application job titles
    rejection_text = rejection_job_title or rejection_subject or ""
    if not rejection_text.strip():
        # No title evidence across multiple applications is ambiguous; do not guess.
        logger.debug("[EML JOB MATCH] No job title evidence with multiple applications; skipping match")
        return None

    # Build corpus with application job titles (or subjects as fallback)
    corpus = [rejection_text]
    for app in all_applications:
        app_text = app.job_title or ""
        corpus.append(app_text)

    # Filter out empty strings to avoid TF-IDF issues
    if not any(text.strip() for text in corpus[1:]):
        # All applications have empty titles, so matching is ambiguous.
        logger.debug("[EML JOB MATCH] Existing applications have empty job titles; skipping match")
        return None

    try:
        # Use TF-IDF with character n-grams for fuzzy matching
        vectorizer = TfidfVectorizer(
            analyzer='char_wb',  # Word boundary-aware character n-grams
            ngram_range=(2, 4),  # 2-4 character n-grams
            lowercase=True,
            min_df=1
        )
        tfidf_matrix = cast(Any, vectorizer.fit_transform(corpus))

        # Calculate cosine similarity between rejection and each application
        rejection_vector = tfidf_matrix[0:1]
        application_vectors = tfidf_matrix[1:]
        similarities = cosine_similarity(rejection_vector, application_vectors).flatten()

        # Find best match
        best_idx = similarities.argmax()
        best_score = similarities[best_idx]
        second_score = 0.0
        if len(similarities) > 1:
            second_score = sorted(similarities, reverse=True)[1]

        logger.debug(f"[EML JOB MATCH] Rejection job title: '{rejection_text}'")
        for i, (app, sim) in enumerate(zip(all_applications, similarities)):
            marker = " ← BEST MATCH" if i == best_idx else ""
            logger.debug(f"[EML JOB MATCH]   App #{i+1}: '{app.job_title}' (similarity: {sim:.3f}){marker}")

        if best_score >= threshold and (best_score - second_score) >= 0.05:
            best_match = all_applications[best_idx]
            if best_match.rejection_date or best_match.status == "rejected":
                logger.debug(
                    "[EML JOB MATCH] Best title match already rejected; returning it to prevent spillover"
                )
                return best_match
            logger.debug(
                "[EML JOB MATCH] Selected application with similarity %.3f >= "
                "threshold %s",
                best_score,
                threshold,
            )
            return best_match
        else:
            logger.debug(
                f"[EML JOB MATCH] No confident match (best={best_score:.3f}, "
                f"second={second_score:.3f}, threshold={threshold})"
            )
            return None

    except Exception as e:
        logger.debug(f"[EML JOB MATCH] TF-IDF matching failed: {e}, skipping match")
        return None


def ingest_message_from_eml(eml_content: str, fake_msg_id: str | None = None):
    """Ingest a message directly from .eml file content.

    Args:
        eml_content: Raw .eml file content as string
        fake_msg_id: Optional message ID to use (defaults to hash of subject+date)

    Returns:
        Same as ingest_message: 'inserted' | 'skipped' | 'ignored' | None
    """
    from email import message_from_string
    from email.utils import parseaddr, parsedate_to_datetime
    import hashlib

    # Reload company data if companies.json has been modified
    _reload_domain_map_if_needed()

    stats = get_stats()

    try:
        # Parse the .eml file
        msg = message_from_string(eml_content)

        # Extract headers
        subject = msg.get("Subject", "")
        date_raw = msg.get("Date", "")
        sender = msg.get("From", "")
        to_header = msg.get("To", "")

        # Decode subject if needed
        if subject:
            decoded_parts = eml_decode_header(subject)
            subject = " ".join(
                part.decode(encoding or "utf-8") if isinstance(part, bytes) else part
                for part, encoding in decoded_parts
            )

        # Parse date
        try:
            date_obj = parsedate_to_datetime(date_raw)
            if timezone.is_naive(date_obj):
                date_obj = timezone.make_aware(date_obj)
        except Exception:
            date_obj = timezone.now()

        # Generate message ID if not provided
        # Extract body
        body = ""
        body_html = ""
        body_text = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                try:
                    payload = part.get_payload(decode=True)
                    if not isinstance(payload, bytes):
                        continue

                    charset = part.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="ignore")

                    if content_type == "text/plain" and not body_text:
                        body_text = decoded.strip()
                        if not body:
                            body = body_text
                    elif content_type == "text/html":
                        body_html = html.unescape(decoded)
                        # Extract text from HTML
                        soup = BeautifulSoup(body_html, "html.parser")
                        body = soup.get_text(separator=" ", strip=True)
                except Exception as e:
                    logger.debug(f"[EML] Error decoding part: {e}")
                    continue
        else:
            # Not multipart
            try:
                payload = msg.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = msg.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="ignore").strip()
            except Exception as e:
                logger.debug(f"[EML] Error decoding body: {e}")
        forwarded_headers = EmailBodyParser.extract_forwarded_message_headers(
            body_text or body,
            body_html,
        )
        if forwarded_headers.get("subject"):
            subject = forwarded_headers["subject"]
        if forwarded_headers.get("from"):
            sender = forwarded_headers["from"]
        if forwarded_headers.get("to"):
            to_header = forwarded_headers["to"]
        if forwarded_headers.get("date") is not None:
            date_obj = forwarded_headers["date"]

        # Extract sender domain
        parsed = parseaddr(sender)
        email_addr = parsed[1] if len(parsed) == 2 else ""
        match = re.search(r"@([A-Za-z0-9.-]+)$", email_addr)
        sender_domain = match.group(1).lower() if match else ""

        # Generate message ID if not provided
        if not fake_msg_id:
            hash_input = f"{subject}{date_obj.isoformat()}{sender}".encode("utf-8")
            fake_msg_id = f"eml_{hashlib.md5(hash_input).hexdigest()}"

        # Prepare metadata dictionary matching extract_metadata format
        # RFC 5322 compliance: body should not contain headers
        rfc_body = body or "Empty Body"
        classification_text = rfc_body  # For EML files, no header text prepended

        metadata = {
            "subject": subject,
            "date": date_obj,  # Store as datetime object, not string
            "sender": sender,
            "sender_domain": sender_domain,
            "to": to_header,
            "body": rfc_body,  # RFC 5322 compliant body only
            "classification_text": classification_text,  # Same as body for EML (no headers to add)
            "thread_id": fake_msg_id,  # Use message ID as thread ID
            "labels": "",  # No labels from .eml files
            "header_hints": {
                "is_newsletter": False,
                "is_automated": False,
                "is_bulk": False,
                "is_noreply": "noreply" in sender.lower()
                or "no-reply" in sender.lower(),
            },
        }

        logger.debug(f"[EML] Parsed message:")
        logger.debug(f"  Subject: {subject}")
        logger.debug(f"  From: {sender}")
        logger.debug(f"  Date: {date_obj}")
        logger.debug(f"  Sender domain: {sender_domain}")
        logger.debug(f"  Body length: {len(body)} chars")
    except Exception as e:
        logger.debug(f"[EML] Failed to parse .eml content: {e}")
        return None

    # --- Duplicate Gmail message detection ---
    # If this EML matches an existing Gmail message (same subject, sender domain,
    # date), reuse that message's identifiers instead of the synthetic eml_* ones.
    # This prevents orphan ThreadTracking records when importing .eml files that
    # duplicate messages already ingested from Gmail.
    try:
        candidates = Message.objects.filter(
            subject=subject,
            timestamp__date=date_obj.date(),
        ).exclude(msg_id__startswith="eml_")
        for candidate in candidates:
            if candidate.sender_domain == sender_domain:
                dup_msg = (
                    f"[EML] Duplicate detected: existing Gmail message "
                    f"(msg_id={candidate.msg_id}, thread_id={candidate.thread_id}) "
                    f"matches this EML. Reusing existing identifiers to prevent "
                    f"orphan ThreadTracking records."
                )
                logger.info(dup_msg)
                log_console(dup_msg)
                fake_msg_id = candidate.msg_id
                metadata["thread_id"] = candidate.thread_id
                break
    except Exception as e:
        logger.debug(f"[EML] Error during duplicate Gmail detection: {e}")

    # Now follow the same pipeline as ingest_message
    body = metadata["body"]  # RFC 5322 compliant body (for storage)
    classification_text = metadata.get(
        "classification_text", body
    )  # For classification

    # Skip blank bodies
    if not body or not body.strip():
        logger.debug(f"[EML BLANK BODY] Skipping message: {metadata.get('subject','(no subject)')}")
        log_ignored_message(fake_msg_id, metadata, reason="blank_body")
        _increment_stat(stats, "total_ignored")
        return "ignored"

    # Check if application-related (use classification_text for pattern matching)
    header_hints = metadata.get("header_hints", {})

    # Auto-ignore newsletters and bulk mail (shared helper)
    newsletter_result = _check_newsletter_auto_ignore(
        metadata, header_hints, fake_msg_id, stats, log_prefix="[EML] "
    )
    if newsletter_result:
        return "ignored"

    # Continue with classification and company resolution
    # (Using the same logic as ingest_message but without Gmail service dependency)

    # Run ML classification first (use classification_text for ML/pattern matching)
    result = predict_with_fallback(
        predict_subject_type,
        metadata["subject"],
        classification_text,
        sender=metadata["sender"],
    )
    ml_label = result.get("label", "noise")
    ml_confidence = result.get("confidence", 0.0)

    # Parse company from subject/body (use classification_text for pattern matching)
    parse_result = parse_subject(
        metadata["subject"],
        classification_text,
        metadata["sender"],
        metadata["sender_domain"],
    )

    # Extract company name from parse result
    company = None
    if isinstance(parse_result, dict):
        company = parse_result.get("company") or parse_result.get("predicted_company")
    elif isinstance(parse_result, str):
        company = parse_result

    # Apply label overrides (internal intro, internal recruiter, personal domain)
    ml_label, result = _apply_label_overrides(
        result, metadata, company, parse_result, log_prefix="[EML] "
    )
    ml_confidence = result.get("confidence", 0.0) if result else 0.0

    # Skip company assignment for noise and head_hunter messages
    if ml_label in ("noise", "head_hunter"):
        company = None
        logger.debug(f"[EML] Skipping company assignment for {ml_label} message")
    logger.debug(f"[EML] Parsed company: {company}")
    logger.debug(f"[EML] ML label: {ml_label}, confidence: {ml_confidence}")

    # Get or create company object (shared helper)
    company_obj, _canonical_company = _resolve_company_obj(
        company, metadata, ml_confidence, log_prefix="[EML] "
    )

    # Check for duplicates
    existing = Message.objects.filter(msg_id=fake_msg_id).first()
    if existing:
        logger.debug(f"[EML] Message already exists (msg_id={fake_msg_id}), updating...")
        # Update existing message
        existing.subject = metadata["subject"]
        existing.sender = metadata["sender"]
        existing.timestamp = metadata["date"]
        existing.company = company_obj
        existing.ml_label = ml_label
        existing.confidence = ml_confidence
        existing.save()

        # Propagate label to ThreadTracking
        if ml_label in ("job_application", "interview_invite") and company_obj:
            try:
                if isinstance(parse_result, dict):
                    existing_tt = ThreadTracking.objects.filter(
                        thread_id=existing.thread_id
                    ).first()
                    if existing_tt:
                        parsed_job_title = parse_result.get("job_title", "")
                        parsed_job_id = parse_result.get("job_id", "")
                        tt_updated = False
                        if existing_tt.company_id != company_obj.id:
                            existing_tt.company = company_obj
                            existing_tt.company_source = "eml_import"
                            tt_updated = True
                        if parsed_job_title and existing_tt.job_title != parsed_job_title:
                            existing_tt.job_title = parsed_job_title
                            tt_updated = True
                        if parsed_job_id and existing_tt.job_id != parsed_job_id:
                            existing_tt.job_id = parsed_job_id
                            tt_updated = True
                        sent_date = metadata["date"].date()
                        if existing_tt.sent_date != sent_date:
                            existing_tt.sent_date = sent_date
                            tt_updated = True
                        if tt_updated:
                            existing_tt.save()
                from tracker.utils import propagate_message_label_to_thread
                propagate_message_label_to_thread(existing)
                logger.debug(f"[EML] Updated ThreadTracking for existing message")
            except Exception as e:
                logger.debug(f"[EML] Failed to propagate label to ThreadTracking: {e}")
        # Handle rejection/cancelled for existing messages
        elif ml_label in ("rejection", "cancelled") and company_obj:
            try:
                rejection_date = metadata["date"].date()
                # Detect cancelled from email text
                is_cancelled = ml_label == "cancelled"
                if not is_cancelled:
                    combined_text = (metadata.get("subject", "") + " " + body).lower()
                    if re.search(r'\b(?:cancelled|canceled|closed/cancelled|cancelled/closed)\b', combined_text):
                        is_cancelled = True
                        logger.debug(f"[EML] Detected 'cancelled' in email text, setting cancelled=True")
                # Extract job title for matching
                job_title = ""
                if isinstance(parse_result, dict):
                    job_title = parse_result.get("job_title", "")
                # If no job title from subject, try extracting from body
                if not job_title:
                    job_title = extract_rejection_job_title(metadata["subject"], body)

                # Use TF-IDF job title matching to find the correct application
                existing_tt = find_best_matching_application(
                    company_obj,
                    job_title,
                    metadata["subject"]
                )
                if existing_tt:
                    if not existing_tt.rejection_date:
                        existing_tt.rejection_date = rejection_date
                    existing_tt.status = "rejected"
                    if is_cancelled:
                        existing_tt.cancelled = True
                    existing_tt.save()
                    logger.debug(
                        "[EML] Updated existing ThreadTracking for %s (job: '%s') "
                        "with rejection_date=%s, cancelled=%s",
                        company_obj.name,
                        existing_tt.job_title,
                        rejection_date,
                        is_cancelled,
                    )
                else:
                    logger.debug(
                        "[EML] No existing ThreadTracking found for %s to update "
                        "with rejection",
                        company_obj.name,
                    )
            except Exception as e:
                logger.debug(f"[EML] Failed to update ThreadTracking with rejection: {e}")
        return "skipped"

    # Create new message
    try:
        # Compute body hash for deduplication
        normalized_body = re.sub(r"\s+", " ", body or "").strip()
        body_hash = hashlib.sha256(normalized_body.encode("utf-8")).hexdigest()

        msg_obj = Message.objects.create(
            msg_id=fake_msg_id,
            thread_id=metadata["thread_id"],
            subject=metadata["subject"],
            sender=metadata["sender"],
            timestamp=metadata["date"],
            company=company_obj,
            ml_label=ml_label,
            confidence=ml_confidence,
            body=body,
            body_html=body_html,
            body_hash=body_hash,
            reviewed=False,
        )

        # Store body text in separate search table

        # Create or update ThreadTracking for job applications, interview invites, rejections, and cancelled
        if ml_label in ("job_application", "interview_invite", "rejection", "cancelled") and company_obj:
            # Extract job details from parse_result
            job_title = ""
            job_id = ""
            if isinstance(parse_result, dict):
                job_title = parse_result.get("job_title", "")
                job_id = parse_result.get("job_id", "")
            # If no job title from subject and this is a rejection, try extracting from body
            if not job_title and ml_label in ("rejection", "cancelled"):
                job_title = extract_rejection_job_title(metadata["subject"], body)

            # Determine status and dates based on label
            rejection_date = None
            is_cancelled = False
            if ml_label in ("rejection", "cancelled"):
                status = "rejected"
                rejection_date = metadata["date"].date()
                # Set cancelled flag if label is 'cancelled' OR if the email text contains "cancelled"
                is_cancelled = ml_label == "cancelled"
                if not is_cancelled:
                    # Check subject and body for "cancelled" keywords
                    combined_text = (metadata.get("subject", "") + " " + body).lower()
                    if re.search(r'\b(?:cancelled|canceled|closed/cancelled|cancelled/closed)\b', combined_text):
                        is_cancelled = True
                        logger.debug(f"[EML] Detected 'cancelled' in email text, setting cancelled=True")
            elif ml_label == "interview_invite":
                status = "interview"
            else:
                status = "application"

            try:
                # For rejections/cancelled, first try to find existing ThreadTracking by company
                # (since rejection may come in a different thread than original application)
                if ml_label in ("rejection", "cancelled"):
                    # Use TF-IDF job title matching to find the correct application
                    existing_tt = find_best_matching_application(
                        company_obj,
                        job_title,
                        metadata["subject"]
                    )
                    if existing_tt:
                        # Update existing ThreadTracking with rejection info
                        if not existing_tt.rejection_date:
                            existing_tt.rejection_date = rejection_date
                        existing_tt.status = "rejected"
                        if is_cancelled:
                            existing_tt.cancelled = True
                        existing_tt.save()
                        logger.debug(
                            "[EML] Updated existing ThreadTracking for %s (job: '%s') "
                            "with rejection_date=%s, cancelled=%s",
                            company_obj.name,
                            existing_tt.job_title,
                            rejection_date,
                            is_cancelled,
                        )
                    else:
                        # No existing application found - create one with rejection status
                        _thread_tracking, tt_created = ThreadTracking.objects.get_or_create(
                            thread_id=metadata["thread_id"],
                            defaults={
                                "company": company_obj,
                                "company_source": "eml_import",
                                "job_title": job_title,
                                "job_id": job_id,
                                "status": status,
                                "sent_date": metadata["date"].date(),
                                "rejection_date": rejection_date,
                                "cancelled": is_cancelled,
                                "ml_label": ml_label,
                                "ml_confidence": ml_confidence,
                                "reviewed": False,
                            },
                        )
                        if tt_created:
                            logger.debug(
                                "[EML] Created NEW ThreadTracking for %s with "
                                "rejection status (no prior application found)",
                                company_obj.name,
                            )
                else:
                    existing_tt = ThreadTracking.objects.filter(
                        thread_id=metadata["thread_id"]
                    ).first()
                    if existing_tt is None and ml_label == "interview_invite":
                        existing_tt = _find_existing_application_by_identity(
                            company_obj,
                            job_title,
                            job_id,
                            exclude_thread_ids={metadata["thread_id"]},
                            sent_date=metadata["date"].date(),
                        )

                    if existing_tt is not None:
                        parsed_subject = {"job_title": job_title, "job_id": job_id}
                        _update_existing_application_dates(
                            existing_tt,
                            company_obj,
                            "eml_import",
                            None,
                            {
                                "subject": metadata.get("subject", ""),
                                "body": body,
                            },
                            ml_label,
                            rejection_date,
                            metadata["date"].date() if ml_label == "interview_invite" else None,
                            None,
                            parsed_subject,
                        )
                        logger.debug(
                            "[EML] Reused existing ThreadTracking for %s - %s",
                            company_obj.name,
                            ml_label,
                        )
                    elif ml_label == "job_application":
                        _thread_tracking, tt_created = ThreadTracking.objects.get_or_create(
                            thread_id=metadata["thread_id"],
                            defaults={
                                "company": company_obj,
                                "company_source": "eml_import",
                                "job_title": job_title,
                                "job_id": job_id,
                                "status": status,
                                "sent_date": metadata["date"].date(),
                                "ml_label": ml_label,
                                "ml_confidence": ml_confidence,
                                "reviewed": False,
                            },
                        )

                        if tt_created:
                            logger.debug(f"[EML] Created ThreadTracking for {company_obj.name} - {ml_label}")
                        else:
                            logger.debug(f"[EML] ThreadTracking already exists for thread {metadata['thread_id']}")
                    else:
                        logger.debug(
                            "[EML] No application anchor found for %s milestone at %s; manual creation required",
                            ml_label,
                            company_obj.name,
                        )

            except Exception as e:
                logger.debug(f"[EML] Failed to create/update ThreadTracking: {e}")
                # Don't fail the entire ingestion if ThreadTracking creation fails

        # Update stats
        _increment_stat(stats, "total_inserted")

        logger.debug(f"[EML] Successfully ingested message (ID={msg_obj.pk})")
        return "inserted"

    except Exception as e:
        logger.debug(f"[EML] Failed to create message: {e}")
        return None


# --- Helpers for domain handling ---
def _is_ats_domain(domain: str) -> bool:
    """Return True if domain equals or is a subdomain of any ATS root domain (delegates to DomainMapper)."""
    return _domain_mapper.is_ats_domain(domain)


def _map_company_by_domain(domain: str) -> str | None:
    """Resolve company by exact or subdomain match (delegates to DomainMapper).

    Example: if mapping contains 'nsa.gov' -> 'National Security Agency', then
    'uwe.nsa.gov' will also map to that company.
    """
    mapped = _domain_mapper.map_company_by_domain(domain)
    if mapped and not is_valid_company_name(mapped):
        logger.warning(
            "Ignoring invalid domain_to_company mapping for %s -> %s",
            domain,
            mapped,
        )
        return None
    return mapped


def _get_domain_for_company(company_name: str) -> str | None:
    """Look up the primary domain for a company name (delegates to DomainMapper)."""
    return _domain_mapper.get_domain_for_company(company_name)
