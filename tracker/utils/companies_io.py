"""Surgical read-modify-write interface for companies.json.

``CompaniesStore`` is the sole writer for every path except the admin
edit_config view, which performs a user-intentional full-file replacement and
uses ``safe_write_companies_json()`` directly.

Each ``CompaniesStore`` method:

1. Acquires a process-level lock (no stale in-memory copies).
2. Reads the current file fresh.
3. Performs minimal, targeted mutations (only the fields it is authorised
   to change – making it structurally impossible for, say, a domain-label
   operation to zero out the ``known`` list).
4. Atomically replaces the file via a temp-file + ``os.replace()`` (POSIX
   atomic, safe against crashes mid-write).
5. Returns ``True`` iff the file was actually updated.

The module-level ``companies_store`` singleton is the only object callers need.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel: "this parameter was not supplied — leave the field untouched."
_UNCHANGED: Any = object()

# Process-level lock serialising all writes to the JSON file.
# (SQLite handles DB concurrency separately; this protects the flat file.)
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: dict) -> None:
    """Write *data* to *path* via temp-file + ``os.replace`` (POSIX atomic)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _classify_domain_in_data(
    data: dict,
    domain: str,
    label_type: str,
    company_name: str | None,
) -> bool:
    """Mutate *data* in place.  Returns ``True`` iff anything changed.

    ``label_type`` must be one of: ``ats``, ``headhunter``, ``job_board``
    (or ``job_boards``), ``company``, ``personal``.

    For ``personal`` the domain is only *removed* from company-side
    categories; the caller is responsible for updating personal_domains.json.
    """
    dtc = data.setdefault("domain_to_company", {})
    ats = set(data.get("ats_domains", []))
    headhunter = set(data.get("headhunter_domains", []))
    job_boards = set(data.get("job_boards", []))

    # Snapshot before
    was_dtc_val = dtc.get(domain)
    was_ats = domain in ats
    was_headhunter = domain in headhunter
    was_job_board = domain in job_boards

    # Remove from all company-side categories
    dtc.pop(domain, None)
    ats.discard(domain)
    headhunter.discard(domain)
    job_boards.discard(domain)

    # Add to the target category
    if label_type == "ats":
        ats.add(domain)
    elif label_type == "headhunter":
        headhunter.add(domain)
    elif label_type in ("job_board", "job_boards"):
        job_boards.add(domain)
    elif label_type == "company":
        name = company_name or (
            domain.split(".")[-2].title() if domain.count(".") >= 1 else domain.title()
        )
        dtc[domain] = name
    # "personal" → only remove (caller manages personal_domains.json)

    new_dtc_val = dtc.get(domain)
    changed = (
        new_dtc_val != was_dtc_val
        or (domain in ats) != was_ats
        or (domain in headhunter) != was_headhunter
        or (domain in job_boards) != was_job_board
    )

    if changed:
        data["domain_to_company"] = dict(sorted(dtc.items()))
        data["ats_domains"] = sorted(ats)
        data["headhunter_domains"] = sorted(headhunter)
        data["job_boards"] = sorted(job_boards)

    return changed


# ---------------------------------------------------------------------------
# CompaniesStore
# ---------------------------------------------------------------------------

