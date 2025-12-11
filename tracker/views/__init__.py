"""Views package for GmailJobTracker.

Phase 5 Refactoring: Modularized from monolithic views.py (4,403 lines).

This package systematically imports from new modules as they're migrated,
falling back to views_legacy.py for functions not yet migrated.
"""

# Import migrated modules
from .helpers import *  # noqa: F401, F403
from .api import *  # noqa: F401, F403

# Import remaining functions from legacy views
# pylint: disable=wildcard-import,unused-wildcard-import
from tracker.views_legacy import (  # noqa: F401
    label_rule_debugger,
    upload_eml,
    gmail_filters_labels_compare,
    delete_company,
    label_companies,
    merge_companies,
    log_viewer,
    company_threads,
    manage_aliases,
    approve_bulk_aliases,
    reject_alias,
    edit_application,
    flagged_applications,
    manual_entry,
    dashboard,
    label_applications,
    label_messages,
    metrics,
    retrain_model,
    json_file_viewer,
    reingest_admin,
    reingest_stream,
    configure_settings,
    manage_domains,
)

__all__ = []
