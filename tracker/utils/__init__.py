"""Utility modules for GmailJobTracker.

Phase 4 Refactoring: Extracted utility functions from parser.py into organized modules.

Modules:
    validation: Company name validation and normalization utilities
    email_parsing: Email/MIME parsing and decoding utilities  
    helpers: General helper functions for pattern matching and logging

Note: These utilities are thin wrappers that delegate to class methods from parser.py
(CompanyValidator, EmailBodyParser, etc.) to avoid circular imports while providing
a clean, organized API for utility functions.
"""

# Import modules for users who want to use them directly
from . import validation, email_parsing, helpers

__all__ = [
    "validation",
    "email_parsing",
    "helpers",
]
