import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
django.setup()

from tracker.models import ThreadTracking, Message, Company

c = Company.objects.filter(name__icontains='Endyna').first()

print('=== Thread 0455 Messages (the one causing 4th count) ===')
msgs = Message.objects.filter(thread_id='19a697805f150455', company=c).order_by('timestamp')
print(f'Total messages in thread for Endyna: {msgs.count()}\n')

for m in msgs:
    print(f'Timestamp: {m.timestamp}')
    print(f'Subject: {m.subject}')
    print(f'ML Label: {m.ml_label}')
    print(f'Sender: {m.sender}')
    print(f'Body snippet: {m.body[:200]}')
    print('-' * 80)

print('\n=== Check if there is a ThreadTracking for thread 0455 ===')
tt = ThreadTracking.objects.filter(thread_id='19a697805f150455').first()
if tt:
    print(f'ThreadTracking exists!')
    print(f'  Company: {tt.company}')
    print(f'  interview_date: {tt.interview_date}')
    print(f'  sent_date: {tt.sent_date}')
    print(f'  ml_label: {tt.ml_label}')
else:
    print('No ThreadTracking found')
