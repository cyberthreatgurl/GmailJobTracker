"""Services package for GmailJobTracker.

This package contains business logic services:
- message_service: Message-related business logic
- company_service: Company-related business logic
- stats_service: Statistics and analytics calculations
"""

from .company_service import CompanyService
from .message_service import MessageService

__all__ = ['MessageService', 'CompanyService']