class CompaniesStore:
    """Surgical read-modify-write interface for companies.json.

    Use the module-level ``companies_store`` singleton rather than
    instantiating this class directly.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict, source: str) -> None:
        _atomic_write(self._path, data)
        logger.info(
            "companies.json updated via [%s] — domains=%d known=%d aliases=%d",
            source,
            len(data.get("domain_to_company", {})),
            len(data.get("known", [])),
            len(data.get("aliases", {})),
        )

    # ------------------------------------------------------------------
    # Single-domain classification  (label_single)
    # ------------------------------------------------------------------

    def classify_domain(
        self,
        domain: str,
        label_type: str,
        company_name: str | None = None,
        source: str = "",
    ) -> bool:
        """Remove *domain* from all categories then place it in *label_type*.

        ``personal`` only removes from company-side categories; the caller
        is responsible for updating personal_domains.json.

        Returns ``True`` iff the file was updated.
        """
        with _lock:
            data = self._load()
            changed = _classify_domain_in_data(data, domain, label_type, company_name)
            if changed:
                self._write(data, source or f"classify_domain/{domain}")
        return changed

    # ------------------------------------------------------------------
    # Batch domain classification  (bulk_label)
    # ------------------------------------------------------------------

    def classify_domains(
        self,
        domains: list[str],
        label_type: str,
        company_names_map: dict[str, str] | None = None,
        source: str = "",
    ) -> int:
        """Bulk-label *domains* as *label_type* in one atomic read-write.

        Returns the number of domain entries actually changed.
        """
        if not domains:
            return 0
        with _lock:
            data = self._load()
            count = sum(
                1
                for d in domains
                if _classify_domain_in_data(
                    data, d, label_type, (company_names_map or {}).get(d)
                )
            )
            if count:
                self._write(data, source or f"classify_domains/{label_type}")
        return count

    def apply_domain_classifications(
        self,
        domain_labels: list[dict],
        source: str = "",
    ) -> int:
        """Apply a heterogeneous list of domain classifications atomically.

        Each item must have ``"domain"`` and ``"label_type"``;
        ``"company_name"`` is optional (used for ``label_type="company"``).

        Returns the number of entries actually changed.
        """
        if not domain_labels:
            return 0
        with _lock:
            data = self._load()
            count = sum(
                1
                for item in domain_labels
                if _classify_domain_in_data(
                    data,
                    item["domain"],
                    item["label_type"],
                    item.get("company_name"),
                )
            )
            if count:
                self._write(data, source or "apply_domain_classifications")
        return count

    # ------------------------------------------------------------------
    # Domain-mapping merge  (sync_db_to_json)
    # ------------------------------------------------------------------

    def merge_domain_mappings(
        self,
        dtc_additions: dict[str, str],
        ats_additions: set[str] | None = None,
        headhunter_additions: set[str] | None = None,
        source: str = "",
    ) -> int:
        """Add entries not already present; never overwrites or removes.

        Returns the total count of new entries added across all categories.
        """
        with _lock:
            data = self._load()
            dtc = data.setdefault("domain_to_company", {})
            ats = set(data.get("ats_domains", []))
            headhunter = set(data.get("headhunter_domains", []))
            added = 0

            for domain, company in dtc_additions.items():
                if domain not in dtc:
                    dtc[domain] = company
                    added += 1
            for domain in ats_additions or set():
                if domain not in ats:
                    ats.add(domain)
                    added += 1
            for domain in headhunter_additions or set():
                if domain not in headhunter:
                    headhunter.add(domain)
                    added += 1

            if added:
                data["domain_to_company"] = dict(sorted(dtc.items()))
                data["ats_domains"] = sorted(ats)
                data["headhunter_domains"] = sorted(headhunter)
                self._write(data, source or "merge_domain_mappings")

        return added

    # ------------------------------------------------------------------
    # Company registration  (create_company / contracts / message_service)
    # ------------------------------------------------------------------

    def register_company(
        self,
        name: str,
        *,
        domain: str | None = None,
        ats_domain: str | None = None,
        career_url: str | None = None,
        aliases: list[str] | None = None,
        overwrite_domain: bool = False,
        overwrite_career_url: bool = False,
        source: str = "",
    ) -> bool:
        """Add a company to known + optional domain/ATS/JobSites/aliases.

        By default does not overwrite existing entries.  Set
        *overwrite_domain* / *overwrite_career_url* to ``True`` to update
        an existing entry (used by message_service to correct stale mappings).

        Returns ``True`` iff the file was updated.
        """
        with _lock:
            data = self._load()
            changed = False

            if name and name not in data.setdefault("known", []):
                data["known"].append(name)
                changed = True

            if domain:
                dtc = data.setdefault("domain_to_company", {})
                existing = dtc.get(domain)
                if not existing or (overwrite_domain and existing != name):
                    dtc[domain] = name
                    data["domain_to_company"] = dict(sorted(dtc.items()))
                    changed = True

            if ats_domain:
                ats = data.setdefault("ats_domains", [])
                if ats_domain not in ats:
                    ats.append(ats_domain)
                    changed = True

            if career_url and name:
                sites = data.setdefault("JobSites", {})
                existing_url = sites.get(name)
                if not existing_url or (overwrite_career_url and existing_url != career_url):
                    sites[name] = career_url
                    changed = True

            for alias in aliases or []:
                alias_map = data.setdefault("aliases", {})
                if alias_map.get(alias) != name:
                    alias_map[alias] = name
                    changed = True

            if changed:
                self._write(data, source or f"register_company/{name}")

        return changed

    # ------------------------------------------------------------------
    # Registry snapshot sync  (signals export)
    # ------------------------------------------------------------------

    def sync_registry_snapshot(
        self,
        *,
        known: list[str],
        ats_domains: list[str],
        domain_to_company: dict[str, str],
        aliases: dict[str, str],
        source: str = "",
    ) -> bool:
        """Refresh DB-backed sections while preserving unrelated JSON keys."""
        with _lock:
            data = self._load()

            next_known = sorted(set(known))
            next_ats_domains = sorted(set(ats_domains))
            next_domain_to_company = dict(sorted(domain_to_company.items()))
            next_aliases = dict(sorted(aliases.items()))

            changed = any(
                (
                    data.get("known", []) != next_known,
                    data.get("ats_domains", []) != next_ats_domains,
                    data.get("domain_to_company", {}) != next_domain_to_company,
                    data.get("aliases", {}) != next_aliases,
                )
            )

            if not changed:
                return False

            data["known"] = next_known
            data["ats_domains"] = next_ats_domains
            data["domain_to_company"] = next_domain_to_company
            data["aliases"] = next_aliases
            self._write(data, source or "sync_registry_snapshot")

        return True

    # ------------------------------------------------------------------
    # Company update  (save_company)
    # ------------------------------------------------------------------

    def update_company(
        self,
        name: str,
        *,
        new_domain: Any = _UNCHANGED,
        career_url: Any = _UNCHANGED,
        ats_domain: str | None = None,
        new_aliases: list[str] | None = None,
        source: str = "",
    ) -> bool:
        """Apply user-driven edits to a company's JSON entries.

        Parameters
        ----------
        new_domain
            ``_UNCHANGED`` (default) — leave untouched.
            ``""``          — remove the current mapping for *name*.
            ``"foo.com"``   — set or rename (removes current if different).
        career_url
            ``_UNCHANGED`` (default) — leave untouched.
            ``""``          — remove from JobSites.
            ``"url"``       — set or update.
        ats_domain
            ``None`` — leave untouched.
            ``"dom"`` — add if not present (never removed; shared by companies).
        new_aliases
            ``None``   — leave untouched.
            ``[]``     — remove all aliases pointing to *name*.
            ``[...]``  — replace (remove stale, add new).

        Returns ``True`` iff the file was updated.
        """
        with _lock:
            data = self._load()
            changed = False

            # --- domain ---
            if new_domain is not _UNCHANGED:
                dtc = data.setdefault("domain_to_company", {})
                current = next((d for d, c in dtc.items() if c == name), None)
                if new_domain:
                    if current and current != new_domain:
                        del dtc[current]
                        changed = True
                    if dtc.get(new_domain) != name:
                        dtc[new_domain] = name
                        changed = True
                else:
                    # empty string → clear
                    if current:
                        del dtc[current]
                        changed = True
                if changed:
                    data["domain_to_company"] = dict(sorted(dtc.items()))

            # --- career URL ---
            if career_url is not _UNCHANGED:
                sites = data.setdefault("JobSites", {})
                if career_url:
                    if sites.get(name) != career_url:
                        sites[name] = career_url
                        changed = True
                else:
                    if name in sites:
                        del sites[name]
                        changed = True

            # --- ATS domain (add-only; shared across companies) ---
            if ats_domain:
                if _classify_domain_in_data(data, ats_domain, "ats", None):
                    changed = True

            # --- aliases ---
            if new_aliases is not None:
                alias_map = data.setdefault("aliases", {})
                old = [k for k, v in alias_map.items() if v == name]
                for alias in [a for a in old if a not in new_aliases]:
                    del alias_map[alias]
                    changed = True
                for alias in [a for a in new_aliases if alias_map.get(a) != name]:
                    alias_map[alias] = name
                    changed = True

            if changed:
                self._write(data, source or f"update_company/{name}")

        return changed

    def remove_company_registration(
        self,
        name: str,
        *,
        domain: str | None = None,
        ats_domain: str | None = None,
        remove_ats_domain: bool = False,
        source: str = "",
    ) -> bool:
        """Remove a company's JSON registry entries while preserving unrelated data."""
        with _lock:
            data = self._load()
            changed = False

            known = data.setdefault("known", [])
            if name in known:
                data["known"] = [item for item in known if item != name]
                changed = True

            dtc = data.setdefault("domain_to_company", {})
            stale_domains = [mapped_domain for mapped_domain, company in dtc.items() if company == name]
            if domain and dtc.get(domain) == name and domain not in stale_domains:
                stale_domains.append(domain)
            for stale_domain in stale_domains:
                del dtc[stale_domain]
                changed = True
            if changed:
                data["domain_to_company"] = dict(sorted(dtc.items()))

            sites = data.setdefault("JobSites", {})
            if name in sites:
                del sites[name]
                changed = True

            alias_map = data.setdefault("aliases", {})
            aliases_to_remove = [alias for alias, company in alias_map.items() if company == name]
            for alias in aliases_to_remove:
                del alias_map[alias]
                changed = True

            if remove_ats_domain and ats_domain:
                ats_domains = data.setdefault("ats_domains", [])
                if ats_domain in ats_domains:
                    data["ats_domains"] = [item for item in ats_domains if item != ats_domain]
                    changed = True

            if changed:
                self._write(data, source or f"remove_company_registration/{name}")

        return changed


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "json" / "companies.json"
companies_store = CompaniesStore(_DEFAULT_PATH)


