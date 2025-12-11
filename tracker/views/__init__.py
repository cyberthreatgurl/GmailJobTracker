"""Views package for GmailJobTracker.

Phase 5 Refactoring: Complete - modularized from monolithic views.py (4,403 lines).

All 31 view functions now organized into 9 specialized modules.
"""

# Import all view modules
from .helpers import *  # noqa: F401, F403
from .api import *  # noqa: F401, F403
from .debugging import *  # noqa: F401, F403
from .companies import *  # noqa: F401, F403
from .aliases import *  # noqa: F401, F403
from .applications import *  # noqa: F401, F403
from .admin import *  # noqa: F401, F403
from .dashboard import *  # noqa: F401, F403
from .messages import *  # noqa: F401, F403

__all__ = []
