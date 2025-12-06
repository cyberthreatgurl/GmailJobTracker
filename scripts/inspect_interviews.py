import os
import sys

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
import django
django.setup()

from tracker.models import Company, ThreadTracking, Message

TARGETS = [
    "Meta",
    "CVS Health",
]


def show_company(name):
    print("\n--- Company: %s ---" % name)
    try:
        comp = Company.objects.get(name__iexact=name)
    except Company.DoesNotExist:
        print("No Company record found (case-insensitive lookup).")
        # try contains
        comp_qs = Company.objects.filter(name__icontains=name)
        if comp_qs.exists():
            comp = comp_qs.first()
            print("Using first partial match:", comp.name)
        else:
            return

    # ThreadTracking interviews
    tt_qs = ThreadTracking.objects.filter(company=comp, interview_date__isnull=False)
    tt_count = tt_qs.count()
    print(f"ThreadTracking interview_count: {tt_count}")
    for tt in tt_qs[:10]:
        print(f"  TT: thread_id={tt.thread_id}, interview_date={tt.interview_date}, job_title={tt.job_title}, interview_completed={tt.interview_completed}")
        print(f"    sent_date={tt.sent_date}, rejection_date={tt.rejection_date}, ml_label={tt.ml_label}, ml_confidence={tt.ml_confidence}, status={tt.status}, company_source={tt.company_source}")
        # Print messages in this thread to inspect why interview_date was set
        msgs = Message.objects.filter(thread_id=tt.thread_id).order_by('timestamp')
        print(f"    Messages in thread ({msgs.count()}):")
        for m in msgs[:10]:
            subj = (m.subject or '').replace('\n',' ').strip()[:120]
            body_snip = (m.body or '').replace('\n',' ').strip()[:240]
            print(f"      {m.timestamp} | {m.sender} | {m.ml_label} | subject={subj}")
            print(f"        body_snippet={body_snip}")

    # Messages labeled interview_invite or interview
    msg_qs = Message.objects.filter(company=comp, ml_label__in=['interview_invite','interview']).order_by('-timestamp')
    msg_count = msg_qs.count()
    print(f"Message-based interview labels count: {msg_count}")
    for m in msg_qs[:15]:
        subj = (m.subject or '').replace('\n',' ').strip()[:140]
        print(f"  MSG: id={m.msg_id}, thread_id={m.thread_id}, ts={m.timestamp}, ml_label={m.ml_label}, sender={m.sender}, subject={subj}")


if __name__ == '__main__':
    for t in TARGETS:
        show_company(t)
    print('\nDone.')
