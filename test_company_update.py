
import os
import django
import sys

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, ThreadTracking, Message

def setup_test_state():
    # 1. Ensure Red River exists
    rr, _ = Company.objects.get_or_create(name="Red River")
    
    # 2. Create a dummy "Wrong Company"
    from django.utils.timezone import now
    wrong, _ = Company.objects.get_or_create(
        name="Wrong Company Inc",
        defaults={'first_contact': now(), 'last_contact': now()}
    )
    
    # 3. Get the message and force it to be "Wrong Company"
    try:
        msg = Message.objects.get(thread_id="19cce810b6523eb8")
        msg.company = wrong
        msg.save()
        print(f"Set Message {msg.id} company to {wrong.name}")
    except Message.DoesNotExist:
        print("Message not found! Cannot test.")
        return

    # 4. Get the thread and force it to be "Wrong Company"
    try:
        tt = ThreadTracking.objects.get(thread_id="19cce810b6523eb8")
        tt.company = wrong
        tt.save()
        print(f"Set ThreadTracking {tt.id} company to {wrong.name}")
    except ThreadTracking.DoesNotExist:
        # Create one if missing
        tt = ThreadTracking.objects.create(
            thread_id="19cce810b6523eb8",
            company=wrong,
            status="applied",
            sent_date="2026-01-01"
        )
        print(f"Created ThreadTracking {tt.id} for {wrong.name}")

def verify_fix():
    # Check if ThreadTracking is updated to Red River
    try:
        tt = ThreadTracking.objects.get(thread_id="19cce810b6523eb8")
        print(f"Final ThreadTracking Company: {tt.company.name}")
        if tt.company.name == "Red River":
            print("SUCCESS: ThreadTracking company updated correctly.")
        else:
            print("FAILURE: ThreadTracking company NOT updated.")
    except ThreadTracking.DoesNotExist:
        print("FAILURE: ThreadTracking missing.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        verify_fix()
    else:
        setup_test_state()
