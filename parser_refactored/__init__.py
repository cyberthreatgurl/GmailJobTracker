"""
Refactored parser module with class-based architecture.

This package contains the refactored components extracted from parser.py:
- CompanyValidator: Company name validation and normalization
- (More classes to be added in Phase 1)
"""

from .company_validator import CompanyValidator

__all__ = [
    'CompanyValidator',
]
