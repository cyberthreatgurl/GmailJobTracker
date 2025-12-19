"""Message Service: Business logic for message operations.

This service handles:
- Bulk message labeling and updates
- Message re-ingestion and reprocessing
- Message classification and ML model operations
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

from django.db import transaction
from tracker.models import Company, Message, ThreadTracking

logger = logging.getLogger(__name__)


class MessageService:
    """Service class for message-related business logic."""

    @staticmethod
    def bulk_label_messages(
        message_ids: List[int],
        label: str,
        confidence: float = 1.0,
        overwrite_reviewed: bool = True
    ) -> Tuple[int, Set[str]]:
        """Bulk update label for multiple messages.
        
        Args:
            message_ids: List of message IDs to update
            label: New label to apply
            confidence: Confidence score for the label
            overwrite_reviewed: Whether to overwrite reviewed flags
            
        Returns:
            Tuple of (updated_count, touched_thread_ids)
        """
        from tracker.label_helpers import label_message_and_propagate
        
        updated_count = 0
        touched_threads = set()
        
        for msg_id in message_ids:
            try:
                msg = Message.objects.get(pk=msg_id)
                label_message_and_propagate(
                    msg, 
                    label, 
                    confidence=confidence, 
                    overwrite_reviewed=overwrite_reviewed
                )
                if msg.thread_id:
                    touched_threads.add(msg.thread_id)
                updated_count += 1
            except Message.DoesNotExist:
                logger.warning(f"Message {msg_id} not found during bulk label")
                continue
            except Exception as e:
                logger.error(f"Error labeling message {msg_id}: {e}")
                continue
                
        return updated_count, touched_threads

    @staticmethod
    def update_company_registry(
        company_name: Optional[str] = None,
        company_domain: Optional[str] = None,
        ats_domain: Optional[str] = None,
        careers_url: Optional[str] = None
    ) -> Tuple[List[str], List[str], Optional[str]]:
        """Update the company registry (companies.json) with new entries.
        
        Args:
            company_name: Company name to add to known list
            company_domain: Domain to map to company
            ats_domain: ATS domain to add
            careers_url: Careers page URL to add
            
        Returns:
            Tuple of (added_entries, updated_entries, error_message)
        """
        # Strip and validate inputs
        company_name = (company_name or "").strip()
        company_domain = (company_domain or "").strip()
        ats_domain = (ats_domain or "").strip()
        careers_url = (careers_url or "").strip()
        
        if not any([company_name, company_domain, ats_domain, careers_url]):
            return [], [], "Please provide at least one field to add/update."
        
        cfg_path = Path("json/companies.json")
        
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                companies_cfg = json.load(f)
        except Exception as e:
            return [], [], f"Failed to read companies.json: {e}"
        
        added = []
        updated = []
        
        # Ensure top-level keys exist
        companies_cfg.setdefault("known", [])
        companies_cfg.setdefault("domain_to_company", {})
        companies_cfg.setdefault("ats_domains", [])
        companies_cfg.setdefault("JobSites", {})
        
        # Add company name to known list
        if company_name:
            if company_name not in companies_cfg["known"]:
                companies_cfg["known"].append(company_name)
                added.append(f"known: {company_name}")
        
        # Map company domain to company name
        if company_domain:
            domain_key = company_domain.lower()
            existing = companies_cfg["domain_to_company"].get(domain_key)
            if not existing:
                companies_cfg["domain_to_company"][domain_key] = company_name or existing or ""
                added.append(
                    f"domain_to_company: {domain_key} → "
                    f"{companies_cfg['domain_to_company'][domain_key]}"
                )
            elif company_name and existing != company_name:
                companies_cfg["domain_to_company"][domain_key] = company_name
                updated.append(f"domain_to_company: {domain_key} → {company_name}")
        
        # Add ATS domain
        if ats_domain:
            ats_key = ats_domain.lower()
            if ats_key not in companies_cfg["ats_domains"]:
                companies_cfg["ats_domains"].append(ats_key)
                added.append(f"ats_domains: {ats_key}")
        
        # Add or update careers URL under JobSites
        if careers_url and company_name:
            existing_url = companies_cfg["JobSites"].get(company_name)
            if not existing_url:
                companies_cfg["JobSites"][company_name] = careers_url
                added.append(f"JobSites: {company_name}")
            elif existing_url != careers_url:
                companies_cfg["JobSites"][company_name] = careers_url
                updated.append(f"JobSites: {company_name}")
        
        # Persist changes if any
        try:
            if added or updated:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(companies_cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return added, updated, f"Failed to write companies.json: {e}"
        
        return added, updated, None

    @staticmethod
    def get_messages_for_labeling(
        company_filter: Optional[str] = None,
        label_filter: Optional[str] = None,
        show_reviewed: bool = False,
        search_query: Optional[str] = None,
        page_size: int = 50,
        page: int = 1
    ):
        """Get filtered and paginated messages for labeling interface.
        
        Args:
            company_filter: Filter by company name
            label_filter: Filter by message label
            show_reviewed: Whether to include reviewed messages
            search_query: Text search in subject/body
            page_size: Number of results per page
            page: Page number (1-indexed)
            
        Returns:
            QuerySet of Message objects
        """
        qs = Message.objects.select_related('company').all()
        
        # Apply filters
        if company_filter and company_filter != 'all':
            qs = qs.filter(company__name=company_filter)
        
        if label_filter and label_filter != 'all':
            qs = qs.filter(ml_label=label_filter)
        
        if not show_reviewed:
            qs = qs.filter(reviewed=False)
        
        if search_query:
            from django.db.models import Q
            qs = qs.filter(
                Q(subject__icontains=search_query) |
                Q(body__icontains=search_query) |
                Q(sender__icontains=search_query)
            )
        
        # Order by timestamp descending
        qs = qs.order_by('-timestamp')
        
        # Pagination
        start = (page - 1) * page_size
        end = start + page_size
        
        return qs[start:end]

    @staticmethod
    @transaction.atomic
    def reingest_message(message_id: int) -> Tuple[bool, Optional[str]]:
        """Re-ingest and reclassify a single message.
        
        Args:
            message_id: ID of message to reingest
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            from parser import parse_subject
            
            msg = Message.objects.get(pk=message_id)
            
            # Re-parse the message
            result = parse_subject(
                subject=msg.subject,
                sender=msg.sender,
                body=msg.body,
                metadata={}
            )
            
            # Update message with new classification
            msg.ml_label = result.get('label', 'other')
            msg.confidence = result.get('confidence', 0.0)
            
            # Update company if extraction found a new one
            new_company_name = result.get('company')
            if new_company_name:
                from django.utils.timezone import now
                company, _ = Company.objects.get_or_create(
                    name=new_company_name,
                    defaults={
                        "first_contact": msg.timestamp if msg.timestamp else now(),
                        "last_contact": msg.timestamp if msg.timestamp else now(),
                        "confidence": result.get('confidence', 0.0),
                    }
                )
                msg.company = company
            
            msg.save()
            
            # Update related thread tracking if exists
            if msg.thread_id:
                threads = ThreadTracking.objects.filter(thread_id=msg.thread_id)
                for thread in threads:
                    thread.update_from_messages()
            
            return True, None
            
        except Message.DoesNotExist:
            return False, f"Message {message_id} not found"
        except Exception as e:
            logger.error(f"Error reingesting message {message_id}: {e}")
            return False, str(e)

    @staticmethod
    def get_label_statistics():
        """Get statistics about message labels.
        
        Returns:
            Dictionary with label counts and percentages
        """
        from django.db.models import Count
        
        total = Message.objects.count()
        if total == 0:
            return {}
        
        label_counts = Message.objects.values('ml_label').annotate(
            count=Count('id')
        ).order_by('-count')
        
        stats = {}
        for item in label_counts:
            label = item['ml_label'] or 'unknown'
            count = item['count']
            percentage = (count / total) * 100
            stats[label] = {
                'count': count,
                'percentage': round(percentage, 1)
            }
        
        return stats
