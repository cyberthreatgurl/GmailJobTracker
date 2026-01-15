"""Fix ThreadTracking records created by .eml upload that have null ml_label."""

from django.core.management.base import BaseCommand
from tracker.models import Message, ThreadTracking


class Command(BaseCommand):
    help = "Fix ThreadTracking records with null ml_label by copying from corresponding Message"

    def handle(self, *args, **options):
        # Find ThreadTracking records with null ml_label
        broken_tt = ThreadTracking.objects.filter(ml_label__isnull=True)
        
        count = broken_tt.count()
        self.stdout.write(f"Found {count} ThreadTracking records with null ml_label")
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS("✅ No records to fix"))
            return
        
        fixed = 0
        for tt in broken_tt:
            # Find corresponding message
            msg = Message.objects.filter(thread_id=tt.thread_id, company=tt.company).first()
            if msg and msg.ml_label:
                self.stdout.write(f"  Fixing {tt.company.name} - thread {tt.thread_id[:16]}...")
                tt.ml_label = msg.ml_label
                tt.ml_confidence = msg.confidence
                tt.save()
                fixed += 1
            else:
                self.stdout.write(f"  ⚠️  No message found for {tt.company.name if tt.company else 'Unknown'}")
        
        self.stdout.write(self.style.SUCCESS(f"✅ Fixed {fixed} ThreadTracking records"))
