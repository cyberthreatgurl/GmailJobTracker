import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from tracker.models import ThreadTracking, Message, Company

c = Company.objects.filter(name__icontains='Endyna').first()
print(f'Company: {c.name} (ID: {c.id})')

print('\n=== ALL sources contributing to dashboard count ===')

# 1. ThreadTracking with interview_date
print('\n1. ThreadTracking with interview_date:')
tt_interviews = ThreadTracking.objects.filter(
    interview_date__isnull=False,
    company=c
).order_by('interview_date')

interview_list = []
for t in tt_interviews:
    msg = Message.objects.filter(thread_id=t.thread_id, company=c).first()
    subject = msg.subject if msg else "(no message found)"
    print(f'  {t.interview_date} - Thread {t.thread_id[:16]} - {subject[:60]}')
    interview_list.append({
        'date': t.interview_date,
        'source': 'ThreadTracking',
        'thread_id': t.thread_id,
        'subject': subject
    })

print(f'\nThreadTracking count: {len(interview_list)}')

# 2. Get tracked (thread_id, company_id) combinations
tt_with_interview = ThreadTracking.objects.filter(
    interview_date__isnull=False,
    company__isnull=False
).values('thread_id', 'company_id')
tracked_thread_companies = {(item['thread_id'], item['company_id']) for item in tt_with_interview}

# 3. Interview_invite messages NOT in tracked threads
print('\n2. Interview_invite messages (not already in ThreadTracking):')
msg_interviews = Message.objects.filter(
    ml_label="interview_invite",
    company=c
).order_by('timestamp')

added_messages = []
for msg in msg_interviews:
    is_tracked = (msg.thread_id, msg.company_id) in tracked_thread_companies
    if not is_tracked:
        print(f'  {msg.timestamp.date()} - Thread {msg.thread_id[:16]} - {msg.subject[:60]}')
        interview_list.append({
            'date': msg.timestamp.date(),
            'source': 'Message',
            'thread_id': msg.thread_id,
            'subject': msg.subject
        })
        added_messages.append(msg)

print(f'\nMessages added: {len(added_messages)}')

print(f'\n=== TOTAL DASHBOARD COUNT: {len(interview_list)} ===')
print('\nAll entries:')
for item in sorted(interview_list, key=lambda x: x['date']):
    print(f'  {item["date"]} - {item["source"]:15} - {item["subject"][:70]}')

# Show which messages ARE tracked (skipped)
print('\n=== Interview_invite messages SKIPPED (already in ThreadTracking): ===')
for msg in msg_interviews:
    is_tracked = (msg.thread_id, msg.company_id) in tracked_thread_companies
    if is_tracked:
        print(f'  {msg.timestamp.date()} - Thread {msg.thread_id[:16]} - {msg.subject[:60]}')
