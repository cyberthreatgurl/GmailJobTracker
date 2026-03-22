"""Label propagation utilities.

Functions for propagating message labels to ThreadTracking records.
"""

import logging
import re
from difflib import SequenceMatcher
from typing import Optional
from django.db import transaction

from email_parser import MetadataExtractor
from tracker.models import Message, ThreadTracking

logger = logging.getLogger("parser")


def _extract_application_identity(message: Message) -> tuple[str, str]:
    """Extract job title and job ID for exact application matching."""
    from parser import (
        extract_application_job_id_from_body,
        extract_job_title_from_body,
        parse_subject,
    )

    body = message.body or ""
    parsed = parse_subject(
        subject=message.subject or "",
        body=body,
        sender=message.sender or "",
        sender_domain=message.sender_domain,
    )
    job_title = parsed.get("job_title", "") if isinstance(parsed, dict) else ""
    if not job_title:
        job_title = extract_job_title_from_body(body)
    job_id = ""
    if isinstance(parsed, dict):
        job_id = parsed.get("job_id", "") or ""
    if not job_id:
        job_id = MetadataExtractor.extract_job_id(message.subject or "")
    if not job_id:
        job_id = extract_application_job_id_from_body(body)
    return job_title, job_id


def _normalize_application_identity(text: str) -> str:
    """Normalize job-title and job-id text for exact comparisons."""
    if not text:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _should_reuse_existing_application(tt: ThreadTracking, message: Message) -> tuple[bool, str, str]:
    """Decide whether a same-thread application message should enrich the existing TT."""
    job_title, job_id = _extract_application_identity(message)
    normalized_title = _normalize_application_identity(job_title)
    normalized_id = _normalize_application_identity(job_id)
    existing_title = _normalize_application_identity(tt.job_title or "")
    existing_id = _normalize_application_identity(tt.job_id or "")

    if normalized_id and existing_id:
        return normalized_id == existing_id, job_title, job_id
    if normalized_title and existing_title:
        return normalized_title == existing_title, job_title, job_id
    if (normalized_title or normalized_id) and not existing_title and not existing_id:
        return True, job_title, job_id
    return False, job_title, job_id


def _find_company_application_target(
    message: Message,
    exclude_thread_id: str,
) -> Optional[ThreadTracking]:
    """Find an existing application only when exact job identity is available."""
    if not message.company:
        return None

    job_title, job_id = _extract_application_identity(message)
    normalized_title = _normalize_application_identity(job_title)
    normalized_id = _normalize_application_identity(job_id)
    if not normalized_title and not normalized_id:
        if _is_compliance_prescreen_message(message):
            return _find_unique_active_prior_application(message, exclude_thread_id)
        logger.debug(
            "ℹ️ Skipping cross-thread milestone propagation for %s: no job identity",
            message.company.name,
        )
        return None

    queryset = ThreadTracking.objects.filter(company=message.company)
    excluded_thread_ids = {exclude_thread_id}
    if getattr(message, "msg_id", None):
        excluded_thread_ids.add(message.msg_id)
    excluded_thread_ids.discard("")
    if excluded_thread_ids:
        queryset = queryset.exclude(thread_id__in=excluded_thread_ids)

    candidates = list(queryset.order_by("-sent_date", "-id"))
    milestone_date = message.timestamp.date() if message.timestamp else None
    if milestone_date:
        candidates = [
            candidate for candidate in candidates
            if not candidate.sent_date or candidate.sent_date <= milestone_date
        ]

    for candidate in candidates:
        candidate_id = _normalize_application_identity(candidate.job_id or "")
        if normalized_id and candidate_id == normalized_id:
            return candidate

    for candidate in candidates:
        candidate_title = _normalize_application_identity(candidate.job_title or "")
        if normalized_title and candidate_title == normalized_title:
            return candidate

    logger.debug(
        "ℹ️ Skipping cross-thread milestone propagation for %s: no exact application match",
        message.company.name,
    )

    if _is_compliance_prescreen_message(message):
        return _find_unique_active_prior_application(message, exclude_thread_id)

    return None


