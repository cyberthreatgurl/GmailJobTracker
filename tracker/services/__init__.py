"""Services package for GmailJobTracker.

This package contains business logic services:
- message_service: Message-related business logic
- company_service: Company-related business logic
- stats_service: Statistics and analytics calculations
- contract_scraper: Defense contract award scraping from war.gov
"""

from .company_service import CompanyService
from .contract_scraper import ContractScraperService
from .message_service import MessageService
from .stats_service import StatsService

__all__ = ["MessageService", "CompanyService", "StatsService", "ContractScraperService"]
