"""
Management command to clean up orphaned ThreadTracking records.

This command finds and fixes ThreadTracking records that have incorrect data:
- ThreadTracking with rejection_date but no rejection messages
- ThreadTracking with interview_date but no interview messages
- ThreadTracking with no associated messages (orphaned)
"""

from django.core.management.base import BaseCommand
from tracker.models import Message, ThreadTracking


class Command(BaseCommand):
    help = 'Clean up orphaned or inconsistent ThreadTracking records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Find all ThreadTracking records
        all_threads = ThreadTracking.objects.all()
        total = all_threads.count()
        
        orphaned = 0
        fixed_rejection = 0
        fixed_interview = 0
        fixed_label = 0
        
        self.stdout.write(f'Checking {total} ThreadTracking records...\n')
        
        for thread in all_threads:
            messages = Message.objects.filter(thread_id=thread.thread_id)
            message_count = messages.count()
            
            # Check for orphaned ThreadTracking (no messages)
            if message_count == 0:
                self.stdout.write(
                    self.style.WARNING(
                        f'Orphaned ThreadTracking {thread.thread_id} (company: {thread.company.name}) - no messages'
                    )
                )
                if not dry_run:
                    thread.delete()
                orphaned += 1
                continue
            
            # Check rejection_date consistency
            rejections = messages.filter(ml_label='rejection').order_by('-timestamp')
            if thread.rejection_date and not rejections.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f'ThreadTracking {thread.thread_id} has rejection_date but no rejection messages'
                    )
                )
                if not dry_run:
                    thread.rejection_date = None
                    thread.save()
                fixed_rejection += 1
            elif rejections.exists():
                latest_rejection = rejections.first()
                expected_date = latest_rejection.timestamp.date()
                if thread.rejection_date != expected_date:
                    self.stdout.write(
                        self.style.WARNING(
                            f'ThreadTracking {thread.thread_id} rejection_date mismatch: {thread.rejection_date} != {expected_date}'
                        )
                    )
                    if not dry_run:
                        thread.rejection_date = expected_date
                        thread.save()
                    fixed_rejection += 1
            
            # Check interview_date consistency
            interviews = messages.filter(ml_label='interview_invite').order_by('-timestamp')
            if thread.interview_date and not interviews.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f'ThreadTracking {thread.thread_id} has interview_date but no interview messages'
                    )
                )
                if not dry_run:
                    thread.interview_date = None
                    thread.save()
                fixed_interview += 1
            elif interviews.exists():
                latest_interview = interviews.first()
                expected_date = latest_interview.timestamp.date()
                if thread.interview_date != expected_date:
                    self.stdout.write(
                        self.style.WARNING(
                            f'ThreadTracking {thread.thread_id} interview_date mismatch: {thread.interview_date} != {expected_date}'
                        )
                    )
                    if not dry_run:
                        thread.interview_date = expected_date
                        thread.save()
                    fixed_interview += 1
            
            # Check ml_label consistency - should match most recent message
            latest_message = messages.order_by('-timestamp').first()
            if latest_message and thread.ml_label != latest_message.ml_label:
                self.stdout.write(
                    self.style.WARNING(
                        f'ThreadTracking {thread.thread_id} ml_label mismatch: {thread.ml_label} != {latest_message.ml_label}'
                    )
                )
                if not dry_run:
                    thread.ml_label = latest_message.ml_label
                    thread.ml_confidence = latest_message.confidence
                    thread.save()
                fixed_label += 1
        
        # Summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('CLEANUP SUMMARY'))
        self.stdout.write('='*60)
        self.stdout.write(f'Total ThreadTracking records checked: {total}')
        self.stdout.write(f'Orphaned records {"(would be) " if dry_run else ""}deleted: {orphaned}')
        self.stdout.write(f'Rejection dates {"(would be) " if dry_run else ""}fixed: {fixed_rejection}')
        self.stdout.write(f'Interview dates {"(would be) " if dry_run else ""}fixed: {fixed_interview}')
        self.stdout.write(f'ML labels {"(would be) " if dry_run else ""}fixed: {fixed_label}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nRun without --dry-run to apply changes'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ Cleanup complete'))
