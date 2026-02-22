"""Label propagation utilities.

Functions for propagating message labels to ThreadTracking records.
"""

import logging
import re
from difflib import SequenceMatcher
from typing import Optional
from django.db import transaction

from tracker.models import Message, ThreadTracking

logger = logging.getLogger("parser")


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
                        job_title="",
                        job_id="",
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

                changed = False
                is_cancelled = False
                old_label = tt.ml_label
                if message.ml_label and tt.ml_label != message.ml_label:
                    tt.ml_label = message.ml_label
                    changed = True

                    # Update date fields based on new label
                    if message.ml_label == "prescreen" and not tt.prescreen_date:
                        tt.prescreen_date = msg_date
                        # Clear interview_date if it was set from old label
                        if old_label == "interview_invite" and tt.interview_date == msg_date:
                            tt.interview_date = None
                    elif message.ml_label == "interview_invite" and not tt.interview_date:
                        tt.interview_date = msg_date
                        # Clear prescreen_date if it was set from old label
                        if old_label == "prescreen" and tt.prescreen_date == msg_date:
                            tt.prescreen_date = None
                    elif message.ml_label in ("rejection", "cancelled", "withdrew") and not tt.rejection_date:
                        tt.rejection_date = msg_date
                        # Body-based cancellation detection
                        is_cancelled = (
                            message.ml_label == "cancelled"
                            or _check_cancelled_from_body(message)
                        )
                        if is_cancelled:
                            tt.cancelled = True
                        
                        # Body-based withdrawn detection
                        is_withdrawn = (
                            message.ml_label == "withdrew"
                            or _check_withdrawn_from_body(message)
                        )
                        if is_withdrawn:
                            tt.withdrew = True

                if message.confidence is not None and (
                    tt.ml_confidence is None or tt.ml_confidence != message.confidence
                ):
                    tt.ml_confidence = message.confidence
                    changed = True
                if changed:
                    tt.save()

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
                    if _should_propagate_cross_thread(message, tt):
                        _propagate_rejection_to_company(
                            message, msg_date, thread_id, is_cancelled, is_withdrawn
                        )

                return tt

            # No ThreadTracking for this thread_id exists
            # For prescreen/interview/rejection messages, check if company already has a ThreadTracking
            # and update that one instead of creating a duplicate
            if (
                message.ml_label in ("prescreen", "interview_invite", "rejection", "cancelled", "withdrew")
                and message.company
            ):
                existing_tt = None
                if message.ml_label in ("rejection", "cancelled", "withdrew"):
                    # For rejection labels, only update when there is a confident title match.
                    existing_tt = _find_company_rejection_target(message, exclude_thread_id="")
                else:
                    # For prescreen/interview labels, keep existing earliest-company fallback.
                    existing_tt = ThreadTracking.objects.filter(
                        company=message.company
                    ).order_by("sent_date").first()
                
                if existing_tt:
                    # Update the existing record with the date
                    changed = False
                    if message.ml_label == "prescreen" and not existing_tt.prescreen_date:
                        existing_tt.prescreen_date = msg_date
                        changed = True
                    elif message.ml_label == "interview_invite" and not existing_tt.interview_date:
                        existing_tt.interview_date = msg_date
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

            # Create new ThreadTracking for job_application, or prescreen/interview without existing company record
            if (
                message.ml_label in ("job_application", "interview_invite", "prescreen")
                and message.company
            ):
                # Determine date fields based on label
                prescreen_date = msg_date if message.ml_label == "prescreen" else None
                interview_date = msg_date if message.ml_label == "interview_invite" else None

                tt = ThreadTracking.objects.create(
                    thread_id=thread_id,
                    company=message.company,
                    company_source=message.company_source or "manual",
                    job_title="",
                    job_id="",
                    status="application",
                    sent_date=(message.timestamp.date() if message.timestamp else None),
                    prescreen_date=prescreen_date,
                    interview_date=interview_date,
                    ml_label=message.ml_label,
                    ml_confidence=(message.confidence or 0.0),
                )
                return tt
    except Exception:
        # Don't propagate exceptions — callers should handle/log if needed.
        return None

    return None
