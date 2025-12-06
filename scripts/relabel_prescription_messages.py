#!/usr/bin/env python
"""
Relabel prescription messages that are currently mislabeled in the database.
"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message
from django.db.models import Q
from ml_subject_classifier import predict_subject_type

print("=" * 80)
print("RELABELING PRESCRIPTION MESSAGES")
print("=" * 80)

# Find messages with "prescription" that aren't labeled as noise
prescription_messages = Message.objects.filter(
    Q(subject__icontains="prescription") | Q(body__icontains="prescription")
).exclude(ml_label='noise').order_by('-timestamp')

print(f"\nFound {prescription_messages.count()} prescription messages NOT labeled as 'noise':\n")

fixes = []

for msg in prescription_messages:
    # Test what the label SHOULD be with current rules
    result = predict_subject_type(msg.subject or "", msg.body or "", threshold=0.55, sender=msg.sender or "")
    should_be = result['label']
    
    print(f"ID: {msg.id} | Current: {msg.ml_label or 'UNLABELED'} | Should be: {should_be}")
    print(f"  {msg.timestamp.strftime('%Y-%m-%d %H:%M')} | {msg.sender}")
    print(f"  Subject: {msg.subject[:60]}...")
    print(f"  Method: {result.get('method', 'unknown')}, Confidence: {result['confidence']:.3f}")
    
    if should_be != msg.ml_label:
        fixes.append({
            'msg': msg,
            'old': msg.ml_label or 'UNLABELED',
            'new': should_be,
            'method': result.get('method', 'unknown')
        })
    print()

if fixes:
    print("=" * 80)
    print(f"PROPOSED FIXES: {len(fixes)} messages")
    print("=" * 80)
    
    for fix in fixes:
        print(f"\n• ID {fix['msg'].id}: {fix['old']} → {fix['new']}")
        print(f"  {fix['msg'].subject[:50]}...")
        print(f"  Detection: {fix['method']}")
    
    print("\n" + "=" * 80)
    response = input("\nApply these fixes? (y/n): ").strip().lower()
    
    if response == 'y':
        for fix in fixes:
            msg = fix['msg']
            msg.ml_label = fix['new']
            msg.reviewed = True  # Mark as reviewed
            msg.save()
            print(f"✓ Fixed ID {msg.id}: {fix['old']} → {fix['new']}")
        
        print(f"\n✅ Successfully relabeled {len(fixes)} messages!")
        print("\n📌 Next steps:")
        print("  1. Refresh /label_messages/ to see updated labels")
        print("  2. Retrain model with correct labels: python train_model.py --verbose")
    else:
        print("\n❌ No changes made.")
else:
    print("=" * 80)
    print("✅ All prescription messages are correctly labeled!")
    print("=" * 80)
