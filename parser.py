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
import base64
import hashlib
import html
import json
import os

# from joblib import load  # not needed here
import quopri
import re
from datetime import datetime, timedelta, date
from email.utils import parseaddr, parsedate_to_datetime
from email import message_from_string as eml_from_string
from email.header import decode_header as eml_decode_header
from pathlib import Path

import django
import joblib
from bs4 import BeautifulSoup
from django.db.models import F
from django.utils import timezone
from django.utils.timezone import now

from db import (
    COMPANIES_PATH,
    PATTERNS_PATH,
    insert_email_text,
    insert_or_update_application,
    is_valid_company,
)
from db_helpers import build_company_job_index, get_application_by_sender
from ml_entity_extraction import extract_entities
from ml_subject_classifier import predict_subject_type
from tracker.models import (
    Company,
    IgnoredMessage,
    IngestionStats,
    Message,
    ThreadTracking,
    UnresolvedCompany,
)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()
DEBUG = True


# ======================================================================================
# PHASE 3: CONSOLIDATED PARSER CLASSES
# Previously in parser_refactored/ package, now consolidated here for simplicity.
# ======================================================================================


class CompanyValidator:
    """Handles company name validation and normalization.
    
    This class provides methods for:
    - Validating company names against invalid patterns
    - Normalizing company names (removing artifacts, standardizing format)
    - Detecting if a string looks like a person's name rather than a company
    """
    
    def __init__(self, patterns: dict):
        """Initialize the validator with pattern definitions.
        
        Args:
            patterns: Dictionary containing 'invalid_company_prefixes' and other patterns
        """
        self.patterns = patterns
        self.invalid_prefixes = patterns.get("invalid_company_prefixes", [])
    
    def is_valid_company_name(self, name):
        """Reject company names that match known invalid prefixes from patterns.
        
        Args:
            name: Company name to validate
            
        Returns:
            True if valid company name, False if invalid or matches exclusion patterns
        """
        if not name:
            return False

        for prefix in self.invalid_prefixes:
            try:
                # Compile each prefix as regex, using re.IGNORECASE
                if re.match(prefix, name, re.IGNORECASE):
                    return False
            except re.error:
                # If invalid regex, fallback to simple startswith
                if name.lower().startswith(prefix.lower()):
                    return False
        return True
    
    def normalize_company_name(self, name: str) -> str:
        """Normalize common subject-derived artifacts from company names.

        - Strip whitespace and trailing punctuation
        - Remove suffix fragments like "- Application ..." or trailing "Application"
        - Collapse repeated whitespace
        - Map known pseudo-companies like "Indeed Application" -> "Indeed"
        
        Args:
            name: Company name to normalize
            
        Returns:
            Normalized company name
        """
        if not name:
            return ""

        n = name.strip()

        # Remove common subject suffixes accidentally captured
        n = re.sub(r"\s*-\s*Application.*$", "", n, flags=re.IGNORECASE)
        n = re.sub(r"\bApplication\b\s*$", "", n, flags=re.IGNORECASE)

        # Trim lingering separators/punctuation
        n = re.sub(r"[\s\-:|•]+$", "", n)

        # Collapse multiple internal spaces
        n = re.sub(r"\s{2,}", " ", n)

        # Known normalizations
        lower = n.lower()
        if lower == "indeed application":
            return "Indeed"

        return n
    
    def looks_like_person(self, name: str) -> bool:
        """Heuristic: return True if the string looks like an individual person's name.

        Criteria (intentionally conservative so we *reject* obvious person names):
        - 1–3 tokens, each starting with capital then lowercase letters only
        - No token contains digits, '&', '@', '.', or corporate suffix markers
        - Contains no common company suffix words (Inc, LLC, Corp, Company, Technologies, Systems)
        - If exactly two tokens and both are common first/last name shapes (<=12 chars) treat as person
        
        Args:
            name: Name string to check
            
        Returns:
            True if likely a person name, False if likely a company name
        """
        if not name:
            return False
        raw = name.strip()
        if len(raw) > 40:  # Long strings unlikely to be just a person name
            return False
        tokens = raw.split()
        if not (1 <= len(tokens) <= 3):
            return False
        corp_markers = {
            "inc", "llc", "ltd", "co", "corp", "corporation", 
            "company", "technologies", "systems", "group"
        }
        if any(t.lower().strip(".,") in corp_markers for t in tokens):
            return False
        # Reject if any token has non alpha (besides hyphen) or is ALLCAPS acronym
        for t in tokens:
            if not re.match(r"^[A-Z][a-z]+(?:-[A-Z][a-z]+)?$", t):
                return False
        # Two-token typical person pattern
        if len(tokens) == 2 and all(len(t) <= 12 for t in tokens):
            return True
        # Single short token like "Kelly" should not be considered a company unless in known companies
        if len(tokens) == 1 and len(tokens[0]) <= 10:
            return True
        return False


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
            if DEBUG:
                print(f"[WARNING] companies.json not found at {self.companies_path}")
            return
        
        try:
            with open(self.companies_path, "r", encoding="utf-8") as f:
                self.company_data = json.load(f)
            
            # Extract all company configuration data
            self.ats_domains = [d.lower() for d in self.company_data.get("ats_domains", [])]
            self.headhunter_domains = [d.lower() for d in self.company_data.get("headhunter_domains", [])]
            self.job_board_domains = [d.lower() for d in self.company_data.get("job_boards", [])]
            self.known_companies = {c.lower() for c in self.company_data.get("known", [])}
            self.known_companies_cased = self.company_data.get("known", [])
            self.domain_to_company = {
                k.lower(): v for k, v in self.company_data.get("domain_to_company", {}).items()
            }
            self.aliases = self.company_data.get("aliases", {})
            
            # Track file modification time for auto-reload
            try:
                self._domain_map_mtime = self.companies_path.stat().st_mtime
            except Exception:
                self._domain_map_mtime = None
                
            if DEBUG:
                print(f"[INFO] Loaded companies.json: {len(self.domain_to_company)} domains, "
                      f"{len(self.known_companies)} companies")
                
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
                if DEBUG:
                    print(f"[INFO] Reloaded companies.json (mtime changed)")
        except Exception as e:
            # If reload fails, keep the existing mapping silently
            if DEBUG:
                print(f"[WARNING] Failed to reload companies.json: {e}")

    def is_ats_domain(self, domain: str) -> bool:
        """Return True if domain equals or is a subdomain of any ATS root domain.
        
        Args:
            domain: Email domain to check (e.g., 'myworkday.com', 'talent.icims.com')
            
        Returns:
            True if domain is an ATS domain, False otherwise
        """
        if not domain:
            return False
        d = domain.lower()
        for ats in self.ats_domains:
            if d == ats or d.endswith("." + ats):
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


class RuleClassifier:
    """Classifies email messages using rule-based regex patterns.
    
    This class encapsulates the rule_label function logic, which checks message
    text against compiled regex patterns in a prioritized order to classify
    job search emails (applications, rejections, interviews, etc.).
    """

    def __init__(self, patterns: dict):
        """Initialize RuleClassifier with patterns from patterns.json.
        
        Args:
            patterns: Dictionary containing message_label_patterns, 
                     message_label_excludes, special_cases, early_detection,
                     and validation_rules from patterns.json
        """
        self.patterns = patterns
        self._compile_patterns()
        self._compile_special_patterns()

    def _compile_patterns(self):
        """Compile regex patterns from patterns.json for efficient matching."""
        self._msg_label_patterns = {}
        
        # Map code labels to patterns.json keys
        label_key_map = {
            "interview_invite": "interview",
            "job_application": "application",
            "rejection": "rejection",
            "offer": "offer",
            "noise": "noise",
            "head_hunter": "head_hunter",
            "ignore": "ignore",
            "response": "response",
            "follow_up": "follow_up",
            "ghosted": "ghosted",
            "referral": "referral",
            "other": "other",
            "blank": "blank",
        }
        
        # Compile positive patterns for each label
        message_labels = self.patterns.get("message_labels", {})
        for code_label, pattern_key in label_key_map.items():
            compiled = []
            pattern_list = message_labels.get(pattern_key, [])
            for p in pattern_list:
                if p != "None":
                    try:
                        compiled.append(re.compile(p, re.I))
                    except re.error as e:
                        print(f"⚠️  Invalid regex pattern for {code_label}: {p} - {e}")
            self._msg_label_patterns[code_label] = compiled

        # Compile negative patterns (excludes) for each label
        message_excludes = self.patterns.get("message_label_excludes", {})
        self._msg_label_excludes = {}
        for code_label, pattern_key in label_key_map.items():
            exclude_list = message_excludes.get(pattern_key, [])
            compiled_excludes = []
            for p in exclude_list:
                try:
                    compiled_excludes.append(re.compile(p, re.I))
                except re.error as e:
                    print(f"⚠️  Invalid exclude pattern for {code_label}: {p} - {e}")
            self._msg_label_excludes[code_label] = compiled_excludes

    def _compile_special_patterns(self):
        """Compile special case, early detection, and validation patterns from patterns.json."""
        # Special cases (subject-based rules)
        special_cases = self.patterns.get("special_cases", {})
        self._special_indeed_subject = self._compile_pattern_list(special_cases.get("indeed_application_subject", []))
        self._special_assessment = self._compile_pattern_list(special_cases.get("assessment_complete", []))
        self._special_incomplete_app = self._compile_pattern_list(special_cases.get("incomplete_application_reminder", []))
        
        # Early detection patterns
        early_detection = self.patterns.get("early_detection", {})
        self._early_scheduling = self._compile_pattern_list(early_detection.get("scheduling_language", []))
        self._reply_indicators = self._compile_pattern_list(early_detection.get("reply_indicators", []))
        self._early_referral = self._compile_pattern_list(early_detection.get("referral_language", []))
        self._early_rejection_override = self._compile_pattern_list(early_detection.get("rejection_override", []))
        self._early_status_update = self._compile_pattern_list(early_detection.get("status_update", []))
        self._early_application_confirm = self._compile_pattern_list(early_detection.get("application_confirmation", []))
        
        # Validation rules
        validation = self.patterns.get("validation_rules", {})
        self._headhunter_contact_patterns = validation.get("head_hunter_contact_patterns", [])
        signature_pattern = validation.get("head_hunter_signature_pattern", "")
        self._headhunter_signature_rx = re.compile(signature_pattern, re.I) if signature_pattern else None
        referral_lang = validation.get("referral_explicit_language", "")
        self._referral_explicit_rx = re.compile(referral_lang, re.I) if referral_lang else None

    def _compile_pattern_list(self, pattern_list):
        """Helper to compile a list of regex patterns."""
        compiled = []
        for p in pattern_list:
            try:
                compiled.append(re.compile(p, re.I | re.DOTALL))
            except re.error as e:
                print(f"⚠️  Invalid pattern: {p} - {e}")
        return compiled

    def classify(
        self,
        subject: str,
        body: str = "",
        sender_domain=None,
        headhunter_domains: set = None,
        job_board_domains: set = None,
        is_ats_domain_fn=None,
        map_company_by_domain_fn=None,
    ):
        """Return a rule-based label from compiled regex patterns.

        Checks message text against label patterns in a prioritized order to
        reduce false positives (e.g., prefer noise over rejected for newsletters).

        Args:
            subject: Email subject line
            body: Email body text
            sender_domain: Sender's email domain (optional)
            headhunter_domains: Set of known headhunter domains (optional)
            job_board_domains: Set of known job board domains (optional)
            is_ats_domain_fn: Function to check if domain is an ATS (optional)
            map_company_by_domain_fn: Function to map domain to company (optional)

        Returns:
            One of the known labels or None if no rule matches.
            Labels: interview_invite, job_application, rejection, offer, noise,
                   head_hunter, other, referral, ghosted, blank
        """
        s = f"{subject or ''} {body or ''}"

        # Special-case: Indeed application confirmation subjects
        if subject and any(rx.search(subject) for rx in self._special_indeed_subject):
            if DEBUG:
                print("[DEBUG rule_label] Forcing job_application for Indeed Application subject")
            return "job_application"

        # Special-case: Assessment completion notifications -> "other"
        subject_text = subject or ""
        if any(rx.search(subject_text) for rx in self._special_assessment):
            if DEBUG:
                print("[DEBUG rule_label] Forcing 'other' for assessment completion notification")
            return "other"

        # Special-case: Incomplete application reminders -> "other"
        if any(rx.search(s) for rx in self._special_incomplete_app):
            if DEBUG:
                print("[DEBUG rule_label] Forcing 'other' for incomplete application reminder")
            return "other"

        # Check rejection patterns EARLY (before scheduling detection)
        # This prevents email threads with rejection + old scheduling language from being misclassified
        for rx in self._msg_label_patterns.get("rejection", []):
            if rx.search(s):
                if DEBUG:
                    print(f"[DEBUG rule_label] Early rejection match: {rx.pattern[:80]}")
                return "rejection"

        # Check if this is a reply/follow-up email (RE:, Re:, FW:, Fwd:, etc.)
        is_reply = subject and any(rx.search(subject) for rx in self._reply_indicators)

        # Early scheduling-language detection -> interview_invite
        # BUT classify as 'other' for replies (to avoid classifying scheduling follow-ups as interviews)
        if any(rx.search(s) for rx in self._early_scheduling):
            if is_reply:
                if DEBUG:
                    print("[DEBUG rule_label] Scheduling language in reply detected -> treating as follow-up (other)")
                # Scheduling follow-ups should be classified as 'other'
                return "other"
            else:
                if DEBUG:
                    print("[DEBUG rule_label] Early scheduling-language match -> interview_invite")
                return "interview_invite"

        # Early referral detection
        if any(rx.search(s) for rx in self._early_referral):
            if DEBUG:
                print(f"[DEBUG rule_label] Early referral match -> referral")
            return "referral"

        # Check for rejection signals BEFORE application confirmation
        # (to handle mixed messages like "thanks for applying, but we moved forward with others")
        for rx in self._early_rejection_override:
            if rx.search(s):
                if DEBUG:
                    print(f"[DEBUG rule_label] Early rejection signal detected, checking rejection patterns")
                # Verify with full rejection patterns
                for pattern_rx in self._msg_label_patterns.get("rejection", []):
                    if pattern_rx.search(s):
                        if DEBUG:
                            print(f"[DEBUG rule_label] Rejection confirmed -> rejection")
                        return "rejection"
                break  # Exit after checking rejection patterns once

        # Status update messages (follow-up/still under review) -> other (checked BEFORE application confirmation)
        if any(rx.search(s) for rx in self._early_status_update):
            if DEBUG:
                print("[DEBUG rule_label] Matched status-update -> other")
            return "other"

        # Explicit application-confirmation signals -> job_application
        if any(rx.search(s) for rx in self._early_application_confirm):
            if DEBUG:
                print("[DEBUG rule_label] Matched application-confirmation -> job_application")
            return "job_application"

        # Check labels in priority order
        for label in (
            "offer",
            "rejection",
            "head_hunter",
            "noise",
            "job_application",
            "interview_invite",
            "other",
            "referral",
            "ghosted",
            "blank",
        ):
            if DEBUG and label == "rejection":
                print(f"[DEBUG rule_label] Checking '{label}' patterns...")
            
            for rx in self._msg_label_patterns.get(label, []):
                match = rx.search(s)
                if match:
                    if DEBUG and label in ("rejection", "noise", "head_hunter"):
                        print(f"[DEBUG rule_label] Pattern MATCHED for '{label}': {rx.pattern[:80]}")
                        print(f"  Matched text: '{match.group()}'")
                    
                    # Check exclude patterns from patterns.json
                    excludes = self._msg_label_excludes.get(label, [])
                    if DEBUG and label in ("noise", "head_hunter") and excludes:
                        print(f"[DEBUG rule_label] Checking {len(excludes)} exclusion patterns for {label}...")
                    
                    matched_excludes = [ex for ex in excludes if ex.search(s)]
                    if matched_excludes:
                        if DEBUG:
                            print(f"[DEBUG rule_label] Label '{label}' pattern matched but EXCLUDED by:")
                            for ex in matched_excludes:
                                print(f"  - {ex.pattern}")
                        continue

                    # Conservative handling for head_hunter / referral labels
                    if label in ("head_hunter", "referral"):
                        d = (sender_domain or "").lower()

                        # Allow immediate return if domain is configured as headhunter
                        if headhunter_domains and d and d in headhunter_domains:
                            return label

                        # Skip if domain is ATS/job-board/company
                        try:
                            if d:
                                is_ats = is_ats_domain_fn(d) if is_ats_domain_fn else False
                                is_job_board = d in job_board_domains if job_board_domains else False
                                is_company = map_company_by_domain_fn(d) if map_company_by_domain_fn else False
                                if is_ats or is_job_board or is_company:
                                    continue
                        except Exception:
                            pass

                        # Additional strictness for head_hunter: require contact evidence
                        if label == "head_hunter":
                            has_contact = (
                                any(re.search(p, s, re.I) for p in self._headhunter_contact_patterns)
                                or (self._headhunter_signature_rx and self._headhunter_signature_rx.search(s))
                            )
                            if not has_contact:
                                continue
                        else:
                            # For referral: require explicit referral language if no domain
                            if not d:
                                if not (self._referral_explicit_rx and self._referral_explicit_rx.search(s)):
                                    continue

                    # Special case: job_application with scheduling language -> interview_invite
                    # BUT skip for replies (to avoid classifying scheduling follow-ups as interviews)
                    if label == "job_application":
                        if any(rx.search(s) for rx in self._early_scheduling):
                            if is_reply:
                                if DEBUG:
                                    print("[DEBUG rule_label] job_application + scheduling in reply -> skipping interview_invite")
                                # Don't convert to interview_invite for scheduling follow-ups
                                # Fall through to return job_application or continue checking
                            else:
                                if DEBUG:
                                    print("[DEBUG rule_label] Matched scheduling language -> returning interview_invite")
                                return "interview_invite"

                    if DEBUG and label == "rejection":
                        print(f"[DEBUG rule_label] About to return '{label}'")
                    return label

        return None


