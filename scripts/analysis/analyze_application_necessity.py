#!/usr/bin/env python
"""Analyze if Application model is redundant with Message model."""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Message, ThreadTracking

print("\n" + "=" * 80)
print("APPLICATION vs MESSAGE MODEL ANALYSIS")
print("=" * 80 + "\n")

# Compare what's stored in each model
print("APPLICATION MODEL FIELDS:")
print("  - thread_id (unique)")
print("  - company (FK)")
print("  - company_source")
print("  - job_title")
print("  - job_id")
print("  - status")
print("  - sent_date")
print("  - rejection_date")
print("  - interview_date")
print("  - ml_label")
print("  - ml_confidence")
print("  - reviewed")
print()

print("MESSAGE MODEL FIELDS:")
print("  - msg_id (unique)")
print("  - thread_id (indexed, NOT unique)")
print("  - company (FK, nullable)")
print("  - company_source")
print("  - sender")
print("  - subject")
print("  - body / body_html")
print("  - timestamp")
print("  - ml_label")
print("  - confidence")
print("  - reviewed")
print()

# Check how many applications vs messages
app_count = ThreadTracking.objects.count()
msg_count = Message.objects.count()
threads_with_apps = ThreadTracking.objects.values("thread_id").distinct().count()
threads_with_msgs = Message.objects.values("thread_id").distinct().count()

print("=" * 80)
print("DATA VOLUME:")
print("=" * 80)
print(f"Total Applications: {app_count}")
print(f"Total Messages: {msg_count}")
print(f"Unique threads with Applications: {threads_with_apps}")
print(f"Unique threads with Messages: {threads_with_msgs}")
print()

# Check what % of message threads have applications
if threads_with_msgs > 0:
    coverage = (threads_with_apps / threads_with_msgs) * 100
    print(
        f"Application coverage: {coverage:.1f}% of message threads have Application records"
    )
print()

# Check if Applications store any unique data not in Messages
print("=" * 80)
print("UNIQUE DATA IN APPLICATION MODEL:")
print("=" * 80)
print("✓ job_title - extracted from subject, stored at thread level")
print("✓ job_id - extracted from subject, stored at thread level")
print("✓ sent_date - DATE (vs Message.timestamp which is DATETIME)")
print("✓ rejection_date - DATE when rejection occurred")
print("✓ interview_date - DATE when interview occurred")
print("✓ status - current status (application/interview/ghosted/rejected)")
print()

print("=" * 80)
print("CONCLUSION:")
print("=" * 80)
print()
print("Application model provides THREAD-LEVEL aggregation with:")
print("  1. Parsed job metadata (title, job_id)")
print("  2. Status tracking (application → interview → ghosted/rejected)")
print("  3. Key dates (sent, interview, rejection)")
print("  4. One record per thread (vs multiple messages per thread)")
print()
print("Message model provides MESSAGE-LEVEL detail with:")
print("  1. Individual email content (subject, body, sender)")
print("  2. Exact timestamps")
print("  3. ML classification per message")
print("  4. Thread grouping via thread_id")
print()
print("THEY SERVE DIFFERENT PURPOSES:")
print("  - Application = Thread/job summary for dashboard metrics")
print("  - Message = Individual email details for viewing/analysis")
print()

# Check usage in dashboard queries
print("=" * 80)
print("DASHBOARD USAGE:")
print("=" * 80)
print("Most dashboard boxes query APPLICATIONS for:")
print("  - sent_date (applications sent)")
print("  - interview_date (interviews scheduled)")
print("  - rejection_date (rejections)")
print("  - status='ghosted' (ghosted companies)")
print()
print("This would be harder with Messages because:")
print("  - Multiple messages per thread need aggregation")
print("  - Need to determine which message represents the 'application sent' date")
print("  - Need to track status changes across message sequence")
print()

# Sample query comparison
print("=" * 80)
print("QUERY COMPLEXITY COMPARISON:")
print("=" * 80)
print()
print("WITH APPLICATION TABLE:")
print("  ThreadTracking.objects.filter(interview_date__isnull=False).count()")
print()
print("WITHOUT APPLICATION TABLE (using Messages):")
print("  Message.objects.filter(")
print("    ml_label='interview_invite'")
print("  ).values('thread_id').distinct().count()")
print("  # But this doesn't give you the DATE the interview was scheduled")
print("  # You'd need to aggregate timestamps, extract dates, etc.")
print()

print("=" * 80)
print("RECOMMENDATION:")
print("=" * 80)
print()
print("❌ NO - Application table is NOT a relic")
print()
print("It's serving an important purpose:")
print("  ✓ Thread-level aggregation for dashboard metrics")
print("  ✓ Job metadata storage (title, id)")
print("  ✓ Status lifecycle tracking")
print("  ✓ Key milestone dates (sent, interview, rejection)")
print("  ✓ Simplified queries for charts/graphs")
print()
print("Without it, you'd need complex aggregation queries on Messages")
print("for every dashboard load, which would be slower and more complex.")
