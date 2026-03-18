"""Safe writer for companies.json.

All code that writes companies.json MUST go through _safe_write_companies_json().
It refuses to write if the new data would shrink the file by more than SHRINK_THRESHOLD,
logging a loud warning with a stack trace so the culprit is immediately identifiable.
"""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# How much the file is allowed to shrink in one write (fraction of current size).
# 0.20 means: refuse if the new version would lose more than 20% of known entries.
# A single UI action should never remove more than a handful of entries.
SHRINK_THRESHOLD = 0.20


def _entry_counts(data: dict) -> tuple[int, int, int]:
    """Return (domain_count, known_count, alias_count) for a companies dict."""
    return (
        len(data.get("domain_to_company", {})),
        len(data.get("known", [])),
        len(data.get("aliases", {})),
    )


def safe_write_companies_json(
    companies_json_path: Path,
    new_data: dict[str, Any],
    source: str,
) -> bool:
    """Atomically write new_data to companies_json_path with a shrinkage guard.

    Args:
        companies_json_path: Absolute or relative path to companies.json.
        new_data:            The new dict to serialize and write.
        source:              Human-readable label for the write path (shown in logs).

    Returns:
        True if the write succeeded, False if it was blocked or failed.
    """
    try:
        # --- read the current file to get baseline counts ---
        existing_domains, existing_known, existing_aliases = 0, 0, 0
        if companies_json_path.exists():
            try:
                with open(companies_json_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                existing_domains, existing_known, existing_aliases = _entry_counts(existing)
            except (OSError, json.JSONDecodeError):
                pass  # can't read existing — allow the write

        new_domains, new_known, new_aliases = _entry_counts(new_data)

        # Guard: refuse writes that drop more than SHRINK_THRESHOLD of any category
        blocked = False
        reasons = []
        for label, old_n, new_n in (
            ("domain_to_company", existing_domains, new_domains),
            ("known", existing_known, new_known),
            ("aliases", existing_aliases, new_aliases),
        ):
            if old_n > 0 and new_n < old_n * (1 - SHRINK_THRESHOLD):
                reasons.append(
                    f"{label}: {old_n} → {new_n} (lost {old_n - new_n})"
                )
                blocked = True

        if blocked:
            logger.error(
                "companies.json WRITE BLOCKED via [%s] — data shrinkage detected: %s\n%s",
                source,
                "; ".join(reasons),
                "".join(traceback.format_stack()[:-1]),
            )
            return False

        # --- write ---
        with open(companies_json_path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)

        logger.info(
            "companies.json WRITE via [%s] domains=%d known=%d aliases=%d",
            source,
            new_domains,
            new_known,
            new_aliases,
        )
        return True

    except Exception as exc:
        logger.exception("companies.json WRITE via [%s] failed: %s", source, exc)
        return False