def _is_compliance_prescreen_message(message: Message) -> bool:
    """Return True for compliance/prescreen workflow messages without job identity."""
    text = f"{message.subject or ''} {message.body or ''}".lower()
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


def _find_unique_active_prior_application(
    message: Message,
    exclude_thread_id: str,
) -> Optional[ThreadTracking]:
    """Return a unique active application candidate for compliance prescreens."""
    if not message.company:
        return None

    queryset = ThreadTracking.objects.filter(company=message.company)
    excluded_thread_ids = {exclude_thread_id}
    if getattr(message, "msg_id", None):
        excluded_thread_ids.add(message.msg_id)
    excluded_thread_ids.discard("")
    if excluded_thread_ids:
        queryset = queryset.exclude(thread_id__in=excluded_thread_ids)

    milestone_date = message.timestamp.date() if message.timestamp else None
    candidates = [
        candidate for candidate in queryset.order_by("-sent_date", "-id")
        if _is_application_like_threadtracking(candidate)
        and not candidate.rejection_date
        and not candidate.cancelled
        and not candidate.withdrew
        and (not milestone_date or not candidate.sent_date or candidate.sent_date <= milestone_date)
    ]

    if len(candidates) == 1:
        return candidates[0]
    return None


def _is_application_like_threadtracking(tt: ThreadTracking) -> bool:
    """Return True when a ThreadTracking row represents the canonical application."""
    if not tt:
        return False

    return bool(
        tt.ml_label == "job_application"
        or _normalize_application_identity(tt.job_title or "")
        or _normalize_application_identity(tt.job_id or "")
    )


def _find_company_offer_target(
    message: Message,
    exclude_thread_id: str,
    current_tt: Optional[ThreadTracking] = None,
) -> Optional[ThreadTracking]:
    """Find the canonical application that should receive an offer milestone."""
    milestone_date = message.timestamp.date() if message.timestamp else None

    if current_tt and _is_application_like_threadtracking(current_tt):
        if not milestone_date or not current_tt.sent_date or current_tt.sent_date <= milestone_date:
            return current_tt

    target = _find_company_application_target(message, exclude_thread_id=exclude_thread_id)
    if target is not None:
        return target

    if not message.company:
        return None

    queryset = ThreadTracking.objects.filter(company=message.company)
    excluded_thread_ids = {exclude_thread_id}
    if getattr(message, "msg_id", None):
        excluded_thread_ids.add(message.msg_id)
    excluded_thread_ids.discard("")
    if excluded_thread_ids:
        queryset = queryset.exclude(thread_id__in=excluded_thread_ids)

    candidates = [candidate for candidate in queryset.order_by("-sent_date", "-id") if _is_application_like_threadtracking(candidate)]
    if milestone_date:
        candidates = [
            candidate for candidate in candidates
            if not candidate.sent_date or candidate.sent_date <= milestone_date
        ]

    if len(candidates) == 1:
        return candidates[0]
    return None


