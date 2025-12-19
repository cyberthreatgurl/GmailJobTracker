"""Reclassify meeting/calendar invites that were mislabeled as interview_invite.

Finds messages with:
- Label: interview_invite
- Subject: contains "meeting with", "meeting invitation", etc. (without "interview")
- Body: contains Teams/Zoom meeting markers

Reclassifies to "other" and removes ThreadTracking entries (meetings != interviews).
"""

import os
import re
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking


def main():
    """Find and reclassify meeting invites mislabeled as interview_invite."""
    # Find messages labeled as interview_invite that look like meeting invites
    meeting_patterns = Message.objects.filter(ml_label="interview_invite").filter(
        subject__iregex=r"(meeting with|meeting invitation|teams meeting)"
    )

    body_patterns = (
        Message.objects.filter(ml_label="interview_invite")
        .filter(body__iregex=r"(microsoft teams|zoom meeting|join.*meeting)")
        .exclude(subject__icontains="interview")
    )

    # Combine querysets
    meetings = (meeting_patterns | body_patterns).distinct()

    count = meetings.count()
    print(f"Found {count} potential meeting invites mislabeled as interview_invite:")
    print()

    reclassified = []
    threads_deleted = []

    for msg in meetings:
        print(f"ID: {msg.msg_id}")
        print(f"Subject: {msg.subject[:80]}")
        print(f"Sender: {msg.sender}")
        print(f"Company: {msg.company}")
        print(f"ML Label: {msg.ml_label} (confidence: {msg.confidence})")
        print(f"Timestamp: {msg.timestamp}")

        # Check for calendar markers
        has_teams = bool(
            re.search(r"microsoft teams|meeting id:|passcode:", msg.body or "", re.I)
        )
        has_zoom = bool(re.search(r"zoom meeting|zoom.us/j/", msg.body or "", re.I))
        print(f"Has Teams markers: {has_teams}")
        print(f"Has Zoom markers: {has_zoom}")

        # Special case: RAND message is a real interview (contains "Candidate Screen")
        if "candidate screen" in msg.subject.lower():
            print("⚠️  SKIPPING: Contains 'Candidate Screen' - likely real interview")
            print("-" * 80)
            print()
            continue

        # Reclassify
        msg.ml_label = "other"
        msg.save()
        reclassified.append(msg.msg_id)
        print("✓ Reclassified to: other")

        # Remove ThreadTracking if exists (by thread_id, not message_id)
        # Note: ThreadTracking uses thread_id, not first_message_id
        # We need to find the thread from a related Message first
        try:
            # Get the thread_id from this message
            thread_id = msg.thread_id if hasattr(msg, "thread_id") else None
            if thread_id:
                threads = ThreadTracking.objects.filter(thread_id=thread_id)
                if threads.exists():
                    thread_count = threads.count()
                    threads.delete()
                    threads_deleted.append(msg.msg_id)
                    print(f"✓ Deleted {thread_count} ThreadTracking entry(ies)")
            else:
                print("  (No thread_id to check for ThreadTracking)")
        except Exception as e:
            print(f"  Warning: Could not delete ThreadTracking: {e}")

        print("-" * 80)
        print()

    print("\n" + "=" * 80)
    print(f"SUMMARY:")
    print(f"  Total examined: {count}")
    print(f"  Reclassified to 'other': {len(reclassified)}")
    print(f"  ThreadTracking entries deleted: {len(threads_deleted)}")
    print()
    print(f"Reclassified message IDs:")
    for msg_id in reclassified:
        print(f"  - {msg_id}")


if __name__ == "__main__":
    main()
