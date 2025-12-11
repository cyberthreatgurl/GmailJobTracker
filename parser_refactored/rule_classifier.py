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
