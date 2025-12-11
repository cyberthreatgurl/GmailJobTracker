"""Views package for GmailJobTracker.

Phase 5 Refactoring: Modularized from monolithic views.py (4,403 lines).

During migration, this package imports from views_legacy.py to maintain
backward compatibility while we systematically migrate functions to new modules.
"""

# Import everything from legacy views to maintain backward compatibility
# pylint: disable=wildcard-import,unused-wildcard-import
from tracker.views_legacy import *  # noqa: F401, F403

__all__ = []
