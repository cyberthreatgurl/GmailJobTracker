from typing import Optional
from django.db import transaction

from .models import Message, ThreadTracking


def propagate_message_label_to_thread(message: Message) -> Optional[ThreadTracking]:
    """Ensure a Message's ml_label is reflected on its ThreadTracking.

    - If a ThreadTracking exists for the message.thread_id, update its ml_label and ml_confidence.
    - If none exists and the message label indicates an application/interview and the message has a company,
      create a minimal ThreadTracking record.

    Returns the ThreadTracking instance (created or updated), or None if nothing was done.
    """
    if not message or not getattr(message, "thread_id", None):
        return None

    thread_id = message.thread_id
    try:
        with transaction.atomic():
            tt = ThreadTracking.objects.filter(thread_id=thread_id).first()
            if tt:
                changed = False
                if message.ml_label and tt.ml_label != message.ml_label:
                    tt.ml_label = message.ml_label
                    changed = True
                if message.confidence is not None and (
                    tt.ml_confidence is None or tt.ml_confidence != message.confidence
                ):
                    tt.ml_confidence = message.confidence
                    changed = True
                if changed:
                    tt.save()
                return tt

            # No ThreadTracking exists; create when appropriate
            if (
                message.ml_label in ("job_application", "interview_invite")
                and message.company
            ):
                tt = ThreadTracking.objects.create(
                    thread_id=thread_id,
                    company=message.company,
                    company_source=message.company_source or "manual",
                    job_title="",
                    job_id="",
                    status="application",
                    sent_date=(message.timestamp.date() if message.timestamp else None),
                    ml_label=message.ml_label,
                    ml_confidence=(message.confidence or 0.0),
                )
                return tt
    except Exception:
        # Don't propagate exceptions — callers should handle/log if needed.
        return None

    return None
