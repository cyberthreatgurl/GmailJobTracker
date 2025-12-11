"""
Refactored parser module with class-based architecture.

This package contains the refactored components extracted from parser.py:
- CompanyValidator: Company name validation and normalization
- RuleClassifier: Rule-based message classification
- DomainMapper: Domain-to-company mapping and ATS detection
- CompanyResolver: Company extraction from emails (multiple strategies)
- EmailBodyParser: Email body extraction and parsing
- (More classes to be added in Phase 1)
"""

from .company_validator import CompanyValidator
from .rule_classifier import RuleClassifier
from .domain_mapper import DomainMapper
from .company_resolver import CompanyResolver
from .email_body_parser import EmailBodyParser
from .metadata_extractor import MetadataExtractor

__all__ = [
    "CompanyValidator",
    "RuleClassifier",
    "DomainMapper",
    "CompanyResolver",
    "EmailBodyParser",
    "MetadataExtractor",
]
