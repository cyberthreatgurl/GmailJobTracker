"""Company resolution and extraction from email messages.

This module contains the CompanyResolver class which handles company name
extraction from email subjects, bodies, and sender information using various
strategies (ATS domains, regex patterns, known companies, etc.).
"""

import re
from typing import Optional, Tuple
from email.utils import parseaddr
from bs4 import BeautifulSoup


DEBUG = False  # Set to True for verbose company resolution debugging


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
        self, sender: str, sender_domain: Optional[str]
    ) -> Optional[str]:
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
        self, body: str, subject: str, sender_email: str, sender_domain: Optional[str]
    ) -> Optional[str]:
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
    ) -> Optional[str]:
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
    ) -> Tuple[Optional[str], Optional[str]]:
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