def _normalize_title(text: str) -> str:
    """Normalize job-title text for approximate matching."""
    if not text:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _extract_rejection_title(message: Message) -> str:
    """Extract a candidate role title from a rejection/cancelled message subject/body."""
    subject = (message.subject or "").strip()
    body = (message.body or "").strip()

    patterns = [
        r"application\s+status\s+for\s+(.+)$",
        r"rejection\s+for\s+(.+)$",
        r"confirmation\s+of\s+withdraw\s+from\s+(.+)$",
        r"withdraw(?:al)?\s+from\s+(.+)$",
        r"for\s+the\s+(.+?)\s+position",
    ]
    for pattern in patterns:
        match = re.search(pattern, subject, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .:-")

    body_match = re.search(
        r"(?:position|role)\s*[:\-]\s*([^\n\r.]{6,120})",
        body,
        flags=re.IGNORECASE,
    )
    if body_match:
        return body_match.group(1).strip(" .:-")

    return ""


def _find_company_rejection_target(message: Message, exclude_thread_id: str) -> Optional[ThreadTracking]:
    """Find a single, confident ThreadTracking target for cross-thread rejection updates."""
    if not message.company:
        return None

    candidates = list(
        ThreadTracking.objects.filter(
            company=message.company,
        )
        .exclude(thread_id=exclude_thread_id)
    )
    if not candidates:
        return None

    extracted_title = _normalize_title(_extract_rejection_title(message))
    if not extracted_title:
        logger.debug(
            "ℹ️ Skipping cross-thread rejection propagation for %s: no title evidence",
            message.company.name,
        )
        return None

    scored_candidates = []
    for candidate in candidates:
        candidate_title = _normalize_title(candidate.job_title or "")
        if not candidate_title:
            continue
        score = SequenceMatcher(None, extracted_title, candidate_title).ratio()
        scored_candidates.append((candidate, score))

    if not scored_candidates:
        return None

    scored_candidates.sort(
        key=lambda item: (item[1], item[0].rejection_date is None),
        reverse=True,
    )
    best_candidate, best_score = scored_candidates[0]
    second_score = scored_candidates[1][1] if len(scored_candidates) > 1 else 0.0

    if best_score < 0.72 or (best_score - second_score) < 0.08:
        logger.debug(
            "ℹ️ Skipping cross-thread rejection propagation for %s: ambiguous match"
            " (best=%.3f, second=%.3f, title='%s')",
            message.company.name,
            best_score,
            second_score,
            extracted_title,
        )
        return None

    return best_candidate


def _should_propagate_cross_thread(message: Message, current_tt: ThreadTracking) -> bool:
    """Decide whether a rejection should propagate beyond the current thread TT.

    If the current TT already has a confident title match to the rejection message,
    do not propagate to other applications at the same company.
    """
    if not current_tt:
        return True

    current_title = _normalize_title(current_tt.job_title or "")
    extracted_title = _normalize_title(_extract_rejection_title(message))

    if not current_title:
        # Current TT is likely spurious/incomplete; allow cross-thread repair.
        return True

    if not extracted_title:
        # No evidence to justify touching other application records.
        return False

    score = SequenceMatcher(None, extracted_title, current_title).ratio()
    return score < 0.72


def _check_cancelled_from_body(message: Message) -> bool:
    """Check if message body/subject indicates a cancelled position.

    Uses is_cancelled_position() from parser_helpers for pattern matching.
    """
    try:
        from parser_helpers import is_cancelled_position
        return is_cancelled_position(
            message.subject or "", message.body or ""
        )
    except ImportError:
        return False


def _check_withdrawn_from_body(message: Message) -> bool:
    """Check if message body/subject indicates a withdrawn application.

    Uses is_withdrawn_position() from parser_helpers for pattern matching.
    """
    try:
        from parser_helpers import is_withdrawn_position
        return is_withdrawn_position(
            message.subject or "", message.body or ""
        )
    except ImportError:
        return False


def _propagate_rejection_to_company(
    message: Message, msg_date, exclude_thread_id: str, is_cancelled: bool, is_withdrawn: bool = False
) -> None:
    """Propagate rejection/cancelled/withdrawn to other ThreadTracking records for the same company.

    When a rejection arrives on a different thread than the original application,
    the thread_id-based lookup finds the wrong TT (or a spurious one created from
    a misclassification). This function ensures the actual application TT for the
    same company also gets updated with rejection_date and cancelled/withdrawn status.

    Only updates the earliest application (by sent_date) for the company that
    doesn't already have a rejection_date.
    """
    if not message.company:
        return

    other_tt = _find_company_rejection_target(message, exclude_thread_id)
    if other_tt:
        other_tt.rejection_date = msg_date
        if is_cancelled and not other_tt.cancelled:
            other_tt.cancelled = True
        if is_withdrawn and not other_tt.withdrew:
            other_tt.withdrew = True
        other_tt.save()
        logger.debug(
            f"✓ Cross-thread rejection propagation: updated TT id={other_tt.id}"
            f" ('{other_tt.job_title}') for {message.company.name}"
            f", rejection_date={msg_date}, cancelled={other_tt.cancelled}, withdrew={other_tt.withdrew}"
        )


def propagate_message_label_to_thread(message: Message) -> Optional[ThreadTracking]:
    """Ensure a Message's ml_label is reflected on its ThreadTracking.

    - If a ThreadTracking exists for the message.thread_id, update its ml_label and ml_confidence.
    - If none exists and the message label indicates an application/interview and the message has a company,
      create a minimal ThreadTracking record.
    - When label changes to prescreen/interview_invite, update corresponding date fields.
    - For rejection/cancelled labels, also checks message body for cancellation indicators
      and propagates rejection to other ThreadTracking records for the same company.

    Returns the ThreadTracking instance (created or updated), or None if nothing was done.
    """
    if not message or not getattr(message, "thread_id", None):
        return None

    thread_id = message.thread_id
    msg_date = message.timestamp.date() if message.timestamp else None

    try:
        with transaction.atomic():
            tt = ThreadTracking.objects.filter(thread_id=thread_id).first()
            if tt:
                # Multiple applications on same Gmail thread detection:
                # If both the existing TT and this message are job_application,
                # and this message's msg_id differs from the Gmail thread_id,
                # this is a separate application that Gmail grouped together
                # (e.g., identical ATS confirmation subjects).
                if (
                    message.ml_label == "job_application"
                    and tt.ml_label == "job_application"
                    and hasattr(message, "msg_id")
                    and message.msg_id
                    and message.msg_id != thread_id
                ):
                    reuse_existing, job_title, job_id = _should_reuse_existing_application(tt, message)
                    if reuse_existing:
                        changed = False
                        if job_title and not tt.job_title:
                            tt.job_title = job_title
                            changed = True
                        if job_id and not tt.job_id:
                            tt.job_id = job_id
                            changed = True
                        if message.confidence is not None and (
                            tt.ml_confidence is None or tt.ml_confidence != message.confidence
                        ):
                            tt.ml_confidence = message.confidence
                            changed = True
                        if changed:
                            tt.save()
                        return tt

                    msg_tt = ThreadTracking.objects.filter(
                        thread_id=message.msg_id
                    ).first()
                    if msg_tt:
                        # Already has its own TT — update confidence if needed
                        if message.confidence is not None and (
                            msg_tt.ml_confidence is None
                            or msg_tt.ml_confidence != message.confidence
                        ):
                            msg_tt.ml_confidence = message.confidence
                            msg_tt.save()
                        return msg_tt
                    # Create separate TT for this application
                    new_tt = ThreadTracking.objects.create(
                        thread_id=message.msg_id,
                        company=message.company,
                        company_source=message.company_source or "manual",
                        job_title=job_title,
                        job_id=job_id,
                        status="application",
                        sent_date=msg_date,
                        ml_label=message.ml_label,
                        ml_confidence=(message.confidence or 0.0),
                    )
                    logger.debug(
                        f"✓ Created separate ThreadTracking (id={new_tt.id}) "
                        f"for additional application on same Gmail thread "
                        f"(msg_id={message.msg_id})"
                    )
                    return new_tt

                target_tt = tt
                if message.ml_label == "offer":
                    offer_target = _find_company_offer_target(
                        message,
                        exclude_thread_id=thread_id,
                        current_tt=tt,
                    )
                    if offer_target is not None:
                        target_tt = offer_target

                changed = False
                is_cancelled = False
                old_label = target_tt.ml_label
                if message.ml_label and target_tt.ml_label != message.ml_label:
                    target_tt.ml_label = message.ml_label
                    changed = True

                    # Update date fields based on new label
                    if message.ml_label == "prescreen" and not target_tt.prescreen_date:
                        target_tt.prescreen_date = msg_date
                        # Clear interview_date if it was set from old label
                        if old_label == "interview_invite" and target_tt.interview_date == msg_date:
                            target_tt.interview_date = None
                    elif message.ml_label == "interview_invite" and not target_tt.interview_date:
                        target_tt.interview_date = msg_date
                        # Clear prescreen_date if it was set from old label
                        if old_label == "prescreen" and target_tt.prescreen_date == msg_date:
                            target_tt.prescreen_date = None
                    elif message.ml_label == "offer" and not target_tt.offer_date:
                        target_tt.offer_date = msg_date
                        target_tt.status = "offer"
                    elif message.ml_label in ("rejection", "cancelled", "withdrew") and not target_tt.rejection_date:
                        target_tt.rejection_date = msg_date
                        # Body-based cancellation detection
                        is_cancelled = (
                            message.ml_label == "cancelled"
                            or _check_cancelled_from_body(message)
                        )
                        if is_cancelled:
                            target_tt.cancelled = True

                        # Body-based withdrawn detection
                        is_withdrawn = (
                            message.ml_label == "withdrew"
                            or _check_withdrawn_from_body(message)
                        )
                        if is_withdrawn:
                            target_tt.withdrew = True

                if message.confidence is not None and (
                    target_tt.ml_confidence is None or target_tt.ml_confidence != message.confidence
                ):
                    target_tt.ml_confidence = message.confidence
                    changed = True
                if changed:
                    target_tt.save()

                # Cross-thread rejection propagation: also update other TTs
                # from the same company that don't have rejection_date set.
                # This handles cases where a rejection arrives on a different
                # thread than the application, or when a spurious TT was created
                # from a prior misclassification.
                if message.ml_label in ("rejection", "cancelled", "withdrew"):
                    if not is_cancelled:
                        is_cancelled = (
                            message.ml_label == "cancelled"
                            or _check_cancelled_from_body(message)
                        )
                    is_withdrawn = (
                        message.ml_label == "withdrew"
                        or _check_withdrawn_from_body(message)
                    )
                    if _should_propagate_cross_thread(message, target_tt):
                        _propagate_rejection_to_company(
                            message, msg_date, thread_id, is_cancelled, is_withdrawn
                        )

                return target_tt

            # No ThreadTracking for this thread_id exists
            # For prescreen/interview/rejection messages, check if company already has a ThreadTracking
            # and update that one instead of creating a duplicate
            if (
                message.ml_label in ("prescreen", "interview_invite", "offer", "rejection", "cancelled", "withdrew")
                and message.company
            ):
                existing_tt = None
                if message.ml_label in ("rejection", "cancelled", "withdrew"):
                    # For rejection labels, only update when there is a confident title match.
                    existing_tt = _find_company_rejection_target(message, exclude_thread_id="")
                elif message.ml_label == "offer":
                    existing_tt = _find_company_offer_target(message, exclude_thread_id="")
                else:
                    existing_tt = _find_company_application_target(
                        message,
                        exclude_thread_id="",
                    )

                if existing_tt:
                    # Update the existing record with the date
                    changed = False
                    if message.ml_label == "prescreen" and not existing_tt.prescreen_date:
                        existing_tt.prescreen_date = msg_date
                        changed = True
                    elif message.ml_label == "interview_invite" and not existing_tt.interview_date:
                        existing_tt.interview_date = msg_date
                        changed = True
                    elif message.ml_label == "offer" and not existing_tt.offer_date:
                        existing_tt.offer_date = msg_date
                        existing_tt.status = "offer"
                        changed = True
                    elif message.ml_label in ("rejection", "cancelled", "withdrew") and not existing_tt.rejection_date:
                        existing_tt.rejection_date = msg_date
                        is_cancelled = (
                            message.ml_label == "cancelled"
                            or _check_cancelled_from_body(message)
                        )
                        if is_cancelled:
                            existing_tt.cancelled = True
                        is_withdrawn = (
                            message.ml_label == "withdrew"
                            or _check_withdrawn_from_body(message)
                        )
                        if is_withdrawn:
                            existing_tt.withdrew = True
                        changed = True
                    if changed:
                        existing_tt.save()
                    return existing_tt

            # Only application messages create a new ThreadTracking without an existing anchor.
            if message.ml_label == "job_application" and message.company:
                tt = ThreadTracking.objects.create(
                    thread_id=thread_id,
                    company=message.company,
                    company_source=message.company_source or "manual",
                    job_title="",
                    job_id="",
                    status="application",
                    sent_date=(message.timestamp.date() if message.timestamp else None),
                    prescreen_date=None,
                    interview_date=None,
                    ml_label=message.ml_label,
                    ml_confidence=(message.confidence or 0.0),
                )
                return tt
    except Exception:
        # Don't propagate exceptions — callers should handle/log if needed.
        return None

    return None