# ---------------------------------------------------------------------------
# Legacy full-file replacement — admin edit_config ONLY
# ---------------------------------------------------------------------------

def safe_write_companies_json(
    companies_json_path: Path,
    new_data: dict[str, Any],
    source: str,
) -> bool:
    """Full-file replacement with a shrinkage guard.

    **Only** use this for the admin ``edit_config`` path where the user
    intentionally replaces the entire file.  All other write paths must use
    ``companies_store``.

    Returns ``True`` if the write succeeded, ``False`` if blocked or failed.
    """
    _SHRINK_THRESHOLD = 0.20

    def _counts(d: dict) -> tuple[int, int, int]:
        return (
            len(d.get("domain_to_company", {})),
            len(d.get("known", [])),
            len(d.get("aliases", {})),
        )

    try:
        old_domains, old_known, old_aliases = 0, 0, 0
        if companies_json_path.exists():
            try:
                with open(companies_json_path, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                old_domains, old_known, old_aliases = _counts(old_data)
            except (OSError, json.JSONDecodeError):
                pass

        new_domains, new_known, new_aliases = _counts(new_data)

        reasons = []
        for label, old_n, new_n in (
            ("domain_to_company", old_domains, new_domains),
            ("known", old_known, new_known),
            ("aliases", old_aliases, new_aliases),
        ):
            if old_n > 0 and new_n < old_n * (1 - _SHRINK_THRESHOLD):
                reasons.append(f"{label}: {old_n} → {new_n} (lost {old_n - new_n})")

        if reasons:
            logger.error(
                "companies.json WRITE BLOCKED via [%s] — shrinkage: %s\n%s",
                source,
                "; ".join(reasons),
                "".join(traceback.format_stack()[:-1]),
            )
            return False

        _atomic_write(companies_json_path, new_data)
        logger.info(
            "companies.json full-replace via [%s] domains=%d known=%d aliases=%d",
            source, new_domains, new_known, new_aliases,
        )
        return True

    except Exception as exc:
        logger.exception("companies.json WRITE via [%s] failed: %s", source, exc)
        return False
