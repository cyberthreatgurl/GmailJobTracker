# mark_ghosted.py

from django.core.management.base import BaseCommand
from django.utils.timezone import now
from datetime import timedelta
from tracker.models import Message

class Command(BaseCommand):
    help = "Mark messages as ghosted if no follow-up received after X months"

    def handle(self, *args, **kwargs):
        cutoff = now() - timedelta(days=60)  # 2 months
        candidates = Message.objects.filter(
            ml_label__in=["job_application", "interview_invite"],
            timestamp__lte=cutoff,
            reviewed=True,
        ).exclude(company=None)

        ghosted_count = 0
        for msg in candidates:
            newer = Message.objects.filter(
                company=msg.company,
                timestamp__gt=msg.timestamp,
                reviewed=True
            ).exclude(ml_label="ghosted").exists()

            if not newer:
                msg.ml_label = "ghosted"
                msg.reviewed = True
                msg.save()
                ghosted_count += 1
                self.stdout.write(f"👻 Marked ghosted: {msg.subject} ({msg.company.name})")

        self.stdout.write(self.style.SUCCESS(f"✅ {ghosted_count} messages marked as ghosted."))