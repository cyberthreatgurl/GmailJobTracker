"""Rule-based email classification using regex patterns.

Extracted from parser.py for maintainability. Contains:
- RuleClassifier: Classifies email messages using compiled regex patterns from patterns.json

This class is used by parser.py's rule_label() wrapper function and is instantiated
at module level as _rule_classifier.
"""

import re
import logging

logger = logging.getLogger("parser")


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
            "prescreen": "prescreen",
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
        self._special_indeed_subject = self._compile_pattern_list(
            special_cases.get("indeed_application_subject", [])
        )
        self._special_assessment = self._compile_pattern_list(
            special_cases.get("assessment_complete", [])
        )
        self._special_incomplete_app = self._compile_pattern_list(
            special_cases.get("incomplete_application_reminder", [])
        )

        # Early detection patterns
        early_detection = self.patterns.get("early_detection", {})
        self._early_cancelled = self._compile_pattern_list(
            early_detection.get("cancelled_position", [])
        )
        self._early_scheduling = self._compile_pattern_list(
            early_detection.get("scheduling_language", [])
        )
        self._reply_indicators = self._compile_pattern_list(
            early_detection.get("reply_indicators", [])
        )
        self._early_referral = self._compile_pattern_list(
            early_detection.get("referral_language", [])
        )
        self._early_rejection_override = self._compile_pattern_list(
            early_detection.get("rejection_override", [])
        )
        self._early_status_update = self._compile_pattern_list(
            early_detection.get("status_update", [])
        )
        self._early_application_confirm = self._compile_pattern_list(
            early_detection.get("application_confirmation", [])
        )

        # Validation rules
        validation = self.patterns.get("validation_rules", {})
        self._headhunter_contact_patterns = validation.get(
            "head_hunter_contact_patterns", []
        )
        signature_pattern = validation.get("head_hunter_signature_pattern", "")
        self._headhunter_signature_rx = (
            re.compile(signature_pattern, re.I) if signature_pattern else None
        )
        referral_lang = validation.get("referral_explicit_language", "")
        self._referral_explicit_rx = (
            re.compile(referral_lang, re.I) if referral_lang else None
        )

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
            Labels: interview_invite, prescreen, job_application, rejection, offer, noise,
                   head_hunter, other, referral, ghosted, blank
        """
        s = f"{subject or ''} {body or ''}"

        # Special-case: Indeed application confirmation subjects
        if subject and any(rx.search(subject) for rx in self._special_indeed_subject):
            logger.debug("[DEBUG rule_label] Forcing job_application for Indeed Application subject")
            return "job_application"

        # Special-case: Assessment completion notifications -> "other"
        subject_text = subject or ""
        if any(rx.search(subject_text) for rx in self._special_assessment):
            logger.debug("[DEBUG rule_label] Forcing 'other' for assessment completion notification")
            return "other"

        # Special-case: Incomplete application reminders -> "other"
        if any(rx.search(s) for rx in self._special_incomplete_app):
            logger.debug("[DEBUG rule_label] Forcing 'other' for incomplete application reminder")
            return "other"

        # Check cancelled position FIRST (before rejection)
        # "Decided not to move forward with filling this role" is a position cancellation,
        # NOT a personal rejection. Must be checked before rejection patterns.
        if any(rx.search(s) for rx in self._early_cancelled):
            logger.debug("[DEBUG rule_label] Early cancelled match - position was cancelled")
            return "cancelled"

        # Check rejection patterns FIRST (before application confirmation)
        # This is critical because rejection emails often contain "your application to" or
        # "application status" language that would match the broad application patterns.
        #
        # We check BOTH the full rejection patterns AND the rejection_override signals
        # in a single pass. Either is sufficient to classify as rejection.
        rejection_patterns = self._msg_label_patterns.get("rejection", [])
        if any(rx.search(s) for rx in rejection_patterns) or \
           any(rx.search(s) for rx in self._early_rejection_override):
            logger.debug("[DEBUG rule_label] Rejection detected (patterns or override)")
            return "rejection"

        # Check if this is a reply/follow-up email (RE:, Re:, FW:, Fwd:, etc.)
        is_reply = subject and any(rx.search(subject) for rx in self._reply_indicators)
        
        # Track if prescreen was skipped due to being a reply (to skip in priority loop too)
        skip_prescreen_label = False
        is_prescreen_reply = False  # Track if this is specifically a reply to a prescreen

        # Check prescreen patterns FIRST (before scheduling language)
        # "Phone Screen" or "Prescreen" in subject should be classified as prescreen,
        # not interview_invite, even if the email contains scheduling language
        # BUT only for initial outreach - replies should be classified as 'other'
        for rx in self._msg_label_patterns.get("prescreen", []):
            if rx.search(s):
                if is_reply:
                    logger.debug("[DEBUG rule_label] Prescreen pattern in reply -> treating as follow-up (other)")
                    # Mark to skip prescreen in the priority loop as well
                    skip_prescreen_label = True
                    is_prescreen_reply = True
                    break
                logger.debug(f"[DEBUG rule_label] Early prescreen match: {rx.pattern[:80]}")
                return "prescreen"

        # Early scheduling-language detection -> interview_invite (AFTER prescreen check)
        # This is important because emails like "Thank you for applying... I would like to discuss"
        # should be classified as interview_invite, not job_application
        # BUT classify as 'other' for replies (to avoid classifying scheduling follow-ups as interviews)
        if any(rx.search(s) for rx in self._early_scheduling):
            if is_reply:
                logger.debug("[DEBUG rule_label] Scheduling language in reply detected -> treating as follow-up (other)")
                # Scheduling follow-ups should be classified as 'other'
                return "other"
            else:
                logger.debug("[DEBUG rule_label] Early scheduling-language match -> interview_invite")
                return "interview_invite"

        # Check application confirmation patterns
        # Safe to check here because all rejection patterns (including overrides)
        # have already been checked above. This handles "Thank you for applying"
        # emails that also contain explanatory text about the review process.
        for rx in self._msg_label_patterns.get("job_application", []):
            if rx.search(s):
                logger.debug(f"[DEBUG rule_label] Application confirmation match: {rx.pattern[:80]}")
                return "job_application"

        # Early referral detection
        if any(rx.search(s) for rx in self._early_referral):
            logger.debug(f"[DEBUG rule_label] Early referral match -> referral")
            return "referral"

        # Explicit application-confirmation signals -> job_application (checked BEFORE status update)
        # This ensures "Thank you for your application" emails aren't misclassified as "other"
        # just because they also mention "under review"
        if any(rx.search(s) for rx in self._early_application_confirm):
            logger.debug("[DEBUG rule_label] Matched application-confirmation -> job_application")
            return "job_application"

        # Status update messages (follow-up/still under review) -> other
        # Only triggers if application-confirmation patterns didn't match above
        if any(rx.search(s) for rx in self._early_status_update):
            logger.debug("[DEBUG rule_label] Matched status-update -> other")
            return "other"

        # Check labels in priority order
        for label in (
            "offer",
            "cancelled",
            "rejection",
            "head_hunter",
            "noise",
            "prescreen",
            "job_application",
            "interview_invite",
            "other",
            "referral",
            "ghosted",
            "blank",
        ):
            # Skip prescreen if we already determined this is a reply to a prescreen thread
            if label == "prescreen" and skip_prescreen_label:
                logger.debug("[DEBUG rule_label] Skipping prescreen label check (reply detected earlier)")
                continue
                
            if label == "rejection":
                logger.debug(f"[DEBUG rule_label] Checking '{label}' patterns...")

            for rx in self._msg_label_patterns.get(label, []):
                match = rx.search(s)
                if match:
                    if label in ("rejection", "noise", "head_hunter"):
                        logger.debug(
                            f"[DEBUG rule_label] Pattern MATCHED for '{label}': {rx.pattern[:80]}"
                        )
                        logger.debug(f"  Matched text: '{match.group()}'")

                    # Check exclude patterns from patterns.json
                    excludes = self._msg_label_excludes.get(label, [])
                    if label in ("noise", "head_hunter") and excludes:
                        logger.debug(
                            f"[DEBUG rule_label] Checking {len(excludes)} exclusion patterns for {label}..."
                        )

                    matched_excludes = [ex for ex in excludes if ex.search(s)]
                    if matched_excludes:
                        logger.debug(
                            f"[DEBUG rule_label] Label '{label}' pattern matched but EXCLUDED by:"
                        )
                        for ex in matched_excludes:
                            logger.debug(f"  - {ex.pattern}")
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
                                is_ats = (
                                    is_ats_domain_fn(d) if is_ats_domain_fn else False
                                )
                                is_job_board = (
                                    d in job_board_domains
                                    if job_board_domains
                                    else False
                                )
                                is_company = (
                                    map_company_by_domain_fn(d)
                                    if map_company_by_domain_fn
                                    else False
                                )
                                if is_ats or is_job_board or is_company:
                                    continue
                        except Exception:
                            pass

                        # Additional strictness for head_hunter: require contact evidence
                        if label == "head_hunter":
                            has_contact = any(
                                re.search(p, s, re.I)
                                for p in self._headhunter_contact_patterns
                            ) or (
                                self._headhunter_signature_rx
                                and self._headhunter_signature_rx.search(s)
                            )
                            if not has_contact:
                                continue
                        else:
                            # For referral: require explicit referral language if no domain
                            if not d:
                                if not (
                                    self._referral_explicit_rx
                                    and self._referral_explicit_rx.search(s)
                                ):
                                    continue

                    # Special case: job_application with scheduling language -> interview_invite
                    # BUT skip for replies (to avoid classifying scheduling follow-ups as interviews)
                    if label == "job_application":
                        if any(rx.search(s) for rx in self._early_scheduling):
                            if is_reply:
                                logger.debug("[DEBUG rule_label] job_application + scheduling in reply -> skipping interview_invite")
                                # Don't convert to interview_invite for scheduling follow-ups
                                # Fall through to return job_application or continue checking
                            else:
                                logger.debug("[DEBUG rule_label] Matched scheduling language -> returning interview_invite")
                                return "interview_invite"

                    if label == "rejection":
                        logger.debug(f"[DEBUG rule_label] About to return '{label}'")
                    return label

        # If this was a reply to a prescreen thread that didn't match any other label,
        # default to 'other' instead of None
        if is_prescreen_reply:
            logger.debug("[DEBUG rule_label] Prescreen reply with no other match -> other")
            return "other"

        return None


