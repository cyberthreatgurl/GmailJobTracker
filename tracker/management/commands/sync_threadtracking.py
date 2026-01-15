"""
Management command to create missing ThreadTracking records for existing Messages.

This ensures all job_application and interview_invite messages have
corresponding ThreadTracking records for the Application Details feature.
"""

from django.core.management.base import BaseCommand
from tracker.models import Message, ThreadTracking, Company


class Command(BaseCommand):
    help = "Create missing ThreadTracking records for job_application messages (prescreens/interviews are dates within applications)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without making changes'
        )
        parser.add_argument(
            '--company-id',
            type=int,
            help='Only process messages for specific company ID'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        company_id = options.get('company_id')

        # Find all job application messages
        # Note: prescreens and interviews should update existing applications via prescreen_date/interview_date
        # They should NOT create separate ThreadTracking records
        messages_qs = Message.objects.filter(
            ml_label='job_application'
        ).select_related('company')

        if company_id:
            messages_qs = messages_qs.filter(company_id=company_id)

        messages = messages_qs.order_by('timestamp')
        total_messages = messages.count()

        if total_messages == 0:
            self.stdout.write(self.style.WARNING('No job_application messages found'))
            return

        self.stdout.write(f'Found {total_messages} job application messages')

        created_count = 0
        skipped_count = 0
        errors = []

        for msg in messages:
            # Check if ThreadTracking already exists
            thread_exists = ThreadTracking.objects.filter(thread_id=msg.thread_id).exists()

            if thread_exists:
                skipped_count += 1
                continue

            # Create ThreadTracking record
            if not dry_run:
                try:
                    ThreadTracking.objects.create(
                        thread_id=msg.thread_id,
                        company=msg.company,
                        company_source=msg.company_source or '',
                        job_title=msg.subject[:255] if msg.subject else '',
                        job_id='',
                        status=msg.ml_label,
                        sent_date=msg.timestamp.date(),
                        ml_label=msg.ml_label,
                        ml_confidence=msg.confidence or 0.0,
                        reviewed=msg.reviewed
                    )
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ Created ThreadTracking for {msg.company.name} - {msg.timestamp.date()} - {msg.subject[:50]}'
                        )
                    )
                except Exception as e:
                    errors.append(f'Error for thread {msg.thread_id}: {e}')
                    self.stdout.write(self.style.ERROR(f'✗ Error: {e}'))
            else:
                created_count += 1
                self.stdout.write(
                    f'[DRY RUN] Would create ThreadTracking for {msg.company.name} - {msg.timestamp.date()} - {msg.subject[:50]}'
                )

        # Summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write(f'Total messages processed: {total_messages}')
        self.stdout.write(f'ThreadTracking created: {created_count}')
        self.stdout.write(f'Already existed (skipped): {skipped_count}')

        if errors:
            self.stdout.write(self.style.ERROR(f'Errors: {len(errors)}'))
            for error in errors:
                self.stdout.write(self.style.ERROR(f'  - {error}'))

        if dry_run:
            self.stdout.write(self.style.WARNING('\n⚠️  This was a dry run. No changes were made.'))
            self.stdout.write(self.style.WARNING('Run without --dry-run to create records.'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✅ Sync complete!'))
