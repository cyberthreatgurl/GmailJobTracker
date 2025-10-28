from typing import Dict


def sidebar_context(request) -> Dict:
    """Inject sidebar metrics into all templates.

    Delegates to tracker.views.build_sidebar_context to keep a single source of truth.
    Wrapped in try/except so template rendering never breaks on errors.
    """
    try:
        # Local import to avoid potential circular imports at module load time
        from tracker.views import build_sidebar_context  # type: ignore

        return build_sidebar_context()
    except Exception:
        # Fail-closed: return empty dict if stats cannot be built
        return {}
