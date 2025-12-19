from typing import Optional

from .models import Message
from .utils import propagate_message_label_to_thread


def label_message_and_propagate(
    msg: Message,
    label: str,
    confidence: Optional[float] = None,
    overwrite_reviewed: bool = False,
) -> None:
    """Set a Message's ml_label and confidence, save, and propagate to ThreadTracking.

    By default this helper will NOT modify messages flagged `reviewed=True` unless
    `overwrite_reviewed=True` is passed by the caller. This prevents automated ML
    flows from silently overwriting manual reviews.
    """
    if not msg:
        return

    # Respect manual review protection unless caller explicitly requests overwrite
    if getattr(msg, "reviewed", False) and not overwrite_reviewed:
        return

    msg.ml_label = label
    if confidence is not None:
        msg.confidence = confidence
    # Respect Message.save behaviour (clearing company for reviewed noise messages)
    msg.save()
    try:
        propagate_message_label_to_thread(msg)
    except Exception:
        # Swallow exceptions to avoid breaking caller
        pass
