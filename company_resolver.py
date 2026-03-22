"""Company name extraction and validation classes.

Extracted from parser.py for maintainability. Contains:
- CompanyValidator: Company name validation, normalization, person-name detection
- CompanyResolver: Multi-strategy company name extraction from email metadata

These classes are used by parser.py's parse_subject() function and are instantiated
at module level as _company_validator and _company_resolver.
"""

import re
import logging
from email.utils import parseaddr

from bs4 import BeautifulSoup

logger = logging.getLogger("parser")


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
        # Load corp_markers from patterns.json (with fallback defaults)
        self.corp_markers = set(
            m.lower() for m in patterns.get("corp_markers", [
                "inc", "llc", "ltd", "co", "corp", "corporation", "company",
                "technologies", "systems", "group",
            ])
        )
        # Load company name normalizations from patterns.json
        self.company_name_normalizations = {
            k.lower(): v for k, v in patterns.get("company_name_normalizations", {
                "indeed application": "Indeed",
            }).items()
        }

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
        - Map known pseudo-companies from company_name_normalizations config

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

        # Check configurable normalizations
        lower = n.lower()
        if lower in self.company_name_normalizations:
            return self.company_name_normalizations[lower]

        return n

    def looks_like_person(self, name: str) -> bool:
        """Heuristic: return True if the string looks like an individual person's name.

        Criteria (intentionally conservative so we *reject* obvious person names):
        - 1-3 tokens, each starting with capital then lowercase letters only
        - No token contains digits, '&', '@', '.', or corporate suffix markers
        - Contains no common company suffix words from corp_markers config
        - If exactly two tokens and both are common first/last name shapes (<=12 chars)
          treat as person

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
        # Use configurable corp_markers from patterns.json
        if any(t.lower().strip(".,") in self.corp_markers for t in tokens):
            return False
        # Reject if any token has non alpha (besides hyphen) or is ALLCAPS acronym
        for t in tokens:
            if not re.match(r"^[A-Z][a-z]+(?:-[A-Z][a-z]+)?$", t):
                return False
        # Two-token typical person pattern
        if len(tokens) == 2 and all(len(t) <= 12 for t in tokens):
            return True
        # Single short token like "Kelly" should not be considered a company
        # unless in known companies
        if len(tokens) == 1 and len(tokens[0]) <= 10:
            return True
        return False


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

    def _configured_company_names(self):
        """Return canonical company names gathered from companies.json sources."""
        names = []

        for company in self.company_data.get("known", []):
            if company and company not in names:
                names.append(company)

        for company in self.company_data.get("domain_to_company", {}).values():
            if company and company not in names:
                names.append(company)

        for company in self.company_data.get("JobSites", {}).keys():
            if company and company not in names:
                names.append(company)

        for company in self.company_data.get("aliases", {}).values():
            if company and company not in names:
                names.append(company)

        return names

    @staticmethod
    def _compact_company_key(value: str) -> str:
        """Normalize company-like text for compact equality checks."""
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    def extract_from_ats_sender(self, sender: str, sender_domain):
        """Extract company from ATS sender display name or email prefix.

        Checks (in order):
        1. Display name "Person @ Company" pattern
        2. Display name against known companies list
        3. Display name against aliases
        4. Email prefix (before @) against aliases
        5. Email prefix against known companies

        Args:
            sender: Full sender email (with optional display name)
            sender_domain: Sender's email domain

        Returns:
            Company name if found, None otherwise
        """
        if not sender or not sender_domain:
            return None

        # Check if this is an ATS domain (with subdomain support)
        is_ats = False
        domain_lower = sender_domain.lower()
        is_ats = self.domain_mapper.is_ats_domain(domain_lower)
        if is_ats:
            logger.debug(f"[DEBUG] ATS domain detected: {domain_lower}")

        if not is_ats:
            return None

        display_name, sender_email = parseaddr(sender)

        # --- Try display name first (most human-readable) ---
        if display_name:
            display_name_clean = display_name.strip()

            # Handle "PersonName @ CompanyName" pattern (e.g., "Quinn @ Mondo")
            if " @ " in display_name_clean or " at " in display_name_clean.lower():
                if " @ " in display_name_clean:
                    parts = display_name_clean.split(" @ ", 1)
                else:
                    parts = re.split(
                        r"\s+at\s+", display_name_clean, maxsplit=1, flags=re.IGNORECASE
                    )
                if len(parts) == 2:
                    person_part = parts[0].strip()
                    company_part = parts[1].strip()
                    if (
                        self.company_validator.looks_like_person(person_part)
                        and company_part
                    ):
                        display_name_clean = company_part
                        logger.debug(
                            f"[DEBUG] Extracted company from 'Name @ Company' pattern: "
                            f"{display_name_clean}"
                        )

            # Check if display name is a known company
            if display_name_clean.lower() in {c.lower() for c in self.known_companies}:
                # Find original casing from known list
                for orig in self.company_data.get("known", []):
                    if orig.lower() == display_name_clean.lower():
                        logger.debug(f"[DEBUG] ATS display name is known company: {orig}")
                        return orig
                return display_name_clean

            # Check if display name matches an alias
            aliases_lower = {
                k.lower(): v
                for k, v in self.company_data.get("aliases", {}).items()
            }
            if display_name_clean.lower() in aliases_lower:
                canonical = aliases_lower[display_name_clean.lower()]
                logger.debug(
                    f"[DEBUG] ATS display name alias match: "
                    f"{display_name_clean} -> {canonical}"
                )
                return canonical

        # --- Try email prefix (e.g., ngc@myworkday.com -> "ngc") ---
        if sender_email and "@" in sender_email:
            sender_prefix = sender_email.split("@", maxsplit=1)[0].strip().lower()
            # Handle + in email addresses (e.g., peraton+autoreply -> peraton)
            if "+" in sender_prefix:
                sender_prefix = sender_prefix.split("+", maxsplit=1)[0]

            # Check if prefix matches an alias
            aliases_lower = {
                k.lower(): v
                for k, v in self.company_data.get("aliases", {}).items()
            }
            if sender_prefix in aliases_lower:
                logger.debug(
                    f"[DEBUG] ATS alias match: {sender_prefix} -> "
                    f"{aliases_lower[sender_prefix]}"
                )
                return aliases_lower[sender_prefix]

            # Check if prefix is a known company
            if sender_prefix in {c.lower() for c in self.known_companies}:
                for orig in self.company_data.get("known", []):
                    if orig.lower() == sender_prefix:
                        logger.debug(f"[DEBUG] ATS prefix is known company: {orig}")
                        return orig

            configured_by_key = {
                self._compact_company_key(company): company
                for company in self._configured_company_names()
            }
            sender_prefix_key = self._compact_company_key(sender_prefix)
            if sender_prefix_key in configured_by_key:
                company = configured_by_key[sender_prefix_key]
                logger.debug(f"[DEBUG] ATS prefix matched configured company: {company}")
                return company

            if (
                sender_prefix_key
                and sender_prefix.isalpha()
                and 3 <= len(sender_prefix) <= 20
                and sender_prefix not in {
                    "noreply",
                    "donotreply",
                    "recruiting",
                    "recruiter",
                    "careers",
                    "jobs",
                    "workday",
                }
            ):
                company = sender_prefix.upper() if sender_prefix.isupper() else sender_prefix.title()
                logger.debug(f"[DEBUG] ATS prefix fallback company: {company}")
                return company

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

        if not re.search(r"\bapplication\b", subject, re.IGNORECASE):
            return None

        domain_lower = (sender_domain or "").lower()
        sender_email_lower = (sender_email or "").lower()

        # Check if this is a job board domain or matches job board sender patterns
        job_board_sender_match = any(
            pattern in sender_email_lower
            for pattern in self.domain_mapper.job_board_sender_patterns
        )
        is_job_board = (
            domain_lower in self.job_board_domains
            or job_board_sender_match
            or "application" in subject.lower()
        )

        if not is_job_board:
            return None

        logger.debug("[DEBUG] Job board confirmation detected, attempting body extraction")
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

        if (
            extracted
            and len(extracted) > 2
            and self.company_validator.is_valid_company_name(extracted)
        ):
            logger.debug(f"[DEBUG] Job board employer extraction SUCCESS: {extracted}")
            return extracted

        return None

    def extract_from_ats_display_name(self, sender: str, check_known: bool = False):
        """Extract company from ATS display name with validation.

        Handles "Person @ Company" pattern and strips ATS noise words/suffixes.

        Args:
            sender: Full sender string with display name
            check_known: If True, only return if company is known or looks like a company

        Returns:
            Company name if valid, None otherwise
        """
        if not sender:
            return None

        display_name, _ = parseaddr(sender)
        cleaned = display_name

        # Handle "PersonName @ CompanyName" pattern (e.g., "Quinn @ Mondo")
        if " @ " in cleaned or re.search(r"\s+at\s+", cleaned, re.IGNORECASE):
            if " @ " in cleaned:
                parts = cleaned.split(" @ ", 1)
            else:
                parts = re.split(
                    r"\s+at\s+", cleaned, maxsplit=1, flags=re.IGNORECASE
                )
            if len(parts) == 2:
                person_part = parts[0].strip()
                company_part = parts[1].strip()
                if (
                    self.company_validator.looks_like_person(person_part)
                    and company_part
                ):
                    cleaned = company_part
                    logger.debug(
                        f"[DEBUG] Extracted company from 'Name @ Company' pattern: "
                        f"{cleaned}"
                    )

        # Clean up ATS-specific noise words (from companies.json config)
        noise_words = self.domain_mapper.display_name_noise_words
        noise_pattern = (
            r"\b(" + "|".join(re.escape(w) for w in noise_words) + r")\b"
        )
        cleaned = re.sub(noise_pattern, "", cleaned, flags=re.I).strip()

        # Remove ATS platform suffixes (from companies.json config)
        suffixes = self.domain_mapper.ats_platform_suffixes
        suffix_pattern = (
            r"\s*@\s*(" + "|".join(re.escape(s) for s in suffixes) + r")\s*$"
        )
        cleaned = re.sub(suffix_pattern, "", cleaned, flags=re.I).strip()

        # Clean up multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

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
                len(words) >= 3
                or any(
                    w in cleaned
                    for w in [
                        "Corporation",
                        "Inc",
                        "LLC",
                        "Ltd",
                        "Group",
                        "Technologies",
                        "Systems",
                    ]
                )
                or any(len(w) > 12 for w in words)
            )

            if is_likely_company:
                return cleaned

            return None

        return cleaned

    def extract_from_ats_body_patterns(
        self, body: str, subject: str, sender_domain
    ):
        """Extract company from application confirmation text in email body.

        Looks for patterns like:
        - "position here at COMPANY"
        - "application for our POSITION at COMPANY"
        - "interest in COMPANY"
        - "considering us at COMPANY"
        Also handles IntelligenceCareers.gov special case.

        Args:
            body: Email body text (may be HTML)
            subject: Email subject line
            sender_domain: Sender's email domain

        Returns:
            Company name if found, None otherwise
        """
        if not body:
            return None

        domain_lower = (sender_domain or "").lower()

        # Only trigger for subjects with application keywords OR ATS domains
        subject_has_app_keywords = (
            "application" in subject.lower()
            or "applying" in subject.lower()
            or "applied" in subject.lower()
        )
        is_ats = self.domain_mapper.is_ats_domain(domain_lower) if domain_lower else False

        if not (subject_has_app_keywords or is_ats):
            return None

        logger.debug("[DEBUG] Entering ATS body pattern extraction")
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

        logger.debug(
            f"[DEBUG] Body plain length: {len(body_plain)}, "
            f"first 200 chars: {body_plain[:200]}"
        )

        ats_body_patterns = [
            r"thanks?\s+for\s+applying\s+to\s+([A-Z][A-Za-z0-9\s&.,'-]+?)(?:!|\.|,|[\r\n])",
            r"position\s+(?:here\s+)?at\s+([A-Z][A-Za-z0-9\s&.,'-]+?)"
            r"(?:\.|,|[\r\n]|\s+Thank|\s+you\b)",
            r"position\s+(?:here\s+)?(?:at|with)\s+"
            r"([A-Z][A-Za-z0-9\s&.,'-]{2,30})(?:\.|,|[\r\n])",
            r"application\s+for\s+(?:our|the)\s+.{5,50}?\s+at\s+"
            r"([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\.|[\r\n])",
            r"considering\s+us\s+at\s+"
            r"([A-Z][A-Za-z0-9\s&.,'-]+?)\s+as",
            r"considering\s+([A-Z][A-Za-z0-9\s&.,'-]+?)\s+as\s+"
            r"(?:a\s+)?(?:potential|future)\s+employer",
            r"(?:your\s+)?interest\s+in\s+(?:the\s+)?"
            r"([A-Z][A-Za-z0-9\s&.,'-]{2,60}?)"
            r"(?:\s+(?:and\s+(?:apply|applying|applied)"
            r"|to\s+(?:the\s+)?(?:role|position)"
            r"|for\s+(?:the\s+)?(?:role|position)"
            r"|for\s+this\s+job)|\.|!|[\r\n])",
        ]

        for pattern in ats_body_patterns:
            ats_match = re.search(pattern, body_plain, re.IGNORECASE)
            if ats_match:
                extracted = ats_match.group(1).strip()
                # Trim common trailing clauses accidentally captured
                extracted = re.split(
                    r"\s+(?:and\s+(?:apply|applying|applied)"
                    r"|to\s+(?:the\s+)?(?:role|position)"
                    r"|for\s+(?:the\s+)?(?:role|position)"
                    r"|for\s+this\s+job)\b",
                    extracted,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0].strip()
                extracted = re.split(
                    r",\s*you\b|\s+you\s+(?:still|may|will)\b",
                    extracted,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0].strip()
                # Clean up trailing words and punctuation
                extracted = re.sub(
                    r"\s+(and|the|a|as|at|for|with|in)$",
                    "",
                    extracted,
                    flags=re.IGNORECASE,
                ).strip()
                extracted = extracted.rstrip(".,;:")
                if (
                    extracted
                    and len(extracted) > 1
                    and self.company_validator.is_valid_company_name(extracted)
                ):
                    company = self.company_validator.normalize_company_name(extracted)
                    logger.debug(
                        f"[DEBUG] ATS body pattern extraction SUCCESS: {company}"
                    )
                    return company
                else:
                    logger.debug(
                        f"[DEBUG] ATS body pattern matched but failed validation: "
                        f"'{extracted}'"
                    )

        # Special case: IntelligenceCareers.gov (NSA ATS)
        if domain_lower == "intelligencecareers.gov" and body:
            intcareers_pattern = re.search(
                r"application to (?:the\s+)?"
                r"([A-Z][A-Za-z0-9\s&.,'-]+?)(?:\s+\(|\!|\.|$)",
                body_plain,
                re.IGNORECASE,
            )
            if intcareers_pattern:
                extracted = intcareers_pattern.group(1).strip()
                extracted = re.sub(r"\s+\(.*?\)\s*$", "", extracted).strip()
                if extracted and self.company_validator.is_valid_company_name(extracted):
                    company = self.company_validator.normalize_company_name(extracted)
                    logger.debug(
                        f"[DEBUG] IntelligenceCareers.gov agency extraction: {company}"
                    )
                    return company

        return None

    def extract_from_subject_patterns(self, subject: str):
        """Extract company and job title from subject using regex patterns.

        Args:
            subject: Cleaned email subject line (reply/forward prefixes removed)

        Returns:
            Tuple of (company, job_title) - either may be None
        """
        company = None
        job_title = None

        trailing_company_match = re.search(
            r"-\s*([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,3})\s*$",
            subject,
        )
        if trailing_company_match:
            trailing_candidate = self.company_validator.normalize_company_name(
                trailing_company_match.group(1).strip()
            )
            if (
                self.company_validator.is_valid_company_name(trailing_candidate)
                and not self.company_validator.looks_like_person(trailing_candidate)
            ):
                return trailing_candidate, job_title

        update_company_match = re.match(
            r"^([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,3})\s+career opportunity update\b",
            subject,
            re.IGNORECASE,
        )
        if update_company_match:
            update_candidate = self.company_validator.normalize_company_name(
                update_company_match.group(1).strip()
            )
            if (
                self.company_validator.is_valid_company_name(update_candidate)
                and not self.company_validator.looks_like_person(update_candidate)
            ):
                return update_candidate, job_title

        # Special case: "applying for Field CTO position @ Claroty"
        special_match = re.search(
            r"applying for ([\w\s\-]+) position @ ([A-Z][\w\s&\-]+)", subject
        )
        if special_match:
            job_title = special_match.group(1).strip()
            company = special_match.group(2).strip()
            return company, job_title

        # General patterns for company extraction
        patterns = [
            (
                r"^([A-Z][a-zA-Z]+(?:\s+(?:[A-Z][a-zA-Z]+|&[A-Z]?))*?)(?:\s+application|\s+-)",
                re.IGNORECASE,
            ),
            (
                r"application (?:to|for|with)\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b",
                re.IGNORECASE,
            ),
            (r"(?:from|with|at)\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
            (r"position\s+@\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
            (
                r"^([A-Z][\w&-]+(?:\s+[\w&-]+){0,2}?)\s+(?:Job|Application|Interview)\b",
                re.IGNORECASE,
            ),
            (r"-\s*([A-Z][\w&-]+(?:\s+[\w&-]+){0,2}?)\s*-\s*", 0),
            (r"-\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})$", 0),
            (
                r"(?:your application with|application with|interest in|position (?:here )?at)\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b",
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
            (
                r"thank you for applying to\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b",
                re.IGNORECASE,
            ),
            (
                r"applying to\s+([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b",
                re.IGNORECASE,
            ),
            (r"@\s*([A-Z][\w&-]+(?:\s+[\w&-]+){0,2})\b", re.IGNORECASE),
        ]

        for pattern, flags in patterns:
            match = re.search(pattern, subject, flags)
            if match:
                candidate = self.company_validator.normalize_company_name(
                    match.group(1).strip()
                )

                if not self.company_validator.is_valid_company_name(candidate):
                    logger.debug(
                        f"[DEBUG] Rejected invalid candidate company from subject: {candidate}"
                    )
                    continue

                # Person-name safeguard
                if self.company_validator.looks_like_person(candidate):
                    if candidate.lower() not in {
                        c.lower() for c in self.known_companies
                    }:
                        logger.debug(f"[DEBUG] Rejected candidate company as person name: {candidate}")
                        continue

                company = candidate
                break

        return company, job_title

    def canonicalize_company_name(self, company: str, subject: str) -> str:
        """Map company candidate to canonical known name or alias.

        If no alias/known match found, attempts to extract a cleaner company
        name from patterns like "... position at CSA" within the candidate.

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

        # Check aliases first (word boundary matching)
        aliases_lower = {
            k.lower(): v for k, v in self.company_data.get("aliases", {}).items()
        }
        for alias_lower, canonical in aliases_lower.items():
            alias_pattern = r"\b" + re.escape(alias_lower) + r"\b"
            if re.search(alias_pattern, cand_lower) or re.search(
                alias_pattern, subj_lower
            ):
                logger.debug(f"[DEBUG] Company alias matched: {alias_lower} -> {canonical}")
                return canonical

        # Check known companies list for substrings
        configured_companies = sorted(
            self._configured_company_names(), key=len, reverse=True
        )
        for configured in configured_companies:
            configured_lower = configured.lower()
            if configured_lower in cand_lower or configured_lower in subj_lower:
                logger.debug(f"[DEBUG] Configured company matched: {configured}")
                return configured

        # Fallback: extract text after "at" / "@" if candidate looks over-captured
        # e.g. "the Senior Systems Security Engineer position at CSA" -> "CSA"
        m_at = re.search(r"position at\s+(.+)$", company, re.IGNORECASE)
        if not m_at:
            parts = re.split(r"\bat\b|@", company, flags=re.IGNORECASE)
            candidate_after_at = parts[-1].strip() if len(parts) > 1 else ""
        else:
            candidate_after_at = m_at.group(1).strip()

        if candidate_after_at:
            # Remove leading articles like 'the'
            candidate_after_at = re.sub(
                r"^the\s+", "", candidate_after_at, flags=re.IGNORECASE
            ).strip()
            # Shorten long captures to first 4 words
            candidate_short = " ".join(candidate_after_at.split()[:4])
            if candidate_short and not self.company_validator.looks_like_person(
                candidate_short
            ):
                logger.debug(
                    f"[DEBUG] Extracted company after 'at': {candidate_short}"
                )
                return candidate_short

        return company

    def display_name_last_resort(self, sender: str):
        """Last-resort display name fallback (PRIORITY 7).

        Only used after subject patterns find nothing. Applies looser
        person-name check: 2-word short names are rejected, others accepted.

        Args:
            sender: Full sender string with display name

        Returns:
            Company name if valid, None otherwise
        """
        candidate = self.extract_from_ats_display_name(sender, check_known=False)
        if not candidate:
            return None

        words = candidate.split()
        is_likely_person = len(words) == 2 and all(len(w) < 12 for w in words)

        if not is_likely_person or candidate.lower() in {
            c.lower() for c in self.known_companies
        }:
            logger.debug(f"[DEBUG] ATS display name fallback applied: {candidate}")
            return candidate

        logger.debug(
            f"[DEBUG] ATS display name rejected (likely person name): {candidate}"
        )
        return None
