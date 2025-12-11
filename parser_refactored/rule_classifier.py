"""Rule-based classification for email messages.

This module contains the RuleClassifier class which implements pattern-based
classification logic for job search emails using regex patterns from patterns.json.
"""

import re
from typing import Optional


DEBUG = False  # Set to True for verbose classification debugging


class RuleClassifier:
    """Classifies email messages using rule-based regex patterns.
    
    This class encapsulates the rule_label function logic, which checks message
    text against compiled regex patterns in a prioritized order to classify
    job search emails (applications, rejections, interviews, etc.).
    """

    def __init__(self, patterns: dict):
        """Initialize RuleClassifier with patterns from patterns.json.
        
        Args:
            patterns: Dictionary containing message_label_patterns and 
                     message_label_excludes from patterns.json
        """
        self.patterns = patterns
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns from patterns.json for efficient matching."""
        self._msg_label_patterns = {}
        
        # Compile positive patterns for each label
        for code_label in (
            "interview_invite",
            "job_application",
            "rejection",
            "offer",
            "noise",
            "head_hunter",
            "ignore",
            "response",
            "follow_up",
            "ghosted",
            "referral",
            "other",
            "blank",
        ):
            compiled = []
            pattern_list = self.patterns.get("message_label_patterns", {}).get(code_label, [])
            for p in pattern_list:
                if p != "None":
                    try:
                        compiled.append(re.compile(p, re.I))
                    except re.error as e:
                        print(f"⚠️  Invalid regex pattern for {code_label}: {p} - {e}")
            self._msg_label_patterns[code_label] = compiled

        # Compile negative patterns (excludes) for each label
        self._msg_label_excludes = {
            k: [re.compile(p, re.I) for p in self.patterns.get("message_label_excludes", {}).get(k, [])]
            for k in (
                "interview_invite",
                "job_application",
                "rejection",
                "offer",
                "noise",
                "head_hunter",
                "ignore",
                "response",
                "follow_up",
                "ghosted",
                "referral",
            )
        }

    def classify(
        self,
        subject: str,
        body: str = "",
        sender_domain: Optional[str] = None,
        headhunter_domains: set = None,
        job_board_domains: set = None,
        is_ats_domain_fn=None,
        map_company_by_domain_fn=None,
    ) -> Optional[str]:
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
        if subject and ("Indeed Application:" in subject or re.search(r"^\s*Indeed\s+Application:\s*", subject, re.I)):
            if DEBUG:
                print("[DEBUG rule_label] Forcing job_application for Indeed Application subject")
            return "job_application"

        # Special-case: Assessment completion notifications -> "other"
        subject_text = subject or ""
        if re.search(r"\bassessments?\s+complete\b", subject_text, re.I):
            if DEBUG:
                print("[DEBUG rule_label] Forcing 'other' for assessment completion notification")
            return "other"
        if re.search(r"\bassessment\s+(?:completion\s+)?status\b", subject_text, re.I):
            if DEBUG:
                print("[DEBUG rule_label] Forcing 'other' for assessment status notification")
            return "other"

        # Special-case: Incomplete application reminders -> "other"
        if re.search(r"\bstarted\s+applying\b.*\bdidn'?t\s+finish\b", s, re.I | re.DOTALL):
            if DEBUG:
                print("[DEBUG rule_label] Forcing 'other' for incomplete application reminder")
            return "other"
        if re.search(r"\bdon'?t\s+forget\s+to\s+finish\b.*\bapplication\b", s, re.I | re.DOTALL):
            if DEBUG:
                print("[DEBUG rule_label] Forcing 'other' for incomplete application reminder")
            return "other"
        if re.search(r"\bpick\s+up\s+where\s+you\s+left\s+off\b", s, re.I):
            if DEBUG:
                print("[DEBUG rule_label] Forcing 'other' for incomplete application reminder")
            return "other"

        # Early scheduling-language detection -> interview_invite
        scheduling_rx_early = re.compile(
            r"(?:please\s+)?(?:let\s+me\s+know\s+when\s+you(?:\s+would|(?:'re|\s+are))?\s+available)|"
            r"available\s+for\s+(?:a\s+)?(?:call|phone\s+call|conversation|interview)|"
            r"would\s+like\s+to\s+discuss\s+(?:the\s+position|this\s+role|the\s+opportunity)|"
            r"schedule\s+(?:a\s+)?(?:call|time|conversation|interview)|"
            r"would\s+you\s+be\s+available",
            re.I | re.DOTALL,
        )
        if scheduling_rx_early.search(s):
            if DEBUG:
                print("[DEBUG rule_label] Early scheduling-language match -> interview_invite")
            return "interview_invite"

        # Check rejection patterns BEFORE application confirmation
        for rx in self._msg_label_patterns.get("rejection", []):
            if rx.search(s):
                if DEBUG:
                    print(f"[DEBUG rule_label] Early rejection match: {rx.pattern[:80]}")
                return "rejection"

        # Early referral detection
        referral_patterns = [
            r"\b(has\s+referred\s+you|referred\s+you\s+for|employee\s+referral|internal\s+referral|someone\s+(?:from|at|in)\s+\w+.*\s+(?:has\s+)?referred\s+you)\b",
            r"\b(referred\s+to\s+you\s+by|referred\s+by|referral\s+from)\b",
        ]
        for pattern in referral_patterns:
            if re.search(pattern, s, re.I | re.DOTALL):
                if DEBUG:
                    print(f"[DEBUG rule_label] Early referral match -> referral")
                return "referral"

        # Explicit application-confirmation signals -> job_application
        if re.search(
            r"\b(we\s+have\s+received\s+your\s+application|we[''\u2019]?ve\s+received\s+your\s+application|we\s+have\s+received\s+your\s+application|thanks?\s+(?:you\s+)?for\s+applying|application\s+received|your\s+application\s+has\s+been\s+received|your\s+application\s+has\s+been\s+submitted|your\s+application\s+was\s+sent)\b",
            s,
            re.I | re.DOTALL,
        ):
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
                    if DEBUG and label in ("rejection", "noise"):
                        print(f"[DEBUG rule_label] Pattern MATCHED for '{label}': {rx.pattern[:80]}")
                        print(f"  Matched text: '{match.group()}'")
                    
                    # Check exclude patterns
                    excludes = self._msg_label_excludes.get(label, [])
                    if DEBUG and label == "noise" and excludes:
                        print(f"[DEBUG rule_label] Checking {len(excludes)} exclusion patterns for noise...")
                    
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
                            contact_patterns = [
                                r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
                                r"\+?\d{1,2}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
                                r"linkedin\.com/(?:in|pub)/[A-Za-z0-9_\-]+",
                            ]
                            signature_rx = re.compile(
                                r"(?:Regards|Best regards|Sincerely|Best|Thanks|Thank you)[\s,]*[\r\n]+[A-Z][a-z]+",
                                re.I
                            )

                            has_contact = any(re.search(p, s, re.I) for p in contact_patterns) or signature_rx.search(s)
                            if not has_contact:
                                continue
                        else:
                            # For referral: require explicit referral language if no domain
                            if not d:
                                if not re.search(r"\b(referred|referral|referred by|referrer)\b", s, re.I):
                                    continue

                    # Special case: job_application with scheduling language -> interview_invite
                    if label == "job_application":
                        scheduling_rx = re.compile(
                            r"(?:please\s+)?(?:let\s+me\s+know\s+when\s+you(?:\s+would|(?:'re|\s+are))?\s+available)|"
                            r"available\s+for\s+(?:a\s+)?(?:call|phone\s+call|conversation|interview)|"
                            r"would\s+like\s+to\s+discuss\s+(?:the\s+position|this\s+role|the\s+opportunity)|"
                            r"schedule\s+(?:a\s+)?(?:call|time|conversation|interview)|"
                            r"would\s+you\s+be\s+available",
                            re.I | re.DOTALL,
                        )
                        if scheduling_rx.search(s):
                            if DEBUG:
                                print("[DEBUG rule_label] Matched scheduling language -> returning interview_invite")
                            return "interview_invite"

                    if DEBUG and label == "rejection":
                        print(f"[DEBUG rule_label] About to return '{label}'")
                    return label

        return None
