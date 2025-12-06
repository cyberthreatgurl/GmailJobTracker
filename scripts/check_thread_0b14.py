import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from tracker.models import Message, ThreadTracking

thread_id = '19a46c30ea5d0b14'

print(f'=== All messages in thread {thread_id} ===')
msgs = Message.objects.filter(thread_id=thread_id).order_by('timestamp')
print(f'Total messages: {msgs.count()}\n')

for msg in msgs:
    print(f'Date: {msg.timestamp}')
    print(f'Subject: {msg.subject}')
    print(f'ML Label: {msg.ml_label}')
    print(f'Company: {msg.company.name if msg.company else "None"}')
    print(f'Confidence: {msg.confidence:.2f}')
    print(f'Body snippet: {msg.body[:200]}...')
    print('-' * 80)

print(f'\n=== ThreadTracking for thread {thread_id} ===')
tt = ThreadTracking.objects.filter(thread_id=thread_id).first()
if tt:
    print(f'Company: {tt.company.name if tt.company else "None"}')
    print(f'interview_date: {tt.interview_date}')
    print(f'sent_date: {tt.sent_date}')
    print(f'ml_label: {tt.ml_label}')
else:
    print('No ThreadTracking found')
