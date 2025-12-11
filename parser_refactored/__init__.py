"""
Refactored parser module with class-based architecture.

This package contains the refactored components extracted from parser.py:
- CompanyValidator: Company name validation and normalization
- RuleClassifier: Rule-based message classification
- (More classes to be added in Phase 1)
"""

from .company_validator import CompanyValidator
from .rule_classifier import RuleClassifier

__all__ = [
    'CompanyValidator',
    'RuleClassifier',
]