class EmailBodyParser:
    """Parses and extracts body text from email messages.
    
    This class handles:
    - MIME part decoding (base64, quoted-printable, 7bit)
    - Gmail API payload body extraction (recursive multipart handling)
    - Raw EML message parsing
    - HTML to plain text conversion
    - Header extraction for classification
    """

    @staticmethod
    def decode_mime_part(data: str, encoding: str) -> str:
        """Decode a MIME part body string using the provided encoding.

        Supports base64, quoted-printable, and 7bit. Returns a decoded UTF-8 string.
        
        Args:
            data: Encoded MIME part data
            encoding: Encoding type (base64, quoted-printable, 7bit)
            
        Returns:
            Decoded UTF-8 string
        """
        if encoding == "base64":
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        elif encoding == "quoted-printable":
            return quopri.decodestring(data).decode("utf-8", errors="ignore")
        elif encoding == "7bit":
            return data  # usually already decoded
        else:
            return data

    @staticmethod
    def extract_from_gmail_parts(parts: list) -> str:
        """Extract the first HTML part's body from a Gmail message payload tree.

        Walks nested multipart sections; prefers HTML and returns full HTML string.
        
        Args:
            parts: List of Gmail API message parts
            
        Returns:
            HTML body string, "Empty Body" if empty, or "" if not found
        """
        for part in parts:
            mime_type = part.get("mimeType")
            body_data = part.get("body", {}).get("data")
            
            if mime_type == "text/html" and body_data:
                decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
                if not decoded:
                    decoded = "Empty Body"
                    if DEBUG:
                        print("Decoded Body/HTML part is empty.")
                return decoded  # preserve full HTML
            elif "parts" in part:
                result = EmailBodyParser.extract_from_gmail_parts(part["parts"])
                if result:
                    return result
                else:
                    return "Empty Body"
        
        return ""

    @staticmethod
    def decode_header_value(raw_val: str) -> str:
        """Decode RFC 2047 encoded header values to unicode.

        Falls back gracefully on decode errors, always returns a str.
        
        Args:
            raw_val: Raw header value (may be RFC 2047 encoded)
            
        Returns:
            Decoded unicode string
        """
        if not raw_val:
            return ""
        
        try:
            parts = eml_decode_header(raw_val)
            decoded_chunks = []
            for text, enc in parts:
                if isinstance(text, bytes):
                    try:
                        decoded_chunks.append(text.decode(enc or "utf-8", errors="ignore"))
                    except Exception:
                        decoded_chunks.append(text.decode("utf-8", errors="ignore"))
                else:
                    decoded_chunks.append(text)
            return "".join(decoded_chunks)
        except Exception:
            return raw_val

    @staticmethod
    def html_to_text(html: str) -> str:
        """Convert HTML to plain text using BeautifulSoup.
        
        Args:
            html: HTML content
            
        Returns:
            Plain text with HTML tags removed
        """
        if not html:
            return ""
        
        try:
            soup = BeautifulSoup(html, "html.parser")
            # Remove script and style tags
            for tag in soup(["script", "style"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)
        except Exception:
            return html

    @staticmethod
    def parse_raw_eml(raw_text: str, now_fn=None):
        """Parse a raw EML (RFC 822) message string and return metadata.

        This allows debugging/ingesting messages pasted into the UI or loaded from disk
        without requiring a live Gmail API service call.
        
        Args:
            raw_text: Raw EML message text
            now_fn: Function to get current time (for testing)
            
        Returns:
            Dictionary with keys: subject, body, body_html, timestamp, date(str),
            sender, sender_domain, thread_id(None), labels(""), last_updated, header_hints
        """
        if now_fn is None:
            now_fn = timezone.now
        
        if not raw_text:
            return {
                "subject": "",
                "body": "",
                "body_html": "",
                "timestamp": now_fn(),
                "date": now_fn().strftime("%Y-%m-%d %H:%M:%S"),
                "sender": "",
                "sender_domain": "",
                "thread_id": None,
                "labels": "",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "header_hints": {},
            }

        try:
            eml = eml_from_string(raw_text)
        except Exception:
            # Return minimal structure if parsing fails
            return {
                "subject": "(parse error)",
                "body": raw_text,
                "body_html": "",
                "timestamp": now_fn(),
                "date": now_fn().strftime("%Y-%m-%d %H:%M:%S"),
                "sender": "",
                "sender_domain": "",
                "thread_id": None,
                "labels": "",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "header_hints": {},
            }

        subject = EmailBodyParser.decode_header_value(eml.get("Subject", ""))
        sender = EmailBodyParser.decode_header_value(eml.get("From", ""))
        date_raw = eml.get("Date", "")
        
        try:
            date_obj = parsedate_to_datetime(date_raw)
            if timezone.is_naive(date_obj):
                date_obj = timezone.make_aware(date_obj)
        except Exception:
            date_obj = now_fn()
        
        date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")

        # Extract sender domain
        parsed = parseaddr(sender)
        email_addr = parsed[1] if len(parsed) == 2 else ""
        match = re.search(r"@([A-Za-z0-9.-]+)$", email_addr)
        sender_domain = match.group(1).lower() if match else ""

        # Walk parts for body (prefer HTML) else text/plain
        body_html = ""
        body_text = ""
        
        if eml.is_multipart():
            for part in eml.walk():
                ctype = part.get_content_type()
                disp = (part.get("Content-Disposition") or "").lower()
                
                if "attachment" in disp:
                    continue  # skip attachments
                
                try:
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        continue
                    decoded = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    continue
                
                if ctype == "text/html" and not body_html:
                    body_html = decoded
                elif ctype == "text/plain" and not body_text:
                    body_text = decoded
        else:
            try:
                payload = eml.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(eml.get_content_charset() or "utf-8", errors="ignore")
            except Exception:
                body_text = raw_text

        if body_html and not body_text:
            # Provide plain text fallback from HTML
            body_text = EmailBodyParser.html_to_text(body_html)

        # Header hints similar to Gmail path (limited set for EML)
        header_hints = {
            "is_newsletter": any(h in eml for h in ["List-Id", "List-Unsubscribe", "X-Newsletter"]),
            "is_bulk": EmailBodyParser.decode_header_value(eml.get("Precedence", "")).lower() == "bulk",
            "is_noreply": "noreply" in sender.lower() or "no-reply" in sender.lower(),
            "reply_to": EmailBodyParser.decode_header_value(eml.get("Reply-To", "")) or None,
            "organization": EmailBodyParser.decode_header_value(eml.get("Organization", "")) or None,
            "auto_submitted": EmailBodyParser.decode_header_value(eml.get("Auto-Submitted", "")).lower() not in ("", "no"),
        }

        # Combine headers for classification like Gmail version
        header_text = []
        for h_name, h_val in eml.items():
            if h_name.lower() in {"list-id", "list-unsubscribe", "precedence", "reply-to", "organization"}:
                header_text.append(f"{h_name}: {h_val}")
        
        body_for_classification = ("\n".join(header_text) + "\n\n" + (body_text or "")).strip()

        return {
            "thread_id": None,
            "subject": subject,
            "body": body_for_classification,
            "body_html": body_html,
            "date": date_str,
            "timestamp": date_obj,
            "labels": "",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sender": sender,
            "sender_domain": sender_domain,
            "header_hints": header_hints,
        }


class CompanyResolver:
    """Resolves and extracts company names from email messages.
    
    This class implements multiple strategies for company name extraction:
    - ATS domain/sender prefix matching
    - Job board application confirmation parsing
    - Domain-to-company mapping
    - Known company list matching
    - Regex pattern extraction from subject lines
    - Entity extraction (spaCy NER)
    - Display name fallback
    """

    def __init__(
        self,
        company_data: dict,
        domain_mapper,
        company_validator,
        known_companies: set,
        job_board_domains: list,
        ats_domains: list,
    ):
        """Initialize CompanyResolver with configuration data and dependencies.
        
        Args:
            company_data: Dictionary from companies.json with aliases, known companies
            domain_mapper: DomainMapper instance for domain resolution
            company_validator: CompanyValidator instance for validation
            known_companies: Set of known company names (lowercase)
            job_board_domains: List of job board domains
            ats_domains: List of ATS domains
        """
        self.company_data = company_data
        self.domain_mapper = domain_mapper
        self.company_validator = company_validator
        self.known_companies = known_companies
        self.job_board_domains = job_board_domains
        self.ats_domains = ats_domains

    def extract_from_ats_sender(
        self, sender: str, sender_domain
    ):
        """Extract company from ATS sender prefix (e.g., ngc@myworkday.com -> Northrop Grumman).
        
        Args:
            sender: Full sender email (with optional display name)
            sender_domain: Sender's email domain
            
        Returns:
            Company name if found, None otherwise
        """
        if not sender_domain:
            return None
        
        # Check if this is an ATS domain
        is_ats = False
        domain_lower = sender_domain.lower()
        for ats_root in self.ats_domains:
            if domain_lower == ats_root or domain_lower.endswith(f".{ats_root}"):
                is_ats = True
                break
        
        if not is_ats:
            return None
        
        # Extract email address from "Display Name <email@domain.com>"
        _, sender_email = parseaddr(sender)
        if not sender_email or "@" not in sender_email:
            return None
        
        sender_prefix = sender_email.split("@", maxsplit=1)[0].strip().lower()
        
        # Check if prefix matches an alias
        aliases_lower = {k.lower(): v for k, v in self.company_data.get("aliases", {}).items()}
        if sender_prefix in aliases_lower:
            if DEBUG:
                print(f"[DEBUG] ATS alias match: {sender_prefix} -> {aliases_lower[sender_prefix]}")
            return aliases_lower[sender_prefix]
        
        return None

    def extract_from_job_board_body(
        self, body: str, subject: str, sender_email: str, sender_domain
    ):
        """Extract actual employer from job board application confirmation body.
        
        Works for Indeed, LinkedIn, Dice, etc. when subject contains "Application"
        and sender is from a job board domain.
        
        Args:
            body: Email body text (may be HTML)
            subject: Email subject line
            sender_email: Sender's email address
            sender_domain: Sender's email domain
            
        Returns:
            Extracted company name if found, None otherwise
        """
        if not body or not subject:
            return None
        
        if not re.search(r'\bapplication\b', subject, re.IGNORECASE):
            return None
        
        domain_lower = (sender_domain or "").lower()
        
        # Check if this is a job board domain
        is_job_board = (
            domain_lower in self.job_board_domains or
            "indeedapply" in sender_email or
            "application" in subject.lower()
        )
        
        if not is_job_board:
            return None
        
        if DEBUG:
            print(f"[DEBUG] Job board confirmation detected, attempting body extraction")
        
        # Extract plain text body for pattern matching
        body_plain = body
        try:
            if "<html" in body.lower() or "<style" in body.lower():
                soup = BeautifulSoup(body, "html.parser")
                for tag in soup(["style", "script"]):
                    tag.decompose()
                body_plain = soup.get_text(separator=" ", strip=True)
        except Exception:
            body_plain = body
        
        if not body_plain:
            return None
        
        # Try pattern 1: "sent to COMPANY"
        pattern1 = re.search(
            r"(?:the following items were sent to|sent to)\s+([A-Z][A-Za-z0-9\s&.,'-]+?)\s*[.\n]",
            body_plain,
            re.IGNORECASE,
        )
        
        if pattern1:
            extracted = pattern1.group(1).strip()
        else:
            # Try pattern 2: "about your application" with company name before it
            pattern2 = re.search(
                r"<strong>\s*<a[^>]+>([A-Z][A-Za-z0-9\s&.,'-]+?)</a>\s*</strong>.*?about your application",
                body,
                re.IGNORECASE | re.DOTALL,
            )
            extracted = pattern2.group(1).strip() if pattern2 else None
        
        if not extracted:
            return None
        
        # Clean up common trailing words
        extracted = re.sub(
            r"\s+(and|About|Your|Application|Details)$",
            "",
            extracted,
            flags=re.IGNORECASE,
        ).strip()
        
        # Remove trailing punctuation
        extracted = extracted.rstrip(".,;:")
        
        if extracted and len(extracted) > 2 and self.company_validator.is_valid_company_name(extracted):
            if DEBUG:
                print(f"[DEBUG] Job board employer extraction SUCCESS: {extracted}")
            return extracted
        
        return None

    def extract_from_ats_display_name(
        self, sender: str, check_known: bool = False
    ):
        """Extract company from ATS display name with validation.
        
        Args:
            sender: Full sender string with display name
            check_known: If True, only return if company is known or looks like a company
            
        Returns:
            Company name if valid, None otherwise
        """
        if not sender:
            return None
        
        display_name, _ = parseaddr(sender)
        
        # Clean up ATS-specific noise
        cleaned = re.sub(
            r"\b(Workday|Recruiting Team|Careers|Talent Acquisition Team|HR|Hiring|Notification|Notifications|Team|Portal)\b",
            "",
            display_name,
            flags=re.I,
        ).strip()
        
        # Remove ATS platform suffixes
        cleaned = re.sub(
            r'\s*@\s*(icims|workday|greenhouse|lever|indeed)\s*$',
            '',
            cleaned,
            flags=re.I
        ).strip()
        
        # Clean up multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        if not cleaned or len(cleaned) <= 2:
            return None
        
        # If checking known companies, validate
        if check_known:
            # Check if it's a known company
            if cleaned.lower() in {c.lower() for c in self.known_companies}:
                return cleaned
            
            # Check if it looks like a company (not a person name)
            words = cleaned.split()
            is_likely_company = (
                len(words) >= 3 or
                any(w in cleaned for w in ['Corporation', 'Inc', 'LLC', 'Ltd', 'Group', 'Technologies', 'Systems']) or
                any(len(w) > 12 for w in words)
            )
            
            if is_likely_company:
                return cleaned
            
            return None
        
        return cleaned

    def extract_from_subject_patterns(
        self, subject: str
    ):
        """Extract company and job title from subject using regex patterns.
        
        Args:
            subject: Cleaned email subject line (reply/forward prefixes removed)
            
        Returns:
            Tuple of (company, job_title) - either may be None
        """
        company = None
        job_title = None
        
        # Special case: "applying for Field CTO position @ Claroty"
        special_match = re.search(
            r"applying for ([\w\s\-]+) position @ ([A-Z][\w\s&\-]+)",
            subject
        )
        if special_match:
            job_title = special_match.group(1).strip()
            company = special_match.group(2).strip()
            return company, job_title
        
        # General patterns for company extraction
        patterns = [
            (r"^([A-Z][a-zA-Z]+(?:\s+(?:[A-Z][a-zA-Z]+|&[A-Z]?))*?)(?:\s+application|\s+-)", re.IGNORECASE),
            (r"application (?:to|for|with)\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
            (r"(?:from|with|at)\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
            (r"position\s+@\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
            (r"^([A-Z][\w&-]+(?:\s+[\w&-]+){0,2}?)\s+(?:Job|Application|Interview)\b", re.IGNORECASE),
            (r"-\s*([A-Z][\w&-]+(?:\s+[\w&-]+){0,2}?)\s*-\s*", 0),
            (r"-\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})$", 0),
            (r"(?:your application with|application with|interest in|position (?:here )?at)\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
            (r"update on your ([A-Z][\w&-]+(?:\s+[\w&-]+){0,2}) application\b", re.IGNORECASE),
            (r"thank you for your application with\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
            (r"@\s*([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
        ]
        
        for pattern, flags in patterns:
            match = re.search(pattern, subject, flags)
            if match:
                candidate = self.company_validator.normalize_company_name(match.group(1).strip())
                
                # Person-name safeguard
                if self.company_validator.looks_like_person(candidate):
                    if candidate.lower() not in {c.lower() for c in self.known_companies}:
                        if DEBUG:
                            print(f"[DEBUG] Rejected candidate company as person name: {candidate}")
                        continue
                
                company = candidate
                break
        
        return company, job_title

    def canonicalize_company_name(
        self, company: str, subject: str
    ) -> str:
        """Map company candidate to canonical known name or alias.
        
        Args:
            company: Candidate company name
            subject: Subject line for additional matching
            
        Returns:
            Canonical company name if found, original otherwise
        """
        if not company:
            return company
        
        cand_lower = company.lower()
        subj_lower = subject.lower()
        
        # Check aliases first
        aliases_lower = {k.lower(): v for k, v in self.company_data.get("aliases", {}).items()}
        for alias_lower, canonical in aliases_lower.items():
            alias_pattern = r'\b' + re.escape(alias_lower) + r'\b'
            if re.search(alias_pattern, cand_lower) or re.search(alias_pattern, subj_lower):
                if DEBUG:
                    print(f"[DEBUG] Company alias matched: {alias_lower} -> {canonical}")
                return canonical
        
        # Check known companies list for substrings
        for known in self.company_data.get("known", []):
            if known.lower() in cand_lower or known.lower() in subj_lower:
                if DEBUG:
                    print(f"[DEBUG] Known company matched: {known}")
                return known
        
        return company


class MetadataExtractor:
    """Extract dates, job IDs, and other metadata from email messages."""

    def __init__(self, rule_classifier=None, debug: bool = False):
        """
        Initialize MetadataExtractor.
        
        Args:
            rule_classifier: RuleClassifier instance for accessing compiled patterns
            debug: Enable debug logging
        """
        self._rule_classifier = rule_classifier
        self._debug = debug

    def extract_status_dates(self, body: str, received_date):
        """
        Extract key status dates from email body.
        
        For interview invites, sets interview_date to 7 days in the future
        to mark as "upcoming" (user can manually update with actual date).
        
        Args:
            body: Email body text
            received_date: Date the email was received
            
        Returns:
            Dictionary with response_date, rejection_date, interview_date, follow_up_dates
        """
        body_lower = body.lower()
        dates = {
            "response_date": None,
            "rejection_date": None,
            "interview_date": None,
            "follow_up_dates": [],
        }
        
        if not self._rule_classifier:
            return dates
        
        # Use compiled patterns from RuleClassifier instance
        interview_patterns = self._rule_classifier._msg_label_patterns.get("interview_invite", [])
        rejection_patterns = self._rule_classifier._msg_label_patterns.get("rejection", [])
        response_patterns = self._rule_classifier._msg_label_patterns.get("response", [])
        followup_patterns = self._rule_classifier._msg_label_patterns.get("follow_up", [])
        
        if any(re.search(p, body_lower) for p in response_patterns):
            dates["response_date"] = received_date
        if any(re.search(p, body_lower) for p in rejection_patterns):
            dates["rejection_date"] = received_date
        if any(re.search(p, body_lower) for p in interview_patterns):
            # Set to 7 days in future to mark as "upcoming interview"
            dates["interview_date"] = (received_date + timedelta(days=7)).date()
        if any(re.search(p, body_lower) for p in followup_patterns):
            dates["follow_up_dates"] = received_date
        return dates

    @staticmethod
    def extract_organizer_from_icalendar(body: str, debug: bool = False):
        """
        Extract organizer email from iCalendar data in message body.
        
        Teams/Zoom meeting invites often contain BASE64 encoded iCalendar data
        with ORGANIZER field containing the sender's email address.
        
        Args:
            body: Email body text (may contain BASE64 encoded iCalendar data)
            debug: Enable debug logging
            
        Returns:
            Tuple of (organizer_email, organizer_domain) or (None, None)
        """
        if not body:
            return None, None
        
        # Look for BASE64 encoded iCalendar data
        # Pattern: continuous BASE64 string (common in calendar invites)
        base64_pattern = r'(?:[A-Za-z0-9+/]{60,}\n?)+'
        matches = re.findall(base64_pattern, body)
        
        for match in matches:
            try:
                # Remove newlines and decode
                base64_data = match.replace('\n', '').replace('\r', '')
                decoded = base64.b64decode(base64_data).decode('utf-8', errors='ignore')
                
                # Check if this is iCalendar data
                if 'BEGIN:VCALENDAR' in decoded or 'ORGANIZER' in decoded:
                    # Extract ORGANIZER email
                    # Format: ORGANIZER;CN=Name:mailto:email@domain.com
                    organizer_match = re.search(
                        r'ORGANIZER[^:]*:mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                        decoded,
                        re.IGNORECASE
                    )
                    if organizer_match:
                        email = organizer_match.group(1).lower()
                        domain = email.split('@')[-1] if '@' in email else None
                        if debug:
                            print(f"[DEBUG] Extracted organizer from iCalendar: {email} (domain: {domain})")
                        return email, domain
            except Exception as e:
                if debug:
                    print(f"[DEBUG] Failed to decode/parse iCalendar data: {e}")
                continue
        
        return None, None

    @staticmethod
    def extract_job_id(subject: str) -> str:
        """
        Extract job ID from subject line.
        
        Looks for patterns like:
        - Job #12345
        - Position #ABC-123
        - jobId=XYZ789
        
        Args:
            subject: Email subject line
            
        Returns:
            Job ID string or empty string if not found
        """
        if not subject:
            return ""
        
        id_match = re.search(r"(?:Job\s*#?|Position\s*#?|jobId=)([\w\-]+)", subject, re.IGNORECASE)
        return id_match.group(1).strip() if id_match else ""


# ======================================================================================
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
_metadata_extractor = MetadataExtractor(_rule_classifier, debug=DEBUG)

# --- Load personal_domains.json ---
PERSONAL_DOMAINS_PATH = Path(__file__).parent / "json" / "personal_domains.json"
if PERSONAL_DOMAINS_PATH.exists():
    with open(PERSONAL_DOMAINS_PATH, "r", encoding="utf-8") as f:
        personal_domains_data = json.load(f)
    PERSONAL_DOMAINS = set(personal_domains_data.get("domains", []))
else:
    # Fallback to default list if file doesn't exist
    PERSONAL_DOMAINS = {'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'aol.com', 'icloud.com'}

# Compile application patterns for efficient matching
# Include both message_labels.application AND early_detection.application_confirmation
APPLICATION_PATTERNS = []
app_pattern_sources = []
if "message_labels" in PATTERNS and "application" in PATTERNS["message_labels"]:
    app_pattern_sources.extend(PATTERNS["message_labels"]["application"])
if "early_detection" in PATTERNS and "application_confirmation" in PATTERNS["early_detection"]:
    app_pattern_sources.extend(PATTERNS["early_detection"]["application_confirmation"])

if app_pattern_sources:
    APPLICATION_PATTERNS = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in app_pattern_sources
    ]
# Map from label names used in code to JSON keys
LABEL_MAP = {
    "interview_invite": ["interview", "interview_invite"],
    "job_application": ["application", "job_application"],
    "rejection": ["rejection", "rejected"],  # Consolidated: use 'rejection' as canonical
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


def rule_label(subject: str, body: str = "", sender_domain: str | None = None) -> str | None:
    """Return a rule-based label from compiled regex patterns (delegates to RuleClassifier).

    Checks message text against label patterns in a prioritized order to
    reduce false positives (e.g., prefer noise over rejected for newsletters).
    Returns one of the known labels or None if no rule matches.
    """
    return _rule_classifier.classify(
        subject=subject,
        body=body,
        sender_domain=sender_domain,
        headhunter_domains=HEADHUNTER_DOMAINS,
        job_board_domains=JOB_BOARD_DOMAINS,
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
    if DEBUG:
        print(f"[DEBUG predict_with_fallback] ML label={ml.get('label')}, confidence={conf}")
        print(f"[DEBUG predict_with_fallback] rule_label result={rl}")
        print(f"[DEBUG predict_with_fallback] body length={len(body)}, contains 'newsletter'={('newsletter' in body.lower())}, contains 'digest'={('digest' in body.lower())}")
        if body:
            print(f"[DEBUG predict_with_fallback] body first 500 chars: {body[:500]}")

    # If rule_label returned a result, use it authoritatively (skip ML overrides)
    # BUT preserve the original ML prediction for downstream override logic
    if rl is not None:
        if DEBUG:
            print(f"[DEBUG predict_with_fallback] Using rule-based label '{rl}' authoritatively")
        return {"label": rl, "confidence": 1.0, "fallback": "rule", "ml_label": ml.get("label") if ml else None}

    # (scheduling-language authoritative override removed — revert to earlier behavior)

    # If no rule matched but the sender/domain or body contains ATS/company
    # cues AND the content appears application-related, treat as job_application.
    # This allows ATS-generated confirmations to be authoritative even when
    # no explicit application regex matched earlier.
        d = (sender_domain or "").lower()
        body_lower = (body or "").lower()
        try:
            is_ats_or_company = bool(d and (_is_ats_domain(d) or d in globals().get('JOB_BOARD_DOMAINS', []) or _map_company_by_domain(d)))
        except Exception:
            is_ats_or_company = False

        if is_ats_or_company and is_application_related(subject, body):
            if DEBUG:
                print("[DEBUG predict_with_fallback] OVERRIDING ML -> job_application due to ATS/company domain + application patterns (rl was None)")
            return {"label": "job_application", "confidence": 1.0, "fallback": "rules_override", "ml_label": ml.get("label") if ml else None}

    # Targeted override: If rules detect a job_application and sender/domain or
    # body contain ATS/company cues (Workday, iCIMS, Indeed, List-Unsubscribe, etc.),
    # treat the rule as authoritative and override ML. This is conservative and
    # avoids letting ML label ATS-generated confirmations as head_hunter.
    if rl == "job_application":
        d = (sender_domain or "").lower()
        body_lower = (body or "").lower()
        try:
            is_ats_or_company = bool(d and (_is_ats_domain(d) or d in globals().get('JOB_BOARD_DOMAINS', []) or _map_company_by_domain(d)))
        except Exception:
            is_ats_or_company = False

        if is_ats_or_company:
            if DEBUG:
                print("[DEBUG predict_with_fallback] OVERRIDING ML for job_application due to ATS/company domain")
            return {"label": "job_application", "confidence": 1.0, "fallback": "rules_override", "ml_label": ml.get("label") if ml else None}

    # Targeted rule: If rules detected a rejection or an interview-invite
    # coming from an ATS/company (or body contains ATS markers) AND the
    # content is application-related, treat that rule as authoritative and
    # override ML. This preserves the distinction between application
    # lifecycle events (submission/rejection/interview) and recruiter
    # outreach (head_hunter).
    if rl in ("rejection", "interview_invite"):
        d = (sender_domain or "").lower()
        body_lower = (body or "").lower()
        try:
            is_ats_or_company = bool(d and (_is_ats_domain(d) or d in globals().get('JOB_BOARD_DOMAINS', []) or _map_company_by_domain(d)))
        except Exception:
            is_ats_or_company = False

        if is_ats_or_company and is_application_related(subject, body):
            if DEBUG:
                print(f"[DEBUG predict_with_fallback] OVERRIDING ML with rule {rl} due to ATS/company domain + application patterns")
            return {"label": rl, "confidence": 1.0, "fallback": "rules_override", "ml_label": ml.get("label") if ml else None}
    
    # Allow 'other' to override when ML is trying to force job_application for reminder nudges
    # Treat certain rule labels as high-priority authoritative signals
    # These should override ML predictions even when ML confidence is high
    # because regex-based patterns for these labels are intentionally conservative.
    if rl in ("noise", "offer", "head_hunter", "other", "job_application", "rejection"):
        if DEBUG:
            print(f"[DEBUG predict_with_fallback] OVERRIDING ML with rules: {rl}")
        return {"label": rl, "confidence": 1.0, "fallback": "rules_override", "ml_label": ml.get("label") if ml else None}

    # Targeted override: Indeed Application confirmations should override ML
    # even if ML predicts interview_invite with high confidence.
    if rl == "job_application" and subject and re.search(r"^Indeed\s+Application:\s*", subject, re.I):
        if DEBUG:
            print("[DEBUG predict_with_fallback] OVERRIDING ML for Indeed Application confirmation -> job_application")
        return {"label": "job_application", "confidence": 1.0, "fallback": "rules_override", "ml_label": ml.get("label") if ml else None}
    
    # If ML confidence is low, use rules as fallback
    if not ml or conf < threshold:
        if rl:
            if DEBUG:
                print(f"[DEBUG predict_with_fallback] Using rules fallback (low confidence): {rl}")
            return {"label": rl, "confidence": conf, "fallback": "rules", "ml_label": ml.get("label") if ml else None}
    
    if ml and "confidence" not in ml and "proba" in ml:
        ml = {**ml, "confidence": float(ml["proba"])}
    return ml


# def strip_html_tags(text: str) -> str:
#    if not text:
#        return "Empty"
#    # BeautifulSoup handles nested tags, entities, script/style removal better than regex
#    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def get_stats():
    """Get or create today's IngestionStats row and return it."""
    today = now().date()
    stats, _ = IngestionStats.objects.get_or_create(date=today)
    return stats


def is_application_related(subject, body):
    """Check if message is application-related using patterns from patterns.json.
    
    Args:
        subject: Email subject line
        body: Email body text (first 500 chars recommended)
        
    Returns:
        True if any application pattern matches, False otherwise
    """
    if not APPLICATION_PATTERNS:
        return False
    text = f"{subject or ''} {body or ''}".lower()
    return any(pattern.search(text) for pattern in APPLICATION_PATTERNS)


def decode_part(data, encoding):
    """Decode a MIME part body string using the provided encoding (delegates to EmailBodyParser)."""
    return EmailBodyParser.decode_mime_part(data, encoding)


# def extract_body(payload):
#    """Best-effort plain-text body extraction for simple payloads."""
##    if "parts" in payload:
#        for part in payload["parts"]:
#            mt = part.get("mimeType")
#            data = part.get("body", {}).get("data")
#            if not data:
#               continue
#            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
#            if mt == "text/plain":
#                return decoded
#            if mt == "text/html":
#                return strip_html_tags(decoded)
#    data = payload.get("body", {}).get("data")
#    return (
#        base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore") if data else ""
#    )


def extract_body_from_parts(parts):
    """Extract the first HTML part's body from a Gmail message payload tree (delegates to EmailBodyParser)."""
    return EmailBodyParser.extract_from_gmail_parts(parts)


def _decode_header_value(raw_val: str) -> str:
    """Decode RFC 2047 encoded header values to unicode (delegates to EmailBodyParser)."""
    return EmailBodyParser.decode_header_value(raw_val)


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


PARSER_VERSION = "1.0.0"

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
        if DEBUG:
            print("🤖 Parser: company classifier artifacts loaded (optional).")
    except Exception:
        COMPANY_CLASSIFIER = None
        COMPANY_VECTORIZER = None
        COMPANY_LABEL_ENCODER = None


def is_correlated_message(sender_email, sender_domain, msg_date):
    """
    True if sender matches an existing application and msg_date is within 1 year after first_sent.
    """
    app = get_application_by_sender(sender_email, sender_domain)
    if not app:
        return False

    try:
        app_date = datetime.strptime(app["first_sent"], "%Y-%m-%d %H:%M:%S")
        msg_dt = datetime.strptime(msg_date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False

    one_year_later = app_date + timedelta(days=365)
    return app_date <= msg_dt <= one_year_later


def predict_company(subject, body):
    """Predict company name using the trained ML model."""
    # Use optional company-specific classifier if available; otherwise skip
    if not (COMPANY_CLASSIFIER and COMPANY_VECTORIZER):
        return None
    text = (subject or "") + " " + (body or "")
    try:
        X = COMPANY_VECTORIZER.transform([text])
        pred = COMPANY_CLASSIFIER.predict(X)[0]
        if COMPANY_LABEL_ENCODER is not None and hasattr(COMPANY_LABEL_ENCODER, "inverse_transform"):
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


def extract_metadata(service, msg_id):
    """Extract subject, date, thread_id, labels, sender, sender_domain, and body text from a Gmail message."""
    body_html = ""
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = msg["payload"]["headers"]

    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
    date_raw = next((h["value"] for h in headers if h["name"] == "Date"), "")
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
    body = extract_body_from_parts(parts)

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
            decoded = decode_part(data, encoding)

        if mime_type == "text/plain" and body == "Empty Body" and decoded:
            body = decoded.strip()
        elif mime_type == "text/html" and body != "Empty Body" and decoded:
            body_html = html.unescape(decoded)
            # also provide a plain-text fallback
            body = BeautifulSoup(body_html, "html.parser").get_text(separator=" ", strip=True)

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
        "List-Id", "List-Unsubscribe", "Precedence", 
        "X-Campaign", "X-Mailer", "X-Newsletter",
        "Auto-Submitted", "X-Auto-Response-Suppress",
        "Return-Path", "Reply-To", "Organization",
        "X-Entity-Ref-ID", "X-Sender"
    ]
    
    header_text = []
    for h in headers:
        h_name = h["name"]
        h_value = h["value"].lower()
        
        # Collect headers for classification
        if h_name in classification_headers:
            header_text.append(f"{h_name}: {h['value']}")
        
        # Detect newsletter indicators
        if h_name in ("List-Id", "List-Unsubscribe", "X-Newsletter"):
            header_hints["is_newsletter"] = True
        
        # Detect automated/bulk mail
        if h_name == "Precedence" and "bulk" in h_value:
            header_hints["is_bulk"] = True
        if h_name == "Auto-Submitted" and h_value != "no":
            header_hints["auto_submitted"] = True
        
        # Detect no-reply addresses
        if h_name == "From" and ("noreply" in h_value or "no-reply" in h_value or "donotreply" in h_value):
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
    return MetadataExtractor.extract_organizer_from_icalendar(body, debug=DEBUG)


def parse_subject(subject, body="", sender=None, sender_domain=None):
    """Extract company, job title, and job ID from subject line, sender, and optionally sender domain."""

    if DEBUG:
        print(f"[DEBUG] parse_subject called with:")
        print(f"[DEBUG]   subject={subject[:60]}...")
        print(f"[DEBUG]   sender={sender}")
        print(f"[DEBUG]   sender_domain={sender_domain}")
        print(f"[DEBUG]   body_length={len(body) if body else 0}")

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
    result = predict_with_fallback(predict_subject_type, subject, body, threshold=0.55, sender=sender)
    confidence = _conf(result)
    label = result["label"]
    bool(result.get("ignore", False))

    print("=== PARSE_SUBJECT CALLED ===", flush=True)
    print(f"DEBUG={DEBUG}", flush=True)
    if DEBUG:
        print(f"[DEBUG parse_subject] subject='{subject[:80]}'", flush=True)
        print(f"[DEBUG parse_subject] sender='{sender}'", flush=True)
        print(f"[DEBUG parse_subject] sender_domain='{sender_domain}'", flush=True)
        print(f"[DEBUG parse_subject] label={label}, confidence={confidence}", flush=True)

    # --- Initialize variables ---
    company = ""
    job_title = ""
    job_id = ""
    ats_display_name_fallback = None  # initialize early to satisfy linters

    # --- Continue with original logic for fallback or enrichment ---
    subject_clean = subject.strip()
    # Strip common email reply/forward prefixes that interfere with company extraction
    subject_clean = re.sub(r"^(Re|RE|Fwd|FW|Fw):\s*", "", subject_clean, flags=re.IGNORECASE).strip()
    subj_lower = subject_clean.lower()
    domain_lower = sender_domain.lower() if sender_domain else None

    # --- Check for Teams/Zoom meeting invites with iCalendar data ---
    # Extract organizer email from iCalendar ORGANIZER field (more reliable than sender for calendar invites)
    organizer_email, organizer_domain = extract_organizer_from_icalendar(body)
    if organizer_domain and not domain_lower:
        # Use organizer domain if sender domain not available
        domain_lower = organizer_domain
        if DEBUG:
            print(f"[DEBUG] Using organizer domain from iCalendar: {organizer_domain}")
    elif organizer_domain and organizer_domain != domain_lower:
        # Prefer organizer domain for meeting invites (more accurate than relay servers)
        if re.search(r"meeting id|passcode|join.*meeting|zoom\.us|teams\.microsoft", body, re.I):
            domain_lower = organizer_domain
            if DEBUG:
                print(f"[DEBUG] Overriding sender domain with organizer domain for meeting invite: {organizer_domain}")

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
        is_offer_related = any(re.search(pattern, subj_lower) for pattern in offer_patterns)
        
        if is_offer_related:
            if DEBUG:
                print("[DEBUG] Downgrading label interview_invite -> other (offer-related subject)")
            label = "other"
        # Meeting invites without "interview" keyword - only downgrade generic low-confidence meetings
        # Keep high-confidence ones as they're likely actual interview invites
        elif (
            ("meeting with" in subj_lower or "meeting invitation" in subj_lower) 
            and "interview" not in subj_lower
            and confidence < 0.65
            and not (body and re.search(r"meeting id|passcode|join.*meeting", body, re.I))
        ):
            if DEBUG:
                print("[DEBUG] Downgrading label interview_invite -> other (generic meeting, low confidence)")
            label = "other"
    
    # Upgrade: Calendar meeting invites with meeting details should be interview_invite
    # if they're from a company domain and have meeting/interview/call language
    if label in ("other", "response"):
        has_meeting_details = bool(re.search(r"meeting id|passcode|join.*meeting|zoom\.us|meet\.google|teams\.microsoft", body, re.I))
        has_interview_language = bool(re.search(r"\b(interview|meeting|call|discussion|screen|chat)\b", subj_lower))
        
        # Check if sender is from a company domain (not personal)
        is_company_domain = domain_lower and domain_lower not in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"]
        
        if has_meeting_details and has_interview_language and is_company_domain:
            if DEBUG:
                print(f"[DEBUG] Upgrading {label} -> interview_invite (meeting invite with details)")
            label = "interview_invite"
            confidence = max(0.85, confidence)  # Boost confidence

    # PRIORITY 1: ATS domain with known sender prefix (most reliable)
    # Support subdomains of known ATS domains (e.g., talent.icims.com -> icims.com)
    is_ats_domain = False
    if domain_lower:
        for ats_root in ATS_DOMAINS:
            if domain_lower == ats_root or domain_lower.endswith(f".{ats_root}"):
                is_ats_domain = True
                break
    if not company and is_ats_domain and sender:
        # First try to extract from sender email prefix (e.g., ngc@myworkday.com)
        # Use parseaddr to extract the actual email address from "Display Name <email@domain.com>"
        _, sender_email = parseaddr(sender)
        if sender_email and "@" in sender_email:
            sender_prefix = sender_email.split("@", maxsplit=1)[0].strip().lower()
            # Check if prefix matches an alias
            aliases_lower = {k.lower(): v for k, v in company_data.get("aliases", {}).items()}
            if sender_prefix in aliases_lower:
                company = aliases_lower[sender_prefix]
                if DEBUG:
                    print(f"[DEBUG] ATS alias match: {sender_prefix} -> {company}")

    # Job board application confirmations - extract actual employer from body
    # Works for Indeed, LinkedIn, Dice, etc. - any job board where subject contains "Application"
    if not company and body and subject and re.search(r'\bapplication\b', subject, re.IGNORECASE):
        # Need to get sender_email if not already extracted above
        if 'sender_email' not in locals() and sender:
            _, sender_email = parseaddr(sender)
        else:
            sender_email = ""
        
        if DEBUG:
            print(f"[DEBUG] Checking for job board application confirmation in subject: {subject[:50]}...")
        
        # Check if this is a job board domain or generic confirmation email
        is_job_board_confirmation = (
            domain_lower in JOB_BOARD_DOMAINS or
            "indeedapply" in sender_email or
            "application" in subject.lower()
        )
        
        if is_job_board_confirmation:
            if DEBUG:
                print(f"[DEBUG] Job board confirmation detected, attempting body extraction")
                print(f"[DEBUG] Body length: {len(body) if body else 0} chars")
            
            # Extract plain text body for pattern matching
            body_plain = body
            try:
                if body and ("<html" in body.lower() or "<style" in body.lower()):
                    soup = BeautifulSoup(body, "html.parser")
                    for tag in soup(["style", "script"]):
                        tag.decompose()
                    body_plain = soup.get_text(separator=" ", strip=True)
                    if DEBUG:
                        print(f"[DEBUG] Extracted plain text, length: {len(body_plain)} chars")
            except Exception as e:
                body_plain = body
                if DEBUG:
                    print(f"[DEBUG] HTML parsing failed: {e}, using raw body")

            # Look for "The following items were sent to COMPANY" or "about your application" patterns
            if body_plain:
                # Try pattern 1: "sent to COMPANY"
                job_board_pattern = re.search(
                    r"(?:the following items were sent to|sent to)\s+([A-Z][A-Za-z0-9\s&.,'-]+?)\s*[.\n]",
                    body_plain,
                    re.IGNORECASE,
                )
                if job_board_pattern:
                    if DEBUG:
                        print(f"[DEBUG] Pattern 1 matched: 'sent to COMPANY'")
                else:
                    if DEBUG:
                        print(f"[DEBUG] Pattern 1 did not match, trying pattern 2")
                    # Try pattern 2: "about your application" with company name before it
                    job_board_pattern = re.search(
                        r"<strong>\s*<a[^>]+>([A-Z][A-Za-z0-9\s&.,'-]+?)</a>\s*</strong>.*?about your application",
                        body,
                        re.IGNORECASE | re.DOTALL,
                    )
                    if job_board_pattern and DEBUG:
                        print(f"[DEBUG] Pattern 2 matched")

                if job_board_pattern:
                    extracted = job_board_pattern.group(1).strip()
                    if DEBUG:
                        print(f"[DEBUG] Raw extracted company: '{extracted}'")
                    # Clean up common trailing words
                    extracted = re.sub(
                        r"\s+(and|About|Your|Application|Details)$",
                        "",
                        extracted,
                        flags=re.IGNORECASE,
                    ).strip()
                    # Remove trailing punctuation
                    extracted = extracted.rstrip(".,;:")
                    if extracted and len(extracted) > 2 and is_valid_company_name(extracted):
                        company = extracted
                        if DEBUG:
                            print(f"[DEBUG] Job board employer extraction SUCCESS: {company}")
                    elif DEBUG:
                        print(f"[DEBUG] Extracted company failed validation: '{extracted}'")
                elif DEBUG:
                    print(f"[DEBUG] No job board pattern matched in body")
                    # Show a snippet of the body to help debug
                    snippet_idx = body_plain.lower().find("sent to") if "sent to" in body_plain.lower() else 0
                    if snippet_idx >= 0:
                        print(f"[DEBUG] Body snippet around 'sent to': ...{body_plain[snippet_idx:snippet_idx+150]}...")
            else:
                if DEBUG:
                    print(f"[DEBUG] Body plain is empty, cannot extract company")

    # Generic ATS body patterns - look for company name in application confirmation text
    if not company and body and ("application" in subject.lower() or "applying" in subject.lower() or "applied" in subject.lower()):
        if DEBUG:
            print(f"[DEBUG] Entering ATS body pattern extraction")
        body_plain = body
        try:
            if body and ("<html" in body.lower() or "<style" in body.lower()):
                soup = BeautifulSoup(body, "html.parser")
                for tag in soup(["style", "script"]):
                    tag.decompose()
                body_plain = soup.get_text(separator=" ", strip=True)
        except Exception:
            body_plain = body

        if body_plain:
            if DEBUG:
                print(f"[DEBUG] Body plain length: {len(body_plain)}, first 200 chars: {body_plain[:200]}")
            # Pattern: "application for [POSITION] position here at COMPANY"
            # Pattern: "application for our [POSITION] position at COMPANY"
            # Pattern: "your application for [POSITION] at COMPANY"
            ats_body_patterns = [
                r"position\s+(?:here\s+)?at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\.|[\r\n]|\s+Thank)",
                r"position\s+(?:here\s+)?(?:at|with)\s+([A-Z][A-Za-z0-9\s&.,'-]{2,30})[\r\n.]",
                r"application\s+for\s+(?:our|the)\s+.{5,50}?\s+at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\.|[\r\n])",
                r"considering\s+us\s+at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)\s+as",
                r"considering\s+([A-Z][A-Za-z0-9\s&.,'-]+?)\s+as\s+(?:a\s+)?(?:potential|future)\s+employer",
            ]
            
            for pattern in ats_body_patterns:
                ats_match = re.search(pattern, body_plain, re.IGNORECASE)
                if ats_match:
                    extracted = ats_match.group(1).strip()
                    # Clean up trailing words and punctuation
                    extracted = re.sub(r'\s+(and|the|a|as|at|for|with|in)$', '', extracted, flags=re.IGNORECASE).strip()
                    extracted = extracted.rstrip(".,;:")
                    if extracted and len(extracted) > 1 and is_valid_company_name(extracted):
                        company = normalize_company_name(extracted)
                        if DEBUG:
                            print(f"[DEBUG] ATS body pattern extraction SUCCESS: {company}")
                        break
                    elif DEBUG:
                        print(f"[DEBUG] ATS body pattern matched but failed validation: '{extracted}'")

        # Special case: IntelligenceCareers.gov (NSA ATS) - extract agency from body
        if not company and domain_lower == "intelligencecareers.gov" and body:
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

            # Look for "application to the AGENCY" or "application to AGENCY" pattern
            if body_plain:
                intcareers_pattern = re.search(
                    r"application to (?:the\s+)?([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s+\(|\!|\.|$)",
                    body_plain,
                    re.IGNORECASE,
                )
                if intcareers_pattern:
                    extracted = intcareers_pattern.group(1).strip()
                    # Clean up common suffixes
                    extracted = re.sub(r'\s+\(.*?\)\s*$', '', extracted).strip()
                    if extracted and is_valid_company_name(extracted):
                        company = normalize_company_name(extracted)
                        if DEBUG:
                            print(f"[DEBUG] IntelligenceCareers.gov agency extraction: {company}")

        # Save display name as a fallback candidate (defer until after subject patterns)
        ats_display_name_fallback = None
        if not company:
            display_name, _ = parseaddr(sender)
            cleaned = re.sub(
                r"\b(Workday|Recruiting Team|Careers|Talent Acquisition Team|HR|Hiring|Notification|Notifications|Team|Portal)\b",
                "",
                display_name,
                flags=re.I,
            ).strip()
            # Remove ATS platform suffixes (e.g., "@ icims", "@ Workday", etc.)
            cleaned = re.sub(r'\s*@\s*(icims|workday|greenhouse|lever|indeed)\s*$', '', cleaned, flags=re.I).strip()
            # Clean up multiple spaces
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            if cleaned and len(cleaned) > 2:
                ats_display_name_fallback = cleaned
                if DEBUG:
                    print(f"[DEBUG] ATS display name candidate: {cleaned} (will use if subject patterns fail)")

    # PRIORITY 2: Domain mapping (direct company domains) with subdomain support
    # Skip if domain is (or is under) a known ATS platform; ATS handled separately above.
    company_from_domain = False
    if not company and domain_lower and not _is_ats_domain(domain_lower):
        mapped = _map_company_by_domain(domain_lower)
        if mapped:
            company = mapped
            company_from_domain = True  # Mark that we have a reliable domain-based company
            if DEBUG:
                print(f"[DEBUG] Domain mapping (subdomain aware) used: {domain_lower} -> {company}")

    # PRIORITY 3: Known companies in subject
    if not company and KNOWN_COMPANIES:
        # Sort by length descending to match "Northrop Grumman" before "Northrop"
        sorted_companies = sorted(KNOWN_COMPANIES, key=len, reverse=True)
        for known in sorted_companies:
            if known in subj_lower:
                # Find original casing from known list
                for orig in company_data.get("known", []):
                    if orig.lower() == known:
                        company = orig
                        break
                if not company:  # fallback to title case
                    company = known.title()
                break

    # PRIORITY 3.5: ATS display name (if known company or clearly not a person name)
    # Use this before generic subject patterns to avoid matching locations like "at Hampton, VA"
    if not company and 'ats_display_name_fallback' in locals() and ats_display_name_fallback:
        # Check if it's a known company
        if ats_display_name_fallback.lower() in {c.lower() for c in KNOWN_COMPANIES}:
            company = ats_display_name_fallback
            if DEBUG:
                print(f"[DEBUG] ATS display name used (known company): {company}")
        else:
            # Check if it looks like a company (not a typical person name)
            words = ats_display_name_fallback.split()
            # Person names: typically 2-3 short words, all title case
            # Companies: often contain "Corporation", "LLC", "Inc", or longer names
            is_likely_company = (
                len(words) >= 3 or  # 3+ words likely company
                any(w in ats_display_name_fallback for w in ['Corporation', 'Inc', 'LLC', 'Ltd', 'Group', 'Technologies', 'Systems']) or
                any(len(w) > 12 for w in words)  # Long words suggest company
            )
            if is_likely_company:
                company = ats_display_name_fallback
                if DEBUG:
                    print(f"[DEBUG] ATS display name used (company-like): {company}")
            elif DEBUG:
                print(f"[DEBUG] ATS display name deferred (may be person name): {ats_display_name_fallback}")

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

    # PRIORITY 6: Regex patterns
    # Note: Patterns use limited word capture (1-3 words max for company names) to avoid over-matching
    # Example: "Proofpoint - We have received your application" should extract "Proofpoint", not the whole phrase
    subject_patterns = [
        # Prefer stopping at separators like " application" or " -" to avoid over-capture
        (
            r"^([A-Z][a-zA-Z]+(?:\s+(?:[A-Z][a-zA-Z]+|&[A-Z]?))*?)(?:\s+application|\s+-)",
            re.IGNORECASE,
        ),
        (
            r"application (?:to|for|with)\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b",
            re.IGNORECASE,
        ),
        (r"(?:from|with|at)\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
        (
            r"position\s+@\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b",
            re.IGNORECASE,
        ),  # catches "position @ Claroty"
        (
            r"^([A-Z][\w&-]+(?:\s+[\w&-]+){0,2}?)\s+(?:Job|Application|Interview)\b",
            re.IGNORECASE,
        ),  # Max 3 words, non-greedy
        (
            r"-\s*([A-Z][\w&-]+(?:\s+[\w&-]+){0,2}?)\s*-\s*",
            0,
        ),  # Between dashes, max 3 words
        (
            r"-\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})$",
            0,
        ),  # Trailing company after final dash (e.g., "... - Millennium Corporation")
        # (moved earlier)
        (
            r"(?:your application with|application with|interest in|position at)\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b",
            re.IGNORECASE,
        ),
        (
            r"update on your ([A-Z][\w&-]+(?:\s+[\w&-]+){0,2}) application\b",
            re.IGNORECASE,
        ),
        (
            r"thank you for your application with\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b",
            re.IGNORECASE,
        ),
        (r"@\s*([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
        # Removed the problematic pattern that was matching "Re:" - now handled by prefix stripping above
        (
            r"applying for ([\w\s\-]{1,50}) position @ ([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b",
            re.IGNORECASE,
        ),  # special case
    ]
    # Handle special case: "applying for Field CTO position @ Claroty"
    special_match = re.search(r"applying for ([\w\s\-]+) position @ ([A-Z][\w\s&\-]+)", subject_clean)
    if special_match:
        job_title = special_match.group(1).strip()
        company = special_match.group(2).strip()

    # Skip subject pattern matching if we already have a reliable domain-mapped company
    # (prevents subject patterns from overwriting domain mappings with false positives)
    if not company_from_domain:
        for pat, flags in subject_patterns:
            if not company:
                match = re.search(pat, subject_clean, flags)
                if match:
                    candidate = normalize_company_name(match.group(1).strip())
                    # Person-name safeguard specifically for the generic from/with/at capture or leading patterns
                    if looks_like_person(candidate) and candidate.lower() not in {c.lower() for c in KNOWN_COMPANIES}:
                        if DEBUG:
                            print(f"[DEBUG] Rejected candidate company as person name: {candidate}")
                        continue
                    company = candidate

    # Prefer canonical known company names when candidate contains them as substrings
    # (handles cases like "the Senior Systems Security Engineer position at CSA")
    if company:
        # Try to find a known company or alias inside the candidate or subject
        found = False
        cand_lower = company.lower()
        subj_lower = subject_clean.lower()
        # Check aliases first (map lower->canonical)
        aliases_lower = {k.lower(): v for k, v in company_data.get("aliases", {}).items()}
        for alias_lower, canonical in aliases_lower.items():
            # Use word boundary matching to avoid false matches like "arc" in "research"
            alias_pattern = r'\b' + re.escape(alias_lower) + r'\b'
            if re.search(alias_pattern, cand_lower) or re.search(alias_pattern, subj_lower):
                company = canonical
                found = True
                if DEBUG:
                    print(f"[DEBUG] Company alias matched: {alias_lower} -> {canonical}")
                break
        # Next check known companies list for substrings
        if not found and KNOWN_COMPANIES:
            for known in company_data.get("known", []):
                if known.lower() in cand_lower or known.lower() in subj_lower:
                    company = known
                    found = True
                    if DEBUG:
                        print(f"[DEBUG] Known company matched inside candidate/subject: {known}")
                    break

        # If still not found, handle patterns like "... position at CSA" by extracting text after ' at '
        if not found:
            m_at = re.search(r"position at\s+(.+)$", company, re.IGNORECASE)
            if not m_at:
                parts = re.split(r"\bat\b|@", company, flags=re.IGNORECASE)
                if len(parts) > 1:
                    candidate_after_at = parts[-1].strip()
                else:
                    candidate_after_at = ""
            else:
                candidate_after_at = m_at.group(1).strip()

            if candidate_after_at:
                # Remove leading articles like 'the'
                candidate_after_at = re.sub(r"^the\s+", "", candidate_after_at, flags=re.IGNORECASE).strip()
                # Shorten long captures to first 4 words
                candidate_short = " ".join(candidate_after_at.split()[:4])
                # If this shorter candidate looks like a company, use it
                if candidate_short and not looks_like_person(candidate_short):
                    if DEBUG:
                        print(f"[DEBUG] Extracted company after 'at': {candidate_short}")
                    company = candidate_short

    # 🧼 Sanity checks
    if company and re.search(r"\b(CTO|Engineer|Manager|Director|Intern|Analyst)\b", company, re.I):
        if DEBUG:
            print(f"[DEBUG] Clearing company captured as job title: {company}")
        company = ""
    if company and looks_like_person(company) and company.lower() not in {c.lower() for c in KNOWN_COMPANIES}:
        if DEBUG:
            print(f"[DEBUG] Clearing company captured as person name (post-pass): {company}")
        company = ""

    # PRIORITY 7: ATS display name fallback (only if subject patterns found nothing)
    if not company and 'ats_display_name_fallback' in locals() and ats_display_name_fallback:
        # Additional validation: check if it's a known company or looks like a person name
        # Person names usually have 2-3 short words (first/last name)
        words = ats_display_name_fallback.split()
        is_likely_person = (len(words) == 2 and all(len(w) < 12 for w in words))
        
        if not is_likely_person or ats_display_name_fallback.lower() in {c.lower() for c in KNOWN_COMPANIES}:
            company = ats_display_name_fallback
            if DEBUG:
                print(f"[DEBUG] ATS display name fallback applied: {company}")
        elif DEBUG:
            print(f"[DEBUG] ATS display name rejected (likely person name): {ats_display_name_fallback}")

    # Job title fallback
    if not job_title:
        title_match = re.search(
            r"job\s+(?:submission\s+for|application\s+for|title\s+is)?\s*([\w\s\-]+)",
            subject_clean,
            re.IGNORECASE,
        )
        job_title = title_match.group(1).strip() if title_match else ""

    # Job ID (delegate to MetadataExtractor)
    job_id = MetadataExtractor.extract_job_id(subject_clean)

    # --- Hard-ignore check AFTER company extraction ---
    # If we found a valid company from known list or domain, override noise classification
    if company and (
        (domain_lower and domain_lower in DOMAIN_TO_COMPANY)
        or (subj_lower and any(known in subj_lower for known in KNOWN_COMPANIES))
    ):
        # Valid company detected, not noise - reclassify if needed
        if label == "noise":
            label = "job_application"  # assume application if company found
            confidence = 0.7  # moderate confidence for overridden classification

    # Hard-ignore for resume or known noise patterns (only if no valid company)
    if not company and (
        label == "noise"
        or should_ignore(subject, "")
        or any(re.search(p, subject, re.I) for p in RESUME_NOISE_PATTERNS)
    ):
        return {
            "company": "",
            "job_title": "",
            "job_id": "",
            "predicted_company": "",
            "label": "noise",
            "confidence": 0.9,
            "ignore": True,
        }

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
                "like to introduce" in body_lower or 
                "i'd like to introduce" in body_lower or
                "would like to introduce" in body_lower or
                "want to introduce" in body_lower or
                "introducing you" in body_lower
            )
            
            # Check if this is explicitly a job referral (should NOT be overridden)
            is_job_referral = (
                "employee referral" in subject_lower or
                "has referred you for" in body_lower or
                "referred you for consideration" in body_lower or
                "referred you for a position" in body_lower or
                "referred you for an open position" in body_lower or
                "referred you for this position" in body_lower
            )
            
            # Only override if it's a networking intro and NOT a job referral
            if is_networking_intro and not is_job_referral:
                if DEBUG:
                    print(f"[DEBUG] Internal introduction detected: sender domain {sender_domain} matches company {company}, overriding to 'other'")
                label = "other"
            elif DEBUG and is_job_referral:
                print(f"[DEBUG] Employee job referral detected: keeping as 'referral' (from {sender_domain} at {company})")

    return {
        "company": normalize_company_name(company),
        "job_title": job_title,
        "job_id": job_id,
        "predicted_company": normalize_company_name(company),
        "label": label,
        "confidence": confidence,
        "ignore": False,
    }


def ingest_message(service, msg_id):
    """Ingest a single Gmail message by id into the local database.

    Pipeline: metadata extraction → ML+rules classification → company resolution →
    Message/Application ORM writes → ingestion stats and dedupe checks.
    Returns one of: 'inserted' | 'skipped' | 'ignored' | None on failure.
    """
    # Reload company data if companies.json has been modified
    _reload_domain_map_if_needed()
    
    stats = get_stats()

    try:
        metadata = extract_metadata(service, msg_id)
        body = metadata["body"]  # RFC 5322 compliant body (no headers)
        classification_text = metadata.get("classification_text", body)  # Body + headers for classification
        result = None  #  Prevent UnboundLocalError

        # --- PATCH: Skip and log blank/whitespace-only bodies ---
        if not body or not body.strip():
            if DEBUG:
                print(f"[BLANK BODY] Skipping message {msg_id}: {metadata.get('subject','(no subject)')}")
                print("Stats: ignored++ (blank body)")
            log_ignored_message(msg_id, metadata, reason="blank_body")
            IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
            if hasattr(stats, "total_ignored"):
                stats.total_ignored += 1
            return "ignored"

    except Exception as e:
        if DEBUG:
            print(f"Failed to extract data for {msg_id}: {e}")
        return

    # Use header hints to improve classification
    header_hints = metadata.get("header_hints", {})
    
    # Check if this is a transactional application-related message using patterns.json
    # (ATS systems add List-Unsubscribe headers even to application confirmations)
    is_app_related = is_application_related(
        metadata["subject"], 
        classification_text[:500]  # Use classification_text (body+headers) for pattern matching
    )
    
    if DEBUG:
        print(f"[HEADER HINTS] is_application_related={is_app_related}, is_newsletter={header_hints.get('is_newsletter')}, is_bulk={header_hints.get('is_bulk')}, is_noreply={header_hints.get('is_noreply')}")
    
    # Auto-ignore newsletters and bulk mail ONLY if NOT application-related
    if not is_app_related:
        if header_hints.get("is_newsletter") or (header_hints.get("is_bulk") and header_hints.get("is_noreply")):
            if DEBUG:
                print(f"[HEADER HINTS] Auto-ignoring newsletter/bulk mail: {metadata['subject']}")
            
            # Check if this message already exists in Message table (re-ingestion case)
            existing = Message.objects.filter(msg_id=msg_id).first()
            if existing:
                if DEBUG:
                    print(f"[RE-INGEST] Deleting existing Message record for newsletter: {msg_id}")
                existing.delete()
            
            log_ignored_message(msg_id, metadata, reason="newsletter_headers")
            IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
            if hasattr(stats, "total_ignored"):
                stats.total_ignored += 1
            return "ignored"
    elif DEBUG and header_hints.get("is_newsletter"):
        print(f"[HEADER HINTS] Newsletter header found but application-related (patterns.json), not ignoring: {metadata['subject']}")
    
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
    if '<' in recipient_email and '>' in recipient_email:
        match = re.search(r'<([^>]+)>', recipient_email)
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
        if recipient_domain in PERSONAL_DOMAINS or (is_reply_or_forward and recipient_domain in PERSONAL_DOMAINS):
            if DEBUG:
                print(f"[USER EMAIL] Ignoring user message to personal domain: {recipient_domain}")
            
            # Delete if re-ingesting
            existing = Message.objects.filter(msg_id=msg_id).first()
            if existing:
                existing.delete()
            
            log_ignored_message(msg_id, metadata, reason="user_personal_email")
            IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
            if hasattr(stats, "total_ignored"):
                stats.total_ignored += 1
            return "ignored"
        
        # If ML classifies as noise with reasonable confidence, trust it
        if ml_predicted_label == "noise" and ml_confidence > 0.5:
            if DEBUG:
                print(f"[PATCH] User message classified as noise by ML (confidence={ml_confidence:.2f}), keeping noise label.")
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
            if result:
                result["label"] = "other"
                if mapped_company:
                    result["company"] = mapped_company
                    result["predicted_company"] = mapped_company
            if DEBUG:
                print(f"[PATCH] User-initiated message: label set to 'other', company set to {mapped_company if mapped_company else 'N/A'}.")
        else:
            # User reply/forward to job-related domains → use ML classification
            if DEBUG:
                print(f"[PATCH] User reply/forward to job domain, using ML classification: {ml_predicted_label}")
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
        if result:
            result["label"] = "other"
            result["company"] = company
            result["predicted_company"] = company
        if DEBUG:
            print(f"[PATCH] Overriding label to 'other' and company to {company} for user-sent message.")

    # If parse_subject detected internal introduction and overrode label to 'other', apply to result
    if parsed_subject.get("label") == "other" and isinstance(result, dict) and result.get("label") in ("referral", "interview_invite"):
        sender_domain = metadata.get("sender_domain")
        if sender_domain:
            from_company = parsed_subject.get("company") or parsed_subject.get("predicted_company")
            if from_company:
                mapped_domain_company = _map_company_by_domain(sender_domain)
                if mapped_domain_company and mapped_domain_company.lower() == from_company.lower():
                    result = dict(result)  # Create mutable copy
                    result["label"] = "other"
                    if DEBUG:
                        print(f"[INTERNAL INTRODUCTION] Overriding result label to 'other' for internal introduction: {sender_domain} matches {from_company}")

    if parsed_subject.get("ignore"):
        if DEBUG:
            print(f"Ignored by ML: {metadata['subject']}")
            print("Stats: ignored++ (ML ignore)")
        
        # Check if this message already exists in Message table (re-ingestion case)
        existing = Message.objects.filter(msg_id=msg_id).first()
        if existing:
            if DEBUG:
                print(f"[RE-INGEST] Deleting existing Message record for ignored message: {msg_id}")
            existing.delete()
        
        log_ignored_message(
            msg_id,
            metadata,
            reason=parsed_subject.get("ignore_reason", "ml_ignore"),
        )
        IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
        if hasattr(stats, "total_ignored"):
            stats.total_ignored += 1
        return "ignored"

    status = classify_message(body)
    # Pass actual datetime object for date arithmetic (fixes timedelta concat on str)
    status_dates = extract_status_dates(body, metadata["timestamp"])  # was metadata['date'] (string)

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
    follow_up_str = ", ".join(follow_up_raw) if isinstance(follow_up_raw, list) else str(follow_up_raw)

    labels_raw = metadata.get("labels", [])
    labels_str = ", ".join(labels_raw) if isinstance(labels_raw, list) else str(labels_raw)

    if DEBUG:
        print(f"Inserting message: {metadata['subject']}")

    insert_email_text(msg_id, metadata["subject"], body)

    subject = metadata["subject"]
    sender = metadata.get("sender", "")
    # Use the rule-aware wrapper so authoritative regex rules take precedence
    # over the raw ML prediction during ingestion/re-ingestion. This ensures
    # that matches from `rule_label` (via `predict_with_fallback`) are
    # respected when deciding final labels stored in the DB.
    # Use classification_text (body + headers) for classification
    classification_text = metadata.get("classification_text", body)
    result = predict_with_fallback(predict_subject_type, subject, classification_text, threshold=0.55, sender=sender)

    # Apply internal recruiter override - check if ML originally predicted head_hunter
    # Only override to 'other' for generic recruiting spam, preserve meaningful labels
    if isinstance(result, dict):
        ml_label = result.get("ml_label") or result.get("label")  # Check original ML prediction
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
                        ats_markers = ["workday", "myworkday", "taleo", "icims", "indeed", "list-unsubscribe", "one-click"]
                        has_ats_marker = any(marker in classification_text_lower for marker in ats_markers)
                        
                        if not has_ats_marker:
                            # No ATS markers - this is generic recruiter communication, not real application
                            result = dict(result)
                            result["label"] = "other"
                            if DEBUG:
                                print(f"[INTERNAL RECRUITER] Overriding job_application to 'other' (no ATS markers) for internal recruiter: {sender_domain} → {mapped_company}")
                        elif DEBUG:
                            print(f"[INTERNAL RECRUITER] Preserving job_application (has ATS markers) from internal recruiter: {sender_domain} → {mapped_company}")
                    elif final_label not in ("interview_invite", "rejection", "offer"):
                        # Override generic labels to 'other'
                        result = dict(result)
                        result["label"] = "other"
                        if DEBUG:
                            print(f"[INTERNAL RECRUITER] Overriding {final_label} to 'other' for internal recruiter from company domain: {sender_domain} → {mapped_company}")
                    elif DEBUG:
                        print(f"[INTERNAL RECRUITER] Preserving meaningful label '{final_label}' from internal recruiter: {sender_domain} → {mapped_company}")

    # Check if sender domain is in personal domains list - override to noise
    sender_domain = metadata.get("sender_domain", "").lower()
    if sender_domain and sender_domain in PERSONAL_DOMAINS:
        if DEBUG:
            print(f"[PERSONAL DOMAIN] Detected personal domain: {sender_domain}, overriding to 'noise'")
        result = dict(result)
        result["label"] = "noise"

    # Apply downgrade/upgrade logic for consistency with parse_subject
    subject_clean = re.sub(r"^(Re|RE|Fwd|FW|Fw):\s*", "", subject, flags=re.IGNORECASE).strip()
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
            if DEBUG:
                print(f"[RE-INGEST] Downgrading interview_invite -> other (offer-related: {subject})")
            result["label"] = "other"

        # Classification adjustments should be driven by patterns.json, not hard-coded here.
        # We intentionally avoid duplicating application-confirmation logic in code.
    
    # Upgrade: Calendar meeting invites with meeting details should be interview_invite
    # if they're from a company and have meeting/interview/call language
    # Also check job_application since rules may have overridden based on subject alone
    if result and result.get("label") in ("other", "response", "job_application"):
        has_meeting_details = bool(re.search(r"meeting id|passcode|join.*meeting|zoom\.us|meet\.google|teams\.microsoft|ms teams|microsoft teams", body, re.I))
        # Check subject AND body for interview language (sometimes subject is generic like "Job Submission")
        has_interview_language = bool(re.search(r"\b(interview|meeting|call|discussion|screen|chat)\b", subj_lower)) or \
                                 bool(re.search(r"\b(interview|meeting|call|discussion|screen|chat)\b", body, re.I))
        
        # Check if sender is from a company domain (not personal)
        sender_domain = metadata.get("sender_domain", "").lower()
        is_company_domain = sender_domain and sender_domain not in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"]
        
        if has_meeting_details and has_interview_language and is_company_domain:
            if DEBUG:
                print(f"[RE-INGEST] Upgrading {result['label']} -> interview_invite (meeting invite with details: {subject})")
            result["label"] = "interview_invite"
            result["confidence"] = max(0.85, result.get("confidence", 0.85))  # Boost confidence

    # --- NEW LOGIC: Robust company extraction order ---
    # Add guard: skip company assignment for noise label
    label_guard = result.get("label") if result else None
    skip_company_assignment = label_guard == "noise"
    company_obj = None
    # For user-sent messages, use recipient-mapped company if available
    # Extract just the email address from "Display Name <email@domain.com>" format
    sender_email_only = sender_email
    if '<' in sender_email and '>' in sender_email:
        match = re.search(r'<([^>]+)>', sender_email)
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
            company_obj, _ = Company.objects.get_or_create(
                name=company,
                defaults={
                    "first_contact": metadata["timestamp"],
                    "last_contact": metadata["timestamp"],
                    "confidence": float(result.get("confidence", 0.0)) if result else 0.0,
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
            if DEBUG:
                print(f"[HEADER HINTS] Organization header available: {org}")
    
    if not skip_company_assignment:
        sender_domain = metadata.get("sender_domain", "").lower()
        is_ats = any(d in sender_domain for d in ATS_DOMAINS)
        is_headhunter = sender_domain in HEADHUNTER_DOMAINS
        is_job_board = sender_domain in JOB_BOARD_DOMAINS
        is_personal = sender_domain in PERSONAL_DOMAINS
        
        # Personal domain check - completely ignore these messages UNLESS they're user-sent
        # (User-sent messages from personal domains like gmail.com going to recruiters are legitimate)
        # Extract just the email address from "Display Name <email@domain.com>" format
        sender_email_only = sender_email
        if '<' in sender_email and '>' in sender_email:
            match = re.search(r'<([^>]+)>', sender_email)
            if match:
                sender_email_only = match.group(1).strip().lower()
        is_user_sent = user_email and sender_email_only.startswith(user_email)
        if is_personal and not is_user_sent:
            if DEBUG:
                print(f"[PERSONAL DOMAIN] Ignoring message from personal domain: {sender_domain}")
            
            # Delete existing message if re-ingesting
            existing = Message.objects.filter(msg_id=msg_id).first()
            if existing:
                if DEBUG:
                    print(f"[PERSONAL DOMAIN] Deleting existing message: {msg_id}")
                existing.delete()
            
            # Log as ignored
            log_ignored_message(msg_id, metadata, reason="personal_domain")
            IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
            if hasattr(stats, "total_ignored"):
                stats.total_ignored += 1
            return "ignored"

        # Job-board messages should be treated as noise (similar to job_alert)
        # EXCEPT application confirmations where user applied through the job board
        if is_job_board:
            # Check if this is an application confirmation (subject contains "Application")
            is_application_confirmation = (
                subject and re.search(r'\bapplication\b', subject, re.IGNORECASE)
            )
            
            if not is_application_confirmation:
                if DEBUG:
                    print(f"[JOB BOARD] Marking message from job-board domain as noise: {sender_domain}")
                if not result:
                    result = {"label": "noise", "confidence": 1.0}
                else:
                    result["label"] = "noise"
                    result["confidence"] = 1.0
                skip_company_assignment = True
            else:
                if DEBUG:
                    print(f"[JOB BOARD] Application confirmation detected, will extract company from body")
                # Don't skip company assignment for application confirmations
                skip_company_assignment = False

        # 0. Headhunter domain check (highest priority)
        if is_headhunter:
            company = None
            company_source = "headhunter_domain"
            if DEBUG:
                print(f"Headhunter domain detected: {sender_domain} → (no company)")

        # 1. Domain mapping (applies to all non-headhunter domains, including ATS)
        #    Some ATS send confirmations from vendor domains; we still want
        #    to resolve to the hiring company's domain mapping when available.
        if not company and sender_domain:
            mapped = _map_company_by_domain(sender_domain)
            if mapped:
                company = mapped
                company_source = "domain_mapping"
                if DEBUG:
                    print(f"Domain mapping (subdomain aware) used: {sender_domain} → {company}")

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
                        if DEBUG:
                            print(f"USAStaffing organization extraction: {company}")

        # 1.6. Indeed job board special case - extract actual employer from body
        if not company and sender_domain == "indeed.com":
            # Check for Indeed Apply confirmation pattern
            if "Indeed Application:" in subject or "indeedapply@indeed.com" in metadata.get("sender", "").lower():
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
                        r"(?:the following items were sent to|about your application.*?with)\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s+(?:and|About|Your application|Resume|Cover letter|\n|$))",
                        body_plain,
                        re.IGNORECASE,
                    )
                    if indeed_pattern:
                        extracted = indeed_pattern.group(1).strip()
                        # Clean up common trailing words
                        extracted = re.sub(r"\s+(and|About|Your)$", "", extracted, flags=re.IGNORECASE).strip()
                        if extracted and is_valid_company_name(extracted):
                            company = normalize_company_name(extracted)
                            company_source = "indeed_body_extraction"
                            if DEBUG:
                                print(f"Indeed employer extraction: {company}")

        # 2. Subject/body parse (if not resolved by domain or Indeed extraction)
        # Skip for headhunters - they should not have a company assigned
        if not company and not is_headhunter:
            parsed_company = parsed_subject.get("company", "") or ""
            if parsed_company and is_valid_company_name(parsed_company):
                company = normalize_company_name(parsed_company)
                company_source = "subject_parse"
                if DEBUG:
                    print(f"Subject/body parse used: {company}")

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
                        if body and ("<html" in body.lower() or "<style" in body.lower()):
                            soup = BeautifulSoup(body, "html.parser")
                            for tag in soup(["style", "script"]):
                                tag.decompose()
                            body_plain = soup.get_text(separator=" ", strip=True)
                    except Exception:
                        body_plain = body

                    if predicted.lower() in subject.lower() or (body_plain and predicted.lower() in body_plain.lower()):
                        company = normalize_company_name(predicted)
                        company_source = "ml_prediction"
                        if DEBUG:
                            print(f"ML prediction used: {predicted}")
                    elif DEBUG:
                        print(f"ML prediction discarded (not in subject/body): {predicted}")
            except NameError:
                if DEBUG:
                    print(" ML prediction function not available.")

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
                if DEBUG:
                    print(f"'@' symbol match used: {company}")

        if not company:
            body_match = re.search(
                r"(?:apply(?:ing)? to|application to|interest in|position at|role at|opportunity with)\s+([A-Z][\w\s&\-]+)",
                body,
                re.IGNORECASE,
            )
            if body_match:
                company = body_match.group(1).strip()
                company_source = "body_regex"
                if DEBUG:
                    print(f" Body regex used: {company}")

        # 5. Sender name fallback (rare, last resort)
        if not company:
            sender_name = metadata.get("sender", "").split("<")[0].strip().lower()
            for known in KNOWN_COMPANIES:
                if known.lower() in sender_name:
                    company = known
                    company_source = "sender_name_match"
                    if DEBUG:
                        print(f" Sender name match: {sender_name} → {company}")
                    break

        # 6. Organization header fallback
        if not company and org_fallback:
            company = org_fallback
            company_source = "organization_header"
            if DEBUG:
                print(f"[HEADER HINTS] Using Organization header: {company}")
        
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
                    print(f"Subject mentions different company: {known} vs resolved {company}")
                    break

    confidence = float(result.get("confidence", 0.0)) if result else 0.0

    # For user-sent messages, guarantee company_obj and label 'other' are set using recipient domain
    if user_email and sender_email.startswith(user_email):
        mapped_company = None
        if recipient_domain:
            mapped_company = _map_company_by_domain(recipient_domain)
        if mapped_company:
            company = normalize_company_name(mapped_company)
            company_obj, _ = Company.objects.get_or_create(
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
                if DEBUG:
                    print(f"Set domain for {company}: {recipient_domain}")
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
            company_obj, _ = Company.objects.get_or_create(
                name=company,
                defaults={
                    "first_contact": metadata["timestamp"],
                    "last_contact": metadata["timestamp"],
                    "confidence": confidence,
                },
            )
            if company_obj and not company_obj.domain:
                sender_domain = metadata.get("sender_domain", "").lower()
                if sender_domain:
                    company_obj.domain = sender_domain
                    company_obj.save()
                    if DEBUG:
                        print(f"Set domain for {company}: {sender_domain}")
        elif skip_company_assignment and DEBUG:
            print(f"Skipping company assignment for noise message")

    if DEBUG:
        confidence = result.get("confidence", 0.0) if result else 0.0
        print(f"Final company: {company}")
        print(f"company_obj: {company_obj}")
        print(f"ML label: {result.get('label') if result else 'unknown'}")
        print(f"confidence: {confidence}")

    #
    # This is the re-ingest logic
    #
    #  Skip logic (now safe to run after enrichment)
    existing = Message.objects.filter(msg_id=msg_id).first()
    if existing:
        # Snapshot original fields so we can avoid overwriting reviewed messages
        _ORIG_ML_LABEL = existing.ml_label
        _ORIG_CONFIDENCE = getattr(existing, "confidence", None)
        _ORIG_COMPANY = getattr(existing, "company", None)
        _ORIG_COMPANY_SOURCE = getattr(existing, "company_source", None)
        # Preserve the original reviewed state so we only restore originals
        # when the message was actually reviewed before re-ingest.
        _ORIG_REVIEWED = getattr(existing, "reviewed", False)
        # Allow an explicit override via environment variable for batch jobs
        OVERWRITE_REVIEWED = os.environ.get("OVERWRITE_REVIEWED", "").lower() in ("1", "true", "yes")
        if DEBUG:
            print(f"Updating existing message: {msg_id}")
            print(f"Stats: skipped++ (re-ingest)")

        # Special handling for user-sent messages during re-ingestion
        # ONLY apply 'other' label to user-INITIATED messages (not replies/forwards)
        user_email = (os.environ.get("USER_EMAIL_ADDRESS") or "").strip().lower()
        sender_full = (metadata.get("sender") or "").lower()
        # Extract email address from "Name <email@domain.com>" format
        sender_email = sender_full
        if "<" in sender_full and ">" in sender_full:
            sender_email = sender_full[sender_full.index("<")+1:sender_full.index(">")]
        
        subject = metadata.get("subject", "")
        is_reply_or_forward = subject.lower().startswith(("re:", "fwd:", "fw:"))
        
        # CRITICAL: Only override label for user-initiated messages, NOT replies/forwards
        if user_email and sender_email.startswith(user_email) and not is_reply_or_forward:
            # Force label to 'other' and map company from recipient domain
            recipient_email = metadata.get("to", "").lower()
            # Fallback: try to extract recipient from body for forwarded messages
            if not recipient_email:
                body = metadata.get("body", "")
                m = re.search(r"^To:\s*([\w.\-+]+@[\w.\-]+)", body, re.MULTILINE | re.IGNORECASE)
                if m:
                    recipient_email = m.group(1).strip().lower()
            
            recipient_domain = recipient_email.split("@")[-1] if "@" in recipient_email else ""
            
            # Check ML classification first - if it's noise, keep it as noise
            ml_predicted_label = result.get("label") if result else None
            ml_confidence = float(result.get("confidence", 0)) if result else 0
            
            if ml_predicted_label == "noise" and ml_confidence > 0.5:
                # Trust ML noise classification for user-sent messages (personal emails)
                existing.ml_label = "noise"
                existing.confidence = ml_confidence
                if DEBUG:
                    print(f"[RE-INGEST] User-initiated message classified as noise by ML (confidence={ml_confidence:.2f})")
            else:
                # Non-noise user-initiated message → job outreach
                if recipient_domain:
                    mapped_company = _map_company_by_domain(recipient_domain)
                    if mapped_company:
                        company_obj, _ = Company.objects.get_or_create(
                            name=normalize_company_name(mapped_company),
                            defaults={
                                "first_contact": metadata["timestamp"],
                                "last_contact": metadata["timestamp"],
                            },
                        )
                        existing.company = company_obj
                        existing.company_source = "user_sent_to_company"
                existing.ml_label = "other"
                existing.confidence = 1.0
                if DEBUG:
                    print(f"[RE-INGEST] User-initiated message: label='other', company={company_obj.name if company_obj else 'None'}")
        elif user_email and sender_email.startswith(user_email) and is_reply_or_forward:
            # Check if reply is to personal domain → classify as noise
            if recipient_domain in PERSONAL_DOMAINS:
                existing.ml_label = "noise"
                existing.confidence = 0.85
                existing.company = None
                existing.company_source = ""
                if DEBUG:
                    print(f"[RE-INGEST] User reply to personal domain ({recipient_domain}), classified as noise")
            else:
                # User replies/forwards to job domains: update with ML classification results
                if result:
                    existing.ml_label = result["label"]
                    existing.confidence = result["confidence"]
                    existing.classification_source = result.get("fallback") or "ml"
                # Update company normally
                if skip_company_assignment and existing.reviewed:
                    existing.company = None
                    existing.company_source = ""
                elif company_obj:
                    existing.company = company_obj
                    existing.company_source = company_source
                if DEBUG:
                    print(f"[RE-INGEST] User reply/forward to job domain updated: label={result['label'] if result else 'N/A'}, company={company_obj.name if company_obj else 'None'}")
        # Update company (including clearing it for noise messages)
        elif skip_company_assignment:
            # Noise messages (reviewed or not) should have no company
            existing.company = None
            existing.company_source = ""
        elif company_obj:
            # Normal messages get the resolved company
            existing.company = company_obj
            existing.company_source = company_source

        # Headhunter enforcement for re-ingestion: ALL headhunter messages should be head_hunter
        if result:
            sender_domain = (metadata.get("sender_domain") or "").lower()
            is_hh_sender = sender_domain in HEADHUNTER_DOMAINS
            company_name_norm = (company_obj.name if company_obj else "").strip().lower()
            company_domain_norm = (getattr(company_obj, "domain", "") or "").strip().lower() if company_obj else ""
            is_hh_company_domain = (
                any(company_domain_norm.endswith(d) for d in HEADHUNTER_DOMAINS) if company_domain_norm else False
            )
            is_hh_company_status = getattr(company_obj, "status", "") == "headhunter" if company_obj else False
            is_hh_company_name = company_name_norm == "headhunter"

            if is_hh_sender or is_hh_company_domain or is_hh_company_status or is_hh_company_name:
                if DEBUG:
                    print(f"[RE-INGEST HEADHUNTER] Forcing label to head_hunter (was: {result.get('label')})")
                result["label"] = "head_hunter"
        
        # Forwarded message detection for re-ingestion: override label to "other"
        subject_for_check = metadata.get("subject", "").strip()
        if re.match(r"^(Fwd|FW|Fw):\s*", subject_for_check, re.IGNORECASE) and company_obj:
            if DEBUG:
                print(f"[RE-INGEST FORWARD] Subject starts with Fwd/FW and company resolved: {company_obj.name}")
                print(f"[RE-INGEST FORWARD] Original label: {result.get('label') if result else 'N/A'}, overriding to 'other'")
            if result:
                result["label"] = "other"
                result["confidence"] = 0.95
        
        # Update label/confidence for non-user messages
        if result and not (user_email and sender_email.startswith(user_email)):
            existing.ml_label = result["label"]
            existing.confidence = result["confidence"]
            existing.classification_source = result.get("fallback") or "ml"
        
        # Only auto-mark as reviewed if not already reviewed AND meets high-confidence criteria
        # This preserves manual review status during re-ingestion
        # Exclude "other" and "noise" from auto-review as they are typically status updates or non-actionable
        if not existing.reviewed and (
            result
            and result.get("confidence", 0.0) >= 0.85
            and result.get("label") not in ("noise", "other")
            and company_obj is not None
            and is_valid_company(company)
        ):
            # Allow callers to suppress auto-review (e.g., re-ingest from Label Messages UI)
            if os.environ.get("SUPPRESS_AUTO_REVIEW", "").lower() not in ("1", "true", "yes"):
                existing.reviewed = True
        # If the message was manually reviewed and overwrite is not requested,
        # restore original label/confidence/company to avoid accidental ML overwrites.
        # Only restore original label/confidence/company if the message was
        # already reviewed before re-ingest and overwrite is not requested.
        if _ORIG_REVIEWED and not OVERWRITE_REVIEWED:
            existing.ml_label = _ORIG_ML_LABEL
            if _ORIG_CONFIDENCE is not None:
                existing.confidence = _ORIG_CONFIDENCE
            existing.company = _ORIG_COMPANY
            existing.company_source = _ORIG_COMPANY_SOURCE

        existing.save()
        # Propagate ml_label to ThreadTracking so label changes reflect in dashboard
        try:
            from tracker.utils import propagate_message_label_to_thread

            propagate_message_label_to_thread(existing)
        except Exception:
            # Keep parsing resilient; propagation is best-effort
            pass

        # ✅ Also update Application record during re-ingestion if dates are missing
        ml_label = result.get("label") if result else None
        if company_obj and ml_label:
            try:
                app = ThreadTracking.objects.filter(thread_id=metadata["thread_id"]).first()
                if DEBUG:
                    print(
                        f"[Re-ingest] Looking for Application with thread_id={metadata['thread_id']}, found: {app is not None}"
                    )
                if app:
                    if DEBUG:
                        print(
                            f"[Re-ingest] App ml_label={app.ml_label}, rejection_date={app.rejection_date}, ml_label_param={ml_label}"
                        )
                    updated = False
                    # Normalize: treat both 'rejected' and 'rejection' as rejection outcome
                    if not app.rejection_date and ml_label in ("rejected", "rejection"):
                        app.rejection_date = metadata["timestamp"].date()
                        updated = True
                        if DEBUG:
                            print(f"✓ Set rejection_date during re-ingest: {app.rejection_date}")
                        # Only set interview_date from ML label when confidence is high
                        try:
                            ml_conf = float(result.get("confidence", 0.0)) if result else 0.0
                        except Exception:
                            ml_conf = 0.0
                        if not app.interview_date and ml_label == "interview_invite" and ml_conf >= 0.7:
                            app.interview_date = metadata["timestamp"].date()
                        updated = True
                        if DEBUG:
                            print(f"✓ Set interview_date during re-ingest: {app.interview_date}")
                    if not app.ml_label or app.ml_label != ml_label:
                        app.ml_label = ml_label
                        app.ml_confidence = float(result.get("confidence", 0.0)) if result else 0.0
                        updated = True
                    if updated:
                        app.save()
                        if DEBUG:
                            print(f"✓ Updated Application during re-ingest")
                else:
                    if DEBUG:
                        print(f"[Re-ingest] No Application found for thread_id={metadata['thread_id']}")
            except Exception as e:
                if DEBUG:
                    print(f"Warning: Could not update Application during re-ingest: {e}")

        IngestionStats.objects.filter(date=stats.date).update(total_skipped=F("total_skipped") + 1)
        if hasattr(stats, "total_skipped"):
            stats.total_skipped += 1
        return "skipped"

    reviewed = (
        result
        and result.get("confidence", 0.0) >= 0.85
        and result.get("label") != "noise"
        and company_obj is not None
        and is_valid_company(company)
    )
    # or whatever threshold you trust
    if DEBUG and not reviewed:
        print(
            f"Not reviewed: confidence={result.get('confidence', 0.0):.2f}, label={result.get('label')}, company={company}"
        )

    # ✅ Enhanced duplicate detection: Use body hash for reliable deduplication
    # This catches both Gmail re-ingestion and EML uploads of the same message
    ts = metadata["timestamp"]
    body = metadata["body"]
    
    # Compute SHA256 hash of body content (normalized)
    # Strip whitespace and normalize line endings for consistent hashing
    normalized_body = re.sub(r'\s+', ' ', body or "").strip()
    body_hash = hashlib.sha256(normalized_body.encode('utf-8')).hexdigest()
    
    # First check: Body hash match (most reliable - catches exact content duplicates)
    if body_hash:
        hash_duplicate_qs = Message.objects.filter(body_hash=body_hash)
        if hash_duplicate_qs.exists():
            existing = hash_duplicate_qs.first()
            if DEBUG:
                print(f"⚠️ BODY HASH duplicate detected: subject='{subject[:60]}...'")
                print(f"   Existing msg_id: {existing.msg_id}, New msg_id: {msg_id}")
                print(f"   Body hash: {body_hash[:16]}...")
                print(f"   Skipping duplicate (same body content)")
            IgnoredMessage.objects.get_or_create(
                msg_id=msg_id,
                defaults={
                    "subject": subject,
                    "body": metadata["body"],
                    "company_source": company_source or "",
                    "sender": metadata["sender"],
                    "sender_domain": (metadata["sender"].split("@")[-1] if "@" in metadata["sender"] else ""),
                    "date": ts,
                    "reason": "duplicate_body_hash",
                },
            )
            stats.total_ignored += 1
            IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
            return "ignored"
    
    # Second check: Exact timestamp match (for messages with empty/malformed bodies)
    exact_duplicate_qs = Message.objects.filter(
        subject=subject,
        sender=metadata["sender"],
        timestamp=ts,
    )
    if exact_duplicate_qs.exists():
        existing = exact_duplicate_qs.first()
        if DEBUG:
            print(f"⚠️ EXACT duplicate detected: subject='{subject}', sender='{metadata['sender']}', ts={ts}")
            print(f"   Existing msg_id: {existing.msg_id}, New msg_id: {msg_id}")
            print(f"   Skipping duplicate (same timestamp to the second)")
        IgnoredMessage.objects.get_or_create(
            msg_id=msg_id,
            defaults={
                "subject": subject,
                "body": metadata["body"],
                "company_source": company_source or "",
                "sender": metadata["sender"],
                "sender_domain": (metadata["sender"].split("@")[-1] if "@" in metadata["sender"] else ""),
                "date": ts,
                "reason": "duplicate_exact",
            },
        )
        stats.total_ignored += 1
        IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
        return "ignored"
    
    # Third check: Near-duplicate (within 5-second window for quick re-sends)
    window_start = ts - timedelta(seconds=5)
    window_end = ts + timedelta(seconds=5)
    near_duplicate_qs = Message.objects.filter(
        subject=subject,
        sender=metadata["sender"],
        timestamp__gte=window_start,
        timestamp__lte=window_end,
    )
    if near_duplicate_qs.exists():
        existing = near_duplicate_qs.first()
        if DEBUG:
            print(f"⚠️ Near duplicate detected: subject='{subject}', sender='{metadata['sender']}'")
            print(f"   Existing timestamp: {existing.timestamp}, New timestamp: {ts}")
            print(f"   Delta: {abs((existing.timestamp - ts).total_seconds())} seconds")
        IgnoredMessage.objects.get_or_create(
            msg_id=msg_id,
            defaults={
                "subject": subject,
                "body": metadata["body"],
                "company_source": company_source or "",
                "sender": metadata["sender"],
                "sender_domain": (metadata["sender"].split("@")[-1] if "@" in metadata["sender"] else ""),
                "date": ts,
                "reason": "duplicate_near",
            },
        )
        stats.total_ignored += 1
        IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
        return "ignored"

    # Headhunter enforcement: ALL messages from headhunter domains/companies should be labeled head_hunter
    if result:
        sender_domain = (metadata.get("sender_domain") or "").lower()
        is_hh_sender = sender_domain in HEADHUNTER_DOMAINS
        company_name_norm = (company_obj.name if company_obj else "").strip().lower()
        company_domain_norm = (getattr(company_obj, "domain", "") or "").strip().lower() if company_obj else ""
        is_hh_company_domain = (
            any(company_domain_norm.endswith(d) for d in HEADHUNTER_DOMAINS) if company_domain_norm else False
        )
        is_hh_company_status = getattr(company_obj, "status", "") == "headhunter" if company_obj else False
        is_hh_company_name = company_name_norm == "headhunter"

        # Force head_hunter label if from headhunter domain or company (regardless of ML classification)
        if is_hh_sender or is_hh_company_domain or is_hh_company_status or is_hh_company_name:
            if DEBUG:
                print(f"[HEADHUNTER ENFORCEMENT] Forcing label to head_hunter (was: {result.get('label')})")
            result["label"] = "head_hunter"
        
        # Forwarded message detection: if subject starts with "Fwd:" or "FW:" and company is resolved,
        # automatically label as "other" to prevent counting forwards as actual interview invites/applications
        subject_for_check = metadata.get("subject", "").strip()
        if re.match(r"^(Fwd|FW|Fw):\s*", subject_for_check, re.IGNORECASE) and company_obj:
            if DEBUG:
                print(f"[FORWARD DETECTION] Subject starts with Fwd/FW and company resolved: {company_obj.name}")
                print(f"[FORWARD DETECTION] Original label: {result.get('label')}, overriding to 'other'")
            result["label"] = "other"
            result["confidence"] = 0.95  # High confidence for forward detection

        # ✅ Now safe to insert Message with enriched company
        # Use safe fallback for body_html because unit tests' mocked metadata may omit it
        # For user-INITIATED messages (not replies/forwards), use company_obj from recipient domain and label 'other'
        if user_email and sender_email.startswith(user_email) and not is_reply_or_forward:
            mapped_company = None
            if recipient_domain:
                mapped_company = _map_company_by_domain(recipient_domain)
            if mapped_company:
                company_obj, _ = Company.objects.get_or_create(
                    name=normalize_company_name(mapped_company),
                    defaults={
                        "first_contact": metadata["timestamp"],
                        "last_contact": metadata["timestamp"],
                        "confidence": float(result.get("confidence", 0.0)) if result else 0.0,
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
    # ✅ Create or update Application record using Django ORM

    # ✅ Fallback: if pattern-based extraction didn't find rejection/interview dates,
    # but ML classified it as rejected/interview_invite, use message timestamp
    ml_label = result.get("label") if result else None
    rejection_date_final = status_dates["rejection_date"]
    interview_date_final = status_dates["interview_date"]

    # Treat both 'rejection' and 'rejected' as rejection outcomes
    if not rejection_date_final and ml_label in ("rejected", "rejection"):
        rejection_date_final = metadata["timestamp"].date()
        if DEBUG:
            print(f"✓ Set rejection_date from ML label: {rejection_date_final}")

    # If ML indicates an interview and confidence is sufficient, set a conservative interview_date
    # Accept multiple label variants that contain 'interview'
    if not interview_date_final and ml_label and "interview" in str(ml_label).lower():
        # Only derive an interview_date from the ML label when confidence is high;
        # otherwise leave interview_date unset so it doesn't create false positives.
        try:
            ml_conf = float(result.get("confidence", 0.0)) if result else 0.0
        except Exception:
            ml_conf = 0.0
        if ml_conf >= 0.7:
            # Set to the message timestamp date as the conservative interview milestone
            interview_date_final = metadata["timestamp"].date()
            if DEBUG:
                print(f"✓ Set interview_date from ML label (message date): {interview_date_final}")

    try:
        message_obj = Message.objects.get(msg_id=msg_id)
        
        # Guard: If company_obj is missing but message was created, log it
        if not company_obj:
            if DEBUG:
                print(f"⚠️  Warning: Message created without company_obj for {msg_id}")
                print(f"   Subject: {metadata.get('subject', '')[:60]}")
                print(f"   ML Label: {ml_label}")
                print(f"   ThreadTracking creation will be skipped")
        
        # Guard: If message_obj lookup failed, log it
        if not message_obj:
            if DEBUG:
                print(f"⚠️  Warning: Could not retrieve Message object for {msg_id}")
                print(f"   ThreadTracking creation will be skipped")
        
        if company_obj and message_obj:
            # Headhunter guard: do NOT create Application records for headhunters
            sender_domain = (metadata.get("sender_domain") or "").lower()
            is_hh_sender = sender_domain in HEADHUNTER_DOMAINS
            company_name_norm = (company_obj.name or "").strip().lower()
            company_domain_norm = (getattr(company_obj, "domain", "") or "").strip().lower()
            is_hh_company_domain = (
                any(company_domain_norm.endswith(d) for d in HEADHUNTER_DOMAINS) if company_domain_norm else False
            )
            is_hh_label = ml_label == "head_hunter"
            is_hh_company_name = company_name_norm == "headhunter"

            skip_application_creation = is_hh_sender or is_hh_label or is_hh_company_domain or is_hh_company_name

            if skip_application_creation:
                if DEBUG:
                    print("↩️ Skipping ThreadTracking creation for headhunter source/company")
                # Do not create or update Application for headhunters
            else:
                # Create ThreadTracking for applications and interview invites
                if ml_label in ("job_application", "interview_invite"):
                    application_obj, created = ThreadTracking.objects.get_or_create(
                        thread_id=metadata["thread_id"],
                        defaults={
                            "company": company_obj,
                            "company_source": company_source,
                            "job_title": parsed_subject.get("job_title", ""),
                            "job_id": parsed_subject.get("job_id", ""),
                            "status": status,
                            "sent_date": metadata["timestamp"].date(),
                            "rejection_date": rejection_date_final,
                            "interview_date": interview_date_final,
                            "ml_label": ml_label,
                            "ml_confidence": (float(result.get("confidence", 0.0)) if result else 0.0),
                            "reviewed": reviewed,
                        },
                    )

                    # ✅ Update existing application if dates are missing but ML classified it
                    if not created:
                        updated = False
                        # Also update company if it's different (fix company mismatch)
                        if application_obj.company != company_obj and company_obj is not None:
                            application_obj.company = company_obj
                            application_obj.company_source = company_source
                            updated = True
                            if DEBUG:
                                print(f"✓ Updated application company: {company_obj.name}")
                        if not application_obj.rejection_date and ml_label == "rejected":
                            application_obj.rejection_date = rejection_date_final
                            updated = True
                        if not application_obj.interview_date and ml_label == "interview_invite":
                            application_obj.interview_date = interview_date_final
                            updated = True
                        if updated:
                            application_obj.save()
                            if DEBUG:
                                print(f"✓ Updated existing application with ML-derived dates")
                    if created:
                        if DEBUG:
                            print("Stats: inserted++ (new application)")
                        IngestionStats.objects.filter(date=stats.date).update(total_inserted=F("total_inserted") + 1)
                        if hasattr(stats, "total_inserted"):
                            stats.total_inserted += 1
                    else:
                        if DEBUG:
                            print("Stats: ignored++ (duplicate application)")
                        IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
                        if hasattr(stats, "total_ignored"):
                            stats.total_ignored += 1
                else:
                    # Not an application email: update existing Application if present, do not create a new one
                    try:
                        application_obj = ThreadTracking.objects.get(thread_id=metadata["thread_id"])
                        updated = False
                        # Also update company if it's different (fix company mismatch)
                        if application_obj.company != company_obj and company_obj is not None:
                            application_obj.company = company_obj
                            application_obj.company_source = company_source
                            updated = True
                            if DEBUG:
                                print(f"✓ Updated application company: {company_obj.name}")
                        if not application_obj.rejection_date and ml_label == "rejected":
                            application_obj.rejection_date = rejection_date_final
                            updated = True
                        if not application_obj.interview_date and ml_label == "interview_invite":
                            application_obj.interview_date = interview_date_final
                            updated = True
                        if updated:
                            application_obj.save()
                            if DEBUG:
                                print("✓ Updated existing application (no new creation)")
                    except ThreadTracking.DoesNotExist:
                        if DEBUG:
                            print(
                                "ℹ️ No existing ThreadTracking for this thread; not creating because this is not a job_application email"
                            )
        else:
            # Missing company_obj or message_obj - try fallback ThreadTracking creation if applicable
            if ml_label in ("job_application", "interview_invite") and not company_obj:
                if DEBUG:
                    print(f"⚠️  job_application/interview_invite without company - attempting fallback")
                # Try to extract company from Message if it was created
                try:
                    fallback_msg = Message.objects.get(msg_id=msg_id)
                    if fallback_msg.company:
                        company_obj = fallback_msg.company
                        company_source = fallback_msg.company_source
                        if DEBUG:
                            print(f"✓ Retrieved company from Message: {company_obj.name}")
                        # Retry ThreadTracking creation with recovered company
                        application_obj, created = ThreadTracking.objects.get_or_create(
                            thread_id=metadata["thread_id"],
                            defaults={
                                "company": company_obj,
                                "company_source": company_source,
                                "job_title": parsed_subject.get("job_title", ""),
                                "job_id": parsed_subject.get("job_id", ""),
                                "status": status,
                                "sent_date": metadata["timestamp"].date(),
                                "rejection_date": rejection_date_final,
                                "interview_date": interview_date_final,
                                "ml_label": ml_label,
                                "ml_confidence": (float(result.get("confidence", 0.0)) if result else 0.0),
                                "reviewed": reviewed,
                            },
                        )
                        if created and DEBUG:
                            print(f"✓ Created ThreadTracking via fallback for {company_obj.name}")
                    else:
                        if DEBUG:
                            print("⚠️  Message exists but also has no company - cannot create ThreadTracking")
                except Message.DoesNotExist:
                    if DEBUG:
                        print("⚠️  Fallback failed: Message not found")
            
            if DEBUG:
                print("Stats: skipped++ (missing company/message)")
            IngestionStats.objects.filter(date=stats.date).update(total_skipped=F("total_skipped") + 1)
            if hasattr(stats, "total_skipped"):
                stats.total_skipped += 1

    except Exception as e:
        if DEBUG:
            print(f"❌ Failed to create ThreadTracking: {e}")
            import traceback
            traceback.print_exc()
        IngestionStats.objects.filter(date=stats.date).update(total_skipped=F("total_skipped") + 1)
        if hasattr(stats, "total_skipped"):
            stats.total_skipped += 1

    # Refresh stats before printing
    if DEBUG:
        if hasattr(stats, "refresh_from_db"):
            stats.refresh_from_db()
        print(
            f"Stats updated: inserted={stats.total_inserted}, ignored={stats.total_ignored}, skipped={stats.total_skipped}"
        )

    # Final record assembly for applications table
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
        if DEBUG:
            print(f"Logged unresolved company for manual review: {msg_id}")

    if not record["company"] and not record["job_title"] and not record["job_id"]:
        reason = "unclassified"
        if not metadata["body"]:
            reason = "missing_body"
        elif metadata["body"] and not record["company"]:
            reason = "missing_company"
        if DEBUG:
            print(f"Ignored due to: {reason} -> {metadata['subject']}")
            print("Stats: ignored++ (unclassified)")
        log_ignored_message(msg_id, metadata, reason=reason)
        IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
        if hasattr(stats, "total_ignored"):
            stats.total_ignored += 1
        return "ignored"

    record["company_job_index"] = build_company_job_index(
        record.get("company", ""), record.get("job_title", ""), record.get("job_id", "")
    )

    if DEBUG:
        print(f"company: {record['company']}")
        print(f"job_title: {record['job_title']}")
        print(f"job_id: {record['job_id']}")
        print(f"company_source: {record['company_source']}")
        print(f"company_job_index: {record['company_job_index']}")

    if should_ignore(metadata["subject"], metadata["body"]):
        if DEBUG:
            print(f"Ignored by pattern: {metadata['subject']}")
            print("Stats: ignored++ (pattern ignore)")
        log_ignored_message(msg_id, metadata, reason="pattern_ignore")
        IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
        if hasattr(stats, "total_ignored"):
            stats.total_ignored += 1
        return "ignored"

    insert_or_update_application(record)

    if DEBUG:
        print(f"Logged: {metadata['subject']}")

    return "inserted"


# Note: Company data loading moved to DomainMapper class
# Access via _domain_mapper attributes for backward compatibility
ATS_DOMAINS = _domain_mapper.ats_domains
HEADHUNTER_DOMAINS = _domain_mapper.headhunter_domains
JOB_BOARD_DOMAINS = _domain_mapper.job_board_domains
KNOWN_COMPANIES = _domain_mapper.known_companies
KNOWN_COMPANIES_CASED = _domain_mapper.known_companies_cased
DOMAIN_TO_COMPANY = _domain_mapper.domain_to_company
ALIASES = _domain_mapper.aliases
company_data = _domain_mapper.company_data


# Note: Domain map reloading moved to DomainMapper class


def _reload_domain_map_if_needed():
    """Reload all company data if companies.json has changed (delegates to DomainMapper)."""
    global DOMAIN_TO_COMPANY, ATS_DOMAINS, HEADHUNTER_DOMAINS, JOB_BOARD_DOMAINS
    global KNOWN_COMPANIES, KNOWN_COMPANIES_CASED, ALIASES, company_data
    
    _domain_mapper.reload_if_needed()
    
    # Update global references for backward compatibility
    DOMAIN_TO_COMPANY = _domain_mapper.domain_to_company
    ATS_DOMAINS = _domain_mapper.ats_domains
    HEADHUNTER_DOMAINS = _domain_mapper.headhunter_domains
    JOB_BOARD_DOMAINS = _domain_mapper.job_board_domains
    KNOWN_COMPANIES = _domain_mapper.known_companies
    KNOWN_COMPANIES_CASED = _domain_mapper.known_companies_cased
    ALIASES = _domain_mapper.aliases
    company_data = _domain_mapper.company_data


def ingest_message_from_eml(eml_content: str, fake_msg_id: str = None):
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
                part.decode(encoding or 'utf-8') if isinstance(part, bytes) else part
                for part, encoding in decoded_parts
            )
        
        # Parse date
        try:
            date_obj = parsedate_to_datetime(date_raw)
            if timezone.is_naive(date_obj):
                date_obj = timezone.make_aware(date_obj)
        except Exception:
            date_obj = timezone.now()
        
        # Extract sender domain
        parsed = parseaddr(sender)
        email_addr = parsed[1] if len(parsed) == 2 else ""
        match = re.search(r"@([A-Za-z0-9.-]+)$", email_addr)
        sender_domain = match.group(1).lower() if match else ""
        
        # Generate message ID if not provided
        if not fake_msg_id:
            hash_input = f"{subject}{date_obj.isoformat()}{sender}".encode('utf-8')
            fake_msg_id = f"eml_{hashlib.md5(hash_input).hexdigest()}"
        
        # Extract body
        body = ""
        body_html = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                # Skip attachments
                if "attachment" in content_disposition:
                    continue
                
                try:
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        continue
                    
                    charset = part.get_content_charset() or 'utf-8'
                    decoded = payload.decode(charset, errors='ignore')
                    
                    if content_type == "text/plain" and not body:
                        body = decoded.strip()
                    elif content_type == "text/html":
                        body_html = html.unescape(decoded)
                        # Extract text from HTML
                        soup = BeautifulSoup(body_html, "html.parser")
                        body = soup.get_text(separator=" ", strip=True)
                except Exception as e:
                    if DEBUG:
                        print(f"[EML] Error decoding part: {e}")
                    continue
        else:
            # Not multipart
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors='ignore').strip()
            except Exception as e:
                if DEBUG:
                    print(f"[EML] Error decoding body: {e}")
        
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
                "is_noreply": "noreply" in sender.lower() or "no-reply" in sender.lower(),
            }
        }
        
        if DEBUG:
            print(f"[EML] Parsed message:")
            print(f"  Subject: {subject}")
            print(f"  From: {sender}")
            print(f"  Date: {date_obj}")
            print(f"  Sender domain: {sender_domain}")
            print(f"  Body length: {len(body)} chars")
        
    except Exception as e:
        if DEBUG:
            print(f"[EML] Failed to parse .eml content: {e}")
        return None
    
    # Now follow the same pipeline as ingest_message
    body = metadata["body"]  # RFC 5322 compliant body (for storage)
    classification_text = metadata.get("classification_text", body)  # For classification
    
    # Skip blank bodies
    if not body or not body.strip():
        if DEBUG:
            print(f"[EML BLANK BODY] Skipping message: {metadata.get('subject','(no subject)')}")
        log_ignored_message(fake_msg_id, metadata, reason="blank_body")
        IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
        return "ignored"
    
    # Check if application-related (use classification_text for pattern matching)
    header_hints = metadata.get("header_hints", {})
    is_app_related = is_application_related(
        metadata["subject"], 
        classification_text[:500]
    )
    
    if DEBUG:
        print(f"[EML HEADER HINTS] is_application_related={is_app_related}, is_newsletter={header_hints.get('is_newsletter')}, is_bulk={header_hints.get('is_bulk')}, is_noreply={header_hints.get('is_noreply')}")
    
    # Auto-ignore newsletters and bulk mail ONLY if NOT application-related
    if not is_app_related:
        if header_hints.get("is_newsletter") or (header_hints.get("is_bulk") and header_hints.get("is_noreply")):
            if DEBUG:
                print(f"[EML HEADER HINTS] Auto-ignoring newsletter/bulk mail: {metadata['subject']}")
            log_ignored_message(fake_msg_id, metadata, reason="newsletter_headers")
            IngestionStats.objects.filter(date=stats.date).update(total_ignored=F("total_ignored") + 1)
            return "ignored"
    
    # Continue with classification and company resolution
    # (Using the same logic as ingest_message but without Gmail service dependency)
    
    # Run ML classification first (use classification_text for ML/pattern matching)
    result = predict_with_fallback(
        predict_subject_type,
        metadata["subject"],
        classification_text,
        sender=metadata["sender"]
    )
    ml_label = result.get("label", "noise")
    ml_confidence = result.get("confidence", 0.0)
    
    # Parse company from subject/body (use classification_text for pattern matching)
    parse_result = parse_subject(
        metadata["subject"],
        classification_text,
        metadata["sender"],
        metadata["sender_domain"]
    )
    
    # Extract company name from parse result
    company = None
    if isinstance(parse_result, dict):
        company = parse_result.get("company") or parse_result.get("predicted_company")
    elif isinstance(parse_result, str):
        company = parse_result
    
    # If parse_subject detected internal introduction and overrode label to 'other', apply to result
    if isinstance(parse_result, dict) and parse_result.get("label") == "other" and ml_label in ("referral", "interview_invite"):
        sender_domain = metadata.get("sender_domain")
        if sender_domain and company:
            mapped_domain_company = _map_company_by_domain(sender_domain)
            if mapped_domain_company and mapped_domain_company.lower() == company.lower():
                ml_label = "other"
                if DEBUG:
                    print(f"[EML INTERNAL INTRODUCTION] Overriding ml_label to 'other' for internal introduction: {sender_domain} matches {company}")
    
    # If ML originally predicted head_hunter but sender domain maps to actual company (internal recruiter),
    # override to 'other' only for generic spam, preserve meaningful labels
    original_ml_label = result.get("ml_label") or result.get("label")  # Check original ML prediction
    if original_ml_label == "head_hunter":
        sender_domain = metadata.get("sender_domain")
        if sender_domain and sender_domain not in HEADHUNTER_DOMAINS:
            mapped_company = _map_company_by_domain(sender_domain)
            if mapped_company:
                # Preserve meaningful application lifecycle labels
                if ml_label not in ("interview_invite", "rejection", "job_application", "offer"):
                    ml_label = "other"
                    if DEBUG:
                        print(f"[EML INTERNAL RECRUITER] Overriding to 'other' for internal recruiter from company domain: {sender_domain} → {mapped_company}")
                elif DEBUG:
                    print(f"[EML INTERNAL RECRUITER] Preserving meaningful label '{ml_label}' from internal recruiter: {sender_domain} → {mapped_company}")
    
    # Check if sender domain is in personal domains list - override to noise
    sender_domain = metadata.get("sender_domain", "").lower()
    if sender_domain and sender_domain in PERSONAL_DOMAINS:
        if DEBUG:
            print(f"[EML PERSONAL DOMAIN] Detected personal domain: {sender_domain}, overriding to 'noise'")
        ml_label = "noise"
    
    if DEBUG:
        print(f"[EML] Parsed company: {company}")
        print(f"[EML] ML label: {ml_label}, confidence: {ml_confidence}")
    
    # Get or create company object
    company_obj = None
    if company and company.strip():
        company_obj, created = Company.objects.get_or_create(
            name=company,
            defaults={
                "first_contact": date_obj,
                "last_contact": date_obj,
            }
        )
    
    # Check for duplicates
    existing = Message.objects.filter(msg_id=fake_msg_id).first()
    if existing:
        if DEBUG:
            print(f"[EML] Message already exists (msg_id={fake_msg_id}), updating...")
        # Update existing message
        existing.subject = metadata["subject"]
        existing.sender = metadata["sender"]
        existing.timestamp = metadata["date"]
        existing.company = company_obj
        existing.ml_label = ml_label
        existing.confidence = ml_confidence
        existing.save()
        return "skipped"
    
    # Create new message
    try:
        # Compute body hash for deduplication
        normalized_body = re.sub(r'\s+', ' ', body or "").strip()
        body_hash = hashlib.sha256(normalized_body.encode('utf-8')).hexdigest()
        
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
            reviewed=False
        )
        
        # Store body text in separate search table
        insert_email_text(fake_msg_id, metadata["subject"], body)
        
        # Update stats
        IngestionStats.objects.filter(date=stats.date).update(total_inserted=F("total_inserted") + 1)
        
        if DEBUG:
            print(f"[EML] Successfully ingested message (ID={msg_obj.id})")
        
        return "inserted"
        
    except Exception as e:
        if DEBUG:
            print(f"[EML] Failed to create message: {e}")
        return None


# Phase 4: Also available as extract_confidence in tracker/utils/helpers.py
def _conf(res) -> float:
    if not res:
        return 0.0
    try:
        return float(res.get("confidence", res.get("proba", 0.0)))
    except Exception:
        return 0.0


# --- Helpers for domain handling ---
def _is_ats_domain(domain: str) -> bool:
    """Return True if domain equals or is a subdomain of any ATS root domain (delegates to DomainMapper)."""
    return _domain_mapper.is_ats_domain(domain)


def _map_company_by_domain(domain: str) -> str | None:
    """Resolve company by exact or subdomain match (delegates to DomainMapper).

    Example: if mapping contains 'nsa.gov' -> 'National Security Agency', then
    'uwe.nsa.gov' will also map to that company.
    """
    return _domain_mapper.map_company_by_domain(domain)
