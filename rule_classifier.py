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
            "withdrew": "withdrew",
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

    def _scan_all_pattern_matches(self, text: str):
        """Return all positive regex matches across labels for debugger tracing."""
        matches = []
        for label, patterns in self._msg_label_patterns.items():
            for rx in patterns:
                match = rx.search(text)
                if match:
                    matches.append(
                        {
                            "label": label,
                            "pattern": rx.pattern,
                            "matched_text": match.group(0),
                        }
                    )
        return matches

    def debug_classify(
        self,
        subject: str,
        body: str = "",
        sender_domain=None,
        headhunter_domains: set = None,
        job_board_domains: set = None,
        is_ats_domain_fn=None,
        map_company_by_domain_fn=None,
    ):
        """Return classifier trace details for the label-rule debugger UI."""
        text = f"{subject or ''} {body or ''}"
        subject_text = subject or ""
        domain = (sender_domain or "").lower()
        raw_matches = self._scan_all_pattern_matches(text)
        skipped_matches = []

        # Track explicit exclude-based skips.
        for raw_match in raw_matches:
            excludes = self._msg_label_excludes.get(raw_match["label"], [])
            for exclude in excludes:
                exclude_match = exclude.search(text)
                if exclude_match:
                    skipped_matches.append(
                        {
                            "label": raw_match["label"],
                            "pattern": raw_match["pattern"],
                            "matched_text": raw_match["matched_text"],
                            "reason": "excluded by label exclude pattern",
                            "exclude_pattern": exclude.pattern,
                            "exclude_text": exclude_match.group(0),
                        }
                    )

        # Track guard-based skips for conservative recruiter/referral handling.
        for raw_match in raw_matches:
            label = raw_match["label"]
            if label not in ("head_hunter", "referral", "prescreen"):
                continue

            if label == "prescreen":
                is_reply = subject and any(
                    rx.search(subject) for rx in self._reply_indicators
                )
                if is_reply:
                    skipped_matches.append(
                        {
                            "label": label,
                            "pattern": raw_match["pattern"],
                            "matched_text": raw_match["matched_text"],
                            "reason": "skipped because reply messages are treated as follow-up/other",
                        }
                    )
                continue

            if headhunter_domains and domain and domain in headhunter_domains:
                continue

            try:
                is_ats = is_ats_domain_fn(domain) if (domain and is_ats_domain_fn) else False
                is_job_board = domain in job_board_domains if (domain and job_board_domains) else False
                is_company = map_company_by_domain_fn(domain) if (domain and map_company_by_domain_fn) else False
            except Exception:
                is_ats = False
                is_job_board = False
                is_company = False

            if is_ats or is_job_board or is_company:
                reasons = []
                if is_ats:
                    reasons.append("ATS domain")
                if is_job_board:
                    reasons.append("job board domain")
                if is_company:
                    reasons.append("known company domain")
                skipped_matches.append(
                    {
                        "label": label,
                        "pattern": raw_match["pattern"],
                        "matched_text": raw_match["matched_text"],
                        "reason": f"skipped by domain safeguard ({', '.join(reasons)})",
                    }
                )
                continue

            if label == "head_hunter":
                has_contact = any(
                    re.search(pattern, text, re.I)
                    for pattern in self._headhunter_contact_patterns
                ) or (
                    self._headhunter_signature_rx
                    and self._headhunter_signature_rx.search(text)
                )
                if not has_contact:
                    skipped_matches.append(
                        {
                            "label": label,
                            "pattern": raw_match["pattern"],
                            "matched_text": raw_match["matched_text"],
                            "reason": "skipped because recruiter contact evidence was not found",
                        }
                    )

        decision_trace = []
        final_rule_label = self._classify_internal(
            subject=subject,
            body=body,
            sender_domain=sender_domain,
            headhunter_domains=headhunter_domains,
            job_board_domains=job_board_domains,
            is_ats_domain_fn=is_ats_domain_fn,
            map_company_by_domain_fn=map_company_by_domain_fn,
            trace=decision_trace,
        )

        # Remove duplicate skip records from multiple matching excludes.
        deduped_skips = []
        seen = set()
        for skipped in skipped_matches:
            key = (
                skipped.get("label"),
                skipped.get("pattern"),
                skipped.get("reason"),
                skipped.get("exclude_pattern"),
            )
            if key not in seen:
                seen.add(key)
                deduped_skips.append(skipped)

        return {
            "final_rule_label": final_rule_label,
            "raw_matches": raw_matches,
            "skipped_matches": deduped_skips,
            "subject_text": subject_text,
            "decision_trace": decision_trace,
        }

    def _add_trace(self, trace, step: str, outcome: str, detail: str):
        """Append an ordered classifier decision event when tracing is enabled."""
        if trace is not None:
            trace.append({"step": step, "outcome": outcome, "detail": detail})

    def _classify_internal(
        self,
        subject: str,
        body: str = "",
        sender_domain=None,
        headhunter_domains: set = None,
        job_board_domains: set = None,
        is_ats_domain_fn=None,
        map_company_by_domain_fn=None,
        trace=None,
    ):
        """Shared classifier implementation with optional chronological tracing."""
        s = f"{subject or ''} {body or ''}"

        if subject and any(rx.search(subject) for rx in self._special_indeed_subject):
            self._add_trace(
                trace,
                "special_indeed_subject",
                "matched",
                "Forced job_application for Indeed application subject.",
            )
            logger.debug("[DEBUG rule_label] Forcing job_application for Indeed Application subject")
            return "job_application"
        self._add_trace(trace, "special_indeed_subject", "checked", "No Indeed subject override matched.")

        subject_text = subject or ""
        if any(rx.search(subject_text) for rx in self._special_assessment):
            self._add_trace(
                trace,
                "special_assessment",
                "matched",
                "Forced other for assessment completion notification.",
            )
            logger.debug("[DEBUG rule_label] Forcing 'other' for assessment completion notification")
            return "other"
        self._add_trace(trace, "special_assessment", "checked", "No assessment completion override matched.")

        if any(rx.search(s) for rx in self._special_incomplete_app):
            self._add_trace(
                trace,
                "special_incomplete_application",
                "matched",
                "Forced other for incomplete application reminder.",
            )
            logger.debug("[DEBUG rule_label] Forcing 'other' for incomplete application reminder")
            return "other"
        self._add_trace(trace, "special_incomplete_application", "checked", "No incomplete application override matched.")

        if any(rx.search(s) for rx in self._early_cancelled):
            self._add_trace(trace, "early_cancelled", "matched", "Matched cancelled-position language.")
            logger.debug("[DEBUG rule_label] Early cancelled match - position was cancelled")
            return "cancelled"
        self._add_trace(trace, "early_cancelled", "checked", "No cancelled-position language matched.")

        noise_patterns = self._msg_label_patterns.get("noise", [])
        noise_excludes = self._msg_label_excludes.get("noise", [])
        subject_text_only = subject or ""

        def is_excluded_noise(text_to_check):
            if not noise_excludes:
                return False
            return any(ex.search(text_to_check) for ex in noise_excludes)

        if any(rx.search(subject_text_only) for rx in noise_patterns):
            if not is_excluded_noise(s):
                self._add_trace(trace, "early_noise_subject", "matched", "Noise pattern matched on subject and was not excluded.")
                logger.debug("[DEBUG rule_label] Early noise match on subject -> noise")
                return "noise"
            self._add_trace(trace, "early_noise_subject", "excluded", "Noise pattern matched on subject but an exclude rule prevented classification.")
            logger.debug("[DEBUG rule_label] Early noise match on subject but EXCLUDED -> continuing")
        else:
            self._add_trace(trace, "early_noise_subject", "checked", "No subject-level noise pattern matched.")

        if any(rx.search(s) for rx in noise_patterns):
            if not is_excluded_noise(s):
                self._add_trace(trace, "early_noise_body", "matched", "Noise pattern matched on full text and was not excluded.")
                logger.debug("[DEBUG rule_label] Early noise match on body -> noise")
                return "noise"
            self._add_trace(trace, "early_noise_body", "excluded", "Noise pattern matched on full text but an exclude rule prevented classification.")
            logger.debug("[DEBUG rule_label] Early noise match on body but EXCLUDED -> continuing")
        else:
            self._add_trace(trace, "early_noise_body", "checked", "No full-text noise pattern matched.")

        withdrew_patterns = self._msg_label_patterns.get("withdrew", [])
        if any(rx.search(s) for rx in withdrew_patterns):
            self._add_trace(trace, "withdrew", "matched", "Matched withdrew language.")
            logger.debug("[DEBUG rule_label] Withdrew detected")
            return "withdrew"
        self._add_trace(trace, "withdrew", "checked", "No withdrew language matched.")

        rejection_patterns = self._msg_label_patterns.get("rejection", [])
        if any(rx.search(s) for rx in rejection_patterns) or any(
            rx.search(s) for rx in self._early_rejection_override
        ):
            self._add_trace(trace, "early_rejection", "matched", "Matched rejection patterns or rejection override language.")
            logger.debug("[DEBUG rule_label] Rejection detected (patterns or override)")
            return "rejection"
        self._add_trace(trace, "early_rejection", "checked", "No rejection or rejection override matched.")

        is_reply = subject and any(rx.search(subject) for rx in self._reply_indicators)
        self._add_trace(
            trace,
            "reply_detection",
            "matched" if is_reply else "checked",
            "Reply/follow-up subject detected." if is_reply else "No reply/follow-up prefix detected.",
        )

        skip_prescreen_label = False
        is_prescreen_reply = False
        for rx in self._msg_label_patterns.get("prescreen", []):
            if rx.search(s):
                if is_reply:
                    self._add_trace(trace, "early_prescreen", "skipped", f"Prescreen pattern matched but was treated as follow-up because subject is a reply: {rx.pattern}")
                    logger.debug("[DEBUG rule_label] Prescreen pattern in reply -> treating as follow-up (other)")
                    skip_prescreen_label = True
                    is_prescreen_reply = True
                    break
                self._add_trace(trace, "early_prescreen", "matched", f"Matched early prescreen pattern: {rx.pattern}")
                logger.debug(f"[DEBUG rule_label] Early prescreen match: {rx.pattern[:80]}")
                return "prescreen"
        if not skip_prescreen_label:
            self._add_trace(trace, "early_prescreen", "checked", "No early prescreen pattern matched.")

        if any(rx.search(s) for rx in self._early_scheduling):
            if is_reply:
                self._add_trace(trace, "early_scheduling", "matched", "Scheduling language matched in a reply, so the classifier returns other.")
                logger.debug("[DEBUG rule_label] Scheduling language in reply detected -> treating as follow-up (other)")
                return "other"
            self._add_trace(trace, "early_scheduling", "matched", "Scheduling language matched, so the classifier returns interview_invite.")
            logger.debug("[DEBUG rule_label] Early scheduling-language match -> interview_invite")
            return "interview_invite"
        self._add_trace(trace, "early_scheduling", "checked", "No early scheduling language matched.")

        for rx in self._msg_label_patterns.get("job_application", []):
            if rx.search(s):
                self._add_trace(trace, "application_confirmation_patterns", "matched", f"Matched application confirmation pattern: {rx.pattern}")
                logger.debug(f"[DEBUG rule_label] Application confirmation match: {rx.pattern[:80]}")
                return "job_application"
        self._add_trace(trace, "application_confirmation_patterns", "checked", "No application confirmation pattern matched.")

        if any(rx.search(s) for rx in self._early_referral):
            self._add_trace(trace, "early_referral", "matched", "Matched explicit referral language.")
            logger.debug(f"[DEBUG rule_label] Early referral match -> referral")
            return "referral"
        self._add_trace(trace, "early_referral", "checked", "No early referral language matched.")

        if any(rx.search(s) for rx in self._early_application_confirm):
            self._add_trace(trace, "early_application_confirmation", "matched", "Matched explicit application-confirmation language.")
            logger.debug("[DEBUG rule_label] Matched application-confirmation -> job_application")
            return "job_application"
        self._add_trace(trace, "early_application_confirmation", "checked", "No explicit application-confirmation override matched.")

        if any(rx.search(s) for rx in self._early_status_update):
            self._add_trace(trace, "early_status_update", "matched", "Matched application status-update language.")
            logger.debug("[DEBUG rule_label] Matched status-update -> other")
            return "other"
        self._add_trace(trace, "early_status_update", "checked", "No status-update language matched.")

        for label in (
            "offer",
            "cancelled",
            "withdrew",
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
            self._add_trace(trace, f"priority_{label}", "checked", f"Checking priority patterns for {label}.")

            if label == "prescreen" and skip_prescreen_label:
                self._add_trace(trace, f"priority_{label}", "skipped", "Skipped prescreen in priority loop because a reply matched prescreen earlier.")
                logger.debug("[DEBUG rule_label] Skipping prescreen label check (reply detected earlier)")
                continue

            if label == "rejection":
                logger.debug(f"[DEBUG rule_label] Checking '{label}' patterns...")

            for rx in self._msg_label_patterns.get(label, []):
                match = rx.search(s)
                if not match:
                    continue

                if label in ("rejection", "noise", "head_hunter"):
                    logger.debug(
                        f"[DEBUG rule_label] Pattern MATCHED for '{label}': {rx.pattern[:80]}"
                    )
                    logger.debug(f"  Matched text: '{match.group()}'")

                excludes = self._msg_label_excludes.get(label, [])
                matched_excludes = [ex for ex in excludes if ex.search(s)]
                if matched_excludes:
                    self._add_trace(trace, f"priority_{label}", "excluded", f"Pattern matched but exclude rules blocked it: {rx.pattern}")
                    logger.debug(
                        f"[DEBUG rule_label] Label '{label}' pattern matched but EXCLUDED by:"
                    )
                    for ex in matched_excludes:
                        logger.debug(f"  - {ex.pattern}")
                    continue

                if label in ("head_hunter", "referral"):
                    d = (sender_domain or "").lower()

                    if headhunter_domains and d and d in headhunter_domains:
                        self._add_trace(trace, f"priority_{label}", "matched", f"Pattern matched and sender domain is explicitly configured as a headhunter domain: {d}")
                        return label

                    try:
                        if d:
                            is_ats = is_ats_domain_fn(d) if is_ats_domain_fn else False
                            is_job_board = d in job_board_domains if job_board_domains else False
                            is_company = map_company_by_domain_fn(d) if map_company_by_domain_fn else False
                            if is_ats or is_job_board or is_company:
                                reasons = []
                                if is_ats:
                                    reasons.append("ATS domain")
                                if is_job_board:
                                    reasons.append("job board domain")
                                if is_company:
                                    reasons.append("known company domain")
                                self._add_trace(trace, f"priority_{label}", "skipped", f"Pattern matched but was skipped by domain safeguard ({', '.join(reasons)}): {rx.pattern}")
                                continue
                    except Exception:
                        self._add_trace(trace, f"priority_{label}", "checked", "Domain safeguard lookup raised an exception; continuing conservatively.")

                    if label == "head_hunter":
                        has_contact = any(re.search(p, s, re.I) for p in self._headhunter_contact_patterns) or (
                            self._headhunter_signature_rx and self._headhunter_signature_rx.search(s)
                        )
                        if not has_contact:
                            self._add_trace(trace, f"priority_{label}", "skipped", f"Pattern matched but recruiter contact evidence was missing: {rx.pattern}")
                            continue
                    else:
                        if not d:
                            if not (
                                self._referral_explicit_rx
                                and self._referral_explicit_rx.search(s)
                            ):
                                self._add_trace(trace, f"priority_{label}", "skipped", f"Pattern matched but explicit referral language was missing without a sender domain: {rx.pattern}")
                                continue

                if label == "job_application":
                    if any(rx.search(s) for rx in self._early_scheduling):
                        if is_reply:
                            self._add_trace(trace, f"priority_{label}", "checked", "Job application matched with scheduling language in a reply; keeping job_application instead of upgrading.")
                            logger.debug("[DEBUG rule_label] job_application + scheduling in reply -> skipping interview_invite")
                        else:
                            self._add_trace(trace, f"priority_{label}", "matched", "Job application pattern matched with scheduling language, so the classifier exits as interview_invite.")
                            logger.debug("[DEBUG rule_label] Matched scheduling language -> returning interview_invite")
                            return "interview_invite"

                if label == "rejection":
                    logger.debug(f"[DEBUG rule_label] About to return '{label}'")
                self._add_trace(trace, f"priority_{label}", "matched", f"Pattern matched and classifier exited with {label}: {rx.pattern}")
                return label

        if is_prescreen_reply:
            self._add_trace(trace, "prescreen_reply_fallback", "matched", "No later rule matched, so a prescreen reply defaults to other.")
            logger.debug("[DEBUG rule_label] Prescreen reply with no other match -> other")
            return "other"

        self._add_trace(trace, "final", "no_match", "No rule matched; classifier returned None.")
        return None

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
        return self._classify_internal(
            subject=subject,
            body=body,
            sender_domain=sender_domain,
            headhunter_domains=headhunter_domains,
            job_board_domains=job_board_domains,
            is_ats_domain_fn=is_ats_domain_fn,
            map_company_by_domain_fn=map_company_by_domain_fn,
            trace=None,
        )


