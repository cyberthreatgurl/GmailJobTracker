"""
Management command to fix ThreadTracking sent_date fields that used UTC instead of local timezone.

When messages arrive after 7 PM EST (midnight UTC), they get stored with the next day's date
if using UTC. This command corrects those dates to match the local timezone (America/New_York).
"""

from django.core.management.base import BaseCommand
from django.db.models import Q
from tracker.models import ThreadTracking, Message
import pytz


class Command(BaseCommand):
    help = "Fix ThreadTracking sent_date fields that used UTC instead of EST timezone"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes'
        )
        parser.add_argument(
            '--company-id',
            type=int,
            help='Only process specific company ID'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        company_id = options.get('company_id')

        # Get all ThreadTracking records
        threads_qs = ThreadTracking.objects.all().select_related('company')
        
        if company_id:
            threads_qs = threads_qs.filter(company_id=company_id)

        total_threads = threads_qs.count()
        self.stdout.write(f'Scanning {total_threads} ThreadTracking records...\n')

        est = pytz.timezone('America/New_York')
        fixed_count = 0
        errors = []

        for thread in threads_qs.iterator(chunk_size=100):
            try:
                # Get the first message in this thread
                msg = Message.objects.filter(thread_id=thread.thread_id).order_by('timestamp').first()
                
                if not msg:
                    continue

                # Convert message timestamp to EST
                local_time = msg.timestamp.astimezone(est)
                local_date = local_time.date()

                # Check if ThreadTracking date differs from local date
                if thread.sent_date != local_date:
                    if not dry_run:
                        old_date = thread.sent_date
                        thread.sent_date = local_date
                        thread.save(update_fields=['sent_date'])
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'✓ {thread.company.name} - {thread.job_title[:40] or "(no title)"}'
                            )
                        )
                        self.stdout.write(
                            f'  Changed: {old_date} → {local_date} (UTC: {msg.timestamp})'
                        )
                    else:
                        self.stdout.write(
                            f'[DRY RUN] {thread.company.name} - {thread.job_title[:40] or "(no title)"}'
                        )
                        self.stdout.write(
                            f'  Would change: {thread.sent_date} → {local_date} (UTC: {msg.timestamp})'
                        )
                    
                    fixed_count += 1

            except Exception as e:
                error_msg = f'Error processing thread {thread.thread_id}: {e}'
                errors.append(error_msg)
                self.stdout.write(self.style.ERROR(f'✗ {error_msg}'))

        # Summary
        self.stdout.write('\n' + '='*70)
        self.stdout.write(f'Total ThreadTracking records scanned: {total_threads}')
        self.stdout.write(f'Date corrections needed: {fixed_count}')
        
        if errors:
            self.stdout.write(self.style.ERROR(f'Errors: {len(errors)}'))
            for error in errors[:10]:  # Show first 10 errors
                self.stdout.write(self.style.ERROR(f'  - {error}'))
            if len(errors) > 10:
                self.stdout.write(self.style.ERROR(f'  ... and {len(errors) - 10} more errors'))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n⚠️  This was a dry run. No changes were made.'))
            self.stdout.write(self.style.WARNING('Run without --dry-run to apply fixes.'))
        else:
            if fixed_count > 0:
                self.stdout.write(self.style.SUCCESS(f'\n✅ Fixed {fixed_count} date(s)!'))
            else:
                self.stdout.write(self.style.SUCCESS('\n✅ No corrections needed. All dates are correct.'))
