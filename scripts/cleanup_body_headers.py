#!/usr/bin/env python
"""
Clean up RFC 5322 violation: Remove classification headers from message body field.

Headers like Return-Path, List-Unsubscribe, etc. were incorrectly prepended to
message bodies for classification purposes. This script removes them and 
recomputes body_hash with RFC 5322 compliant body content.

Usage:
    python scripts/cleanup_body_headers.py           # Dry run (show changes)
    python scripts/cleanup_body_headers.py --confirm # Apply changes
"""

import os
import sys
import re
import hashlib
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message


# Classification headers that were prepended to body
CLASSIFICATION_HEADERS = [
    "List-Id", "List-Unsubscribe", "Precedence",
    "X-Campaign", "X-Mailer", "X-Newsletter",
    "Auto-Submitted", "X-Auto-Response-Suppress",
    "Return-Path", "Reply-To", "Organization",
    "X-Entity-Ref-ID", "X-Sender"
]


def strip_prepended_headers(body):
    """
    Remove classification headers that were prepended to body text.
    
    Returns:
        tuple: (cleaned_body, headers_found, was_modified)
    """
    if not body:
        return body, [], False
    
    lines = body.split('\n')
    headers_found = []
    clean_body_start_idx = 0
    
    # Find where actual body starts (after header block)
    for i, line in enumerate(lines):
        # Check if line is a header
        is_header = False
        for header_name in CLASSIFICATION_HEADERS:
            if line.startswith(f"{header_name}:"):
                is_header = True
                headers_found.append(line)
                break
        
        if is_header:
            clean_body_start_idx = i + 1
        elif line.strip() == "" and headers_found:
            # Empty line after headers - body starts next line
            clean_body_start_idx = i + 1
            break
        elif not is_header and headers_found:
            # Non-header, non-empty line after headers - body starts here
            clean_body_start_idx = i
            break
    
    if not headers_found:
        return body, [], False
    
    # Extract clean body (everything after headers)
    clean_body = '\n'.join(lines[clean_body_start_idx:])
    return clean_body, headers_found, True


def compute_body_hash(body):
    """Compute SHA256 hash of normalized body."""
    if not body:
        return ""
    normalized = re.sub(r'\s+', ' ', body).strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Clean up message bodies by removing prepended classification headers"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually update the database (default is dry run)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of records to process in each batch (default: 100)"
    )
    args = parser.parse_args()

    # Find messages with classification headers in body
    messages_with_headers = Message.objects.filter(
        body__regex=r'^(Return-Path|List-Id|List-Unsubscribe|X-Mailer|Reply-To|Organization):'
    )
    total_count = messages_with_headers.count()

    if total_count == 0:
        print("✅ No messages have classification headers in body field.")
        print("   All message bodies are RFC 5322 compliant.")
        return

    print(f"📊 Found {total_count} messages with headers in body field")
    
    if not args.confirm:
        print("🔍 DRY RUN MODE - no changes will be made")
        print("   Run with --confirm to apply changes")
    else:
        print("✍️  UPDATING DATABASE")
    
    print()

    # Process in batches
    updated_count = 0
    skipped_count = 0
    batch_num = 0
    
    # Show a few examples first
    if not args.confirm:
        print("Examples of messages to be cleaned:")
        print("=" * 80)
        
        for msg in messages_with_headers[:3]:
            clean_body, headers, was_modified = strip_prepended_headers(msg.body)
            
            if was_modified:
                print(f"\n📧 Message ID: {msg.id}")
                print(f"   Subject: {msg.subject[:60]}")
                print(f"   Headers found: {len(headers)}")
                for h in headers[:3]:
                    print(f"     - {h[:70]}")
                if len(headers) > 3:
                    print(f"     ... and {len(headers) - 3} more")
                
                old_hash = msg.body_hash
                new_hash = compute_body_hash(clean_body)
                
                print(f"   Old body_hash: {old_hash[:16]}...")
                print(f"   New body_hash: {new_hash[:16]}...")
                print(f"   Body length: {len(msg.body)} → {len(clean_body)} chars")
        
        print()
        print("=" * 80)
        print(f"\n🔍 Would clean {total_count} messages")
        print("   Run with --confirm to apply changes")
        return
    
    # Actual processing with --confirm
    while True:
        # Get next batch
        batch = list(messages_with_headers[:args.batch_size])
        if not batch:
            break
        
        batch_num += 1
        print(f"Processing batch {batch_num} ({len(batch)} messages)...", end=" ", flush=True)
        
        batch_updated = 0
        batch_skipped = 0
        
        for msg in batch:
            clean_body, headers, was_modified = strip_prepended_headers(msg.body)
            
            if was_modified:
                # Update body and recompute hash
                msg.body = clean_body
                msg.body_hash = compute_body_hash(clean_body)
                msg.save(update_fields=['body', 'body_hash'])
                batch_updated += 1
            else:
                batch_skipped += 1
        
        updated_count += batch_updated
        skipped_count += batch_skipped
        
        print(f"✅ Updated: {batch_updated}, Skipped: {batch_skipped}")
    
    print()
    print(f"✅ Successfully cleaned {updated_count} messages")
    print(f"   Skipped {skipped_count} messages (no modifications needed)")
    print()
    print("🎉 All message bodies are now RFC 5322 compliant!")


if __name__ == "__main__":
    main()
