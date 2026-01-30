"""Label propagation utilities.

Functions for propagating message labels to ThreadTracking records.
"""

from typing import Optional
from django.db import transaction

from tracker.models import Message, ThreadTracking


def propagate_message_label_to_thread(message: Message) -> Optional[ThreadTracking]:
    """Ensure a Message's ml_label is reflected on its ThreadTracking.

    - If a ThreadTracking exists for the message.thread_id, update its ml_label and ml_confidence.
    - If none exists and the message label indicates an application/interview and the message has a company,
      create a minimal ThreadTracking record.
    - When label changes to prescreen/interview_invite, update corresponding date fields.

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
                changed = False
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

                if message.confidence is not None and (
                    tt.ml_confidence is None or tt.ml_confidence != message.confidence
                ):
                    tt.ml_confidence = message.confidence
                    changed = True
                if changed:
                    tt.save()
                return tt

            # No ThreadTracking for this thread_id exists
            # For prescreen/interview messages, check if company already has a ThreadTracking
            # and update that one instead of creating a duplicate
            if (
                message.ml_label in ("prescreen", "interview_invite")
                and message.company
            ):
                # Look for existing ThreadTracking for this company
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
