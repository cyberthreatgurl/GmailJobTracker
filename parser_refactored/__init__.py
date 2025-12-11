"""
Refactored parser module with class-based architecture.

This package contains the refactored components extracted from parser.py:
- CompanyValidator: Company name validation and normalization
- RuleClassifier: Rule-based message classification
- DomainMapper: Domain-to-company mapping and ATS detection
- CompanyResolver: Company extraction from emails (multiple strategies)
- (More classes to be added in Phase 1)
"""

from .company_validator import CompanyValidator
from .rule_classifier import RuleClassifier
from .domain_mapper import DomainMapper
from .company_resolver import CompanyResolver

__all__ = [
    'CompanyValidator',
    'RuleClassifier',
    'DomainMapper',
    'CompanyResolver',
]
