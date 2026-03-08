
import os
import django
import sys

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from tracker.models import Company, ThreadTracking

# Get the companies
try:
    red_river = Company.objects.get(name="Red River")
    old_company = Company.objects.get(name="the Senior Cyber Engineer opportunity")
except Company.DoesNotExist:
    print("Could not find companies.")
    sys.exit(1)

# Get the thread
try:
    thread = ThreadTracking.objects.get(id=291)
    print(f"Before: Thread {thread.id} linked to {thread.company.name}")
    
    # Update the company
    thread.company = red_river
    thread.save()
    
    print(f"After: Thread {thread.id} linked to {thread.company.name}")
    
except ThreadTracking.DoesNotExist:
    print("Thread not found.")

# We could also delete the bogus company if it has no other messages/threads
if old_company.message_set.count() == 0 and old_company.threadtracking_set.count() == 0:
    print(f"Deleting unused company: {old_company.name}")
    old_company.delete()
else:
    print(f"Company {old_company.name} still has {old_company.message_set.count()} messages and {old_company.threadtracking_set.count()} threads.")
