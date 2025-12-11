#!/usr/bin/env python3
"""Script to automate extraction of views from views_legacy.py into modular package.

This script parses views_legacy.py and extracts functions into their respective modules
based on the categorization defined in Issue #20.
"""

import re
from pathlib import Path

# Define function categorization
CATEGORIES = {
    "helpers.py": [
        "build_sidebar_context",
        "extract_body_content",
        "validate_regex_pattern",
        "sanitize_string",
        "validate_domain",
        "_parse_pasted_gmail_spec",
    ],
    "api.py": [
        "ingestion_status_api",
    ],
    "debugging.py": [
        "label_rule_debugger",
        "upload_eml",
        "gmail_filters_labels_compare",
    ],
    "companies.py": [
        "delete_company",
        "label_companies",
        "merge_companies",
        "manage_domains",
    ],
    "aliases.py": [
        "manage_aliases",
        "approve_bulk_aliases",
        "reject_alias",
    ],
    "applications.py": [
        "edit_application",
        "flagged_applications",
        "manual_entry",
    ],
    "admin.py": [
        "retrain_model",
        "reingest_admin",
        "reingest_stream",
        "configure_settings",
        "json_file_viewer",
        "log_viewer",
    ],
    "dashboard.py": [
        "dashboard",
        "metrics",
        "company_threads",
    ],
    "messages.py": [
        "label_messages",
        "label_applications",
    ],
}

# Common imports for all modules
COMMON_IMPORTS = """import json
import logging
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.db.models import Q, F, Count, Case, When, Value, CharField

from tracker.models import Company, Message, IngestionStats, ThreadTracking, AuditEvent
from tracker.services import CompanyService, MessageService, StatsService

logger = logging.getLogger(__name__)
"""

def extract_function(content, func_name):
    """Extract a complete function definition from content."""
    # Find the function definition
    pattern = rf'^def {re.escape(func_name)}\('
    lines = content.split('\n')
    
    start_idx = None
    for i, line in enumerate(lines):
        if re.match(pattern, line):
            start_idx = i
            break
    
    if start_idx is None:
        return None
    
    # Find the end of the function (next def or class at same indentation, or EOF)
    indent_level = len(lines[start_idx]) - len(lines[start_idx].lstrip())
    end_idx = len(lines)
    
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if line.strip() and not line.startswith(' '):
            # Top-level statement
            if line.startswith('def ') or line.startswith('class ') or line.startswith('@'):
                end_idx = i
                break
        elif line.strip() and len(line) - len(line.lstrip()) <= indent_level:
            # Same or less indentation as function def
            if line.lstrip().startswith('def ') or line.lstrip().startswith('class ') or line.lstrip().startswith('@'):
                end_idx = i
                break
    
    return '\n'.join(lines[start_idx:end_idx])

def main():
    legacy_file = Path("tracker/views_legacy.py")
    views_dir = Path("tracker/views")
    
    if not legacy_file.exists():
        print(f"Error: {legacy_file} not found")
        return
    
    content = legacy_file.read_text()
    
    # Extract each category
    for module_name, functions in CATEGORIES.items():
        module_path = views_dir / module_name
        print(f"Creating {module_path}...")
        
        extracted_functions = []
        for func_name in functions:
            func_code = extract_function(content, func_name)
            if func_code:
                extracted_functions.append(func_code)
                print(f"  ✓ Extracted {func_name}")
            else:
                print(f"  ✗ Could not find {func_name}")
        
        if extracted_functions:
            # Write module file
            module_content = f'''"""{''.join(module_name.split('.')[0].title())} views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

{COMMON_IMPORTS}

{chr(10).join(extracted_functions)}

__all__ = {functions}
'''
            module_path.write_text(module_content)
            print(f"  → Wrote {len(extracted_functions)} functions to {module_path}")

if __name__ == "__main__":
    main()
