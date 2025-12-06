"""Restore noise labels for user-sent messages incorrectly labeled as 'other'.

This script identifies user-sent messages that were incorrectly forced to 'other'
when they should be 'noise' (personal conversations, spam, etc.), and re-ingests
them to apply the correct ML noise classification.
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message
from gmail_auth import get_gmail_service
from parser import ingest_message

def restore_noise_labels():
    """Find and restore noise labels for user-sent messages."""
    user_email = os.environ.get("USER_EMAIL_ADDRESS", "").strip().lower()
    if not user_email:
        print("❌ USER_EMAIL_ADDRESS not set in environment")
        return
    
    print(f"🔍 Finding user-sent messages labeled as 'other' with high confidence...")
    
    # Find user-sent messages with label='other' and confidence=1.0
    # These are likely user-initiated messages that might be personal/noise
    user_messages = Message.objects.filter(
        sender__icontains=user_email,
        ml_label='other',
        confidence=1.0
    ).order_by('-timestamp')
    
    print(f"📊 Found {user_messages.count()} user-sent 'other' messages")
    
    # Filter to potential noise: look for personal keywords in subject
    noise_indicators = [
        'unsubscribe',
        'refinance',
        'mortgage',
        'modem',
        'router',
        'wifi',
        'internet',
        'cable',
        'phone bill',
        'utility',
        'insurance',
        'warranty',
        're: re:',  # deeply nested personal threads
    ]
    
    candidates = []
    for msg in user_messages:
        subject_lower = (msg.subject or "").lower()
        # Check if subject contains personal/noise indicators
        if any(indicator in subject_lower for indicator in noise_indicators):
            candidates.append(msg)
        # Or if subject starts with "unsubscribe" (Gmail auto-generated)
        elif subject_lower.strip() == "unsubscribe":
            candidates.append(msg)
    
    print(f"🎯 Found {len(candidates)} candidates with noise indicators")
    
    if not candidates:
        print("✅ No noise candidates found - all user 'other' labels appear valid")
        return
    
    # Show sample for user review
    print("\n📝 Sample candidates:")
    for msg in candidates[:10]:
        print(f"  - {msg.subject[:60]} | {msg.timestamp.strftime('%Y-%m-%d')}")
    
    proceed = input(f"\n⚠️  Proceed with re-ingesting {len(candidates)} messages? (yes/no): ")
    if proceed.lower() not in ('yes', 'y'):
        print("❌ Aborted by user")
        return
    
    # Get Gmail service
    service = get_gmail_service()
    if not service:
        print("❌ Failed to initialize Gmail service")
        return
    
    print(f"\n🔄 Re-ingesting {len(candidates)} messages...")
    restored = 0
    skipped = 0
    errors = 0
    
    for i, msg in enumerate(candidates, 1):
        try:
            # Re-ingest the message - parser.py will now check ML classification
            ingest_message(service, msg.msg_id)
            
            # Refresh from DB to see new label
            msg.refresh_from_db()
            
            if msg.ml_label == 'noise':
                restored += 1
                print(f"✅ [{i}/{len(candidates)}] Restored: {msg.subject[:50]} -> Label: {msg.ml_label}")
            else:
                skipped += 1
                print(f"⏭️  [{i}/{len(candidates)}] Kept: {msg.subject[:50]} -> Label: {msg.ml_label}")
        
        except Exception as e:
            errors += 1
            print(f"❌ [{i}/{len(candidates)}] Error for {msg.msg_id}: {e}")
    
    print(f"\n📊 Restoration Summary:")
    print(f"   Total processed: {len(candidates)}")
    print(f"   ✅ Restored to noise: {restored}")
    print(f"   ⏭️  Kept as other: {skipped}")
    print(f"   ❌ Errors: {errors}")

if __name__ == "__main__":
    restore_noise_labels()
