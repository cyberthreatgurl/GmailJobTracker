from typing import Optional

from .models import Message
from .utils import propagate_message_label_to_thread


def label_message_and_propagate(msg: Message, label: str, confidence: Optional[float] = None) -> None:
    """Set a Message's ml_label and confidence, save, and propagate to ThreadTracking."""
    if not msg:
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
