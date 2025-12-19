"""Aliases views.

Extracted from monolithic views.py (Phase 5 refactoring).
"""

import json
from pathlib import Path
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from django.http import JsonResponse
from tracker.models import Company

ALIAS_EXPORT_PATH = Path("json/alias_suggestions.json")
ALIAS_LOG_PATH = Path("json/alias_log.json")
ALIAS_REJECT_LOG_PATH = Path("json/alias_reject_log.json")
PATTERNS_PATH = Path("json/patterns.json")


@login_required
def manage_aliases(request):
    """Display alias suggestions loaded from json/alias_candidates.json for review."""
    if not ALIAS_EXPORT_PATH.exists():
        ctx = {"suggestions": []}
        return render(request, "tracker/manage_aliases.html", ctx)

    with open(ALIAS_EXPORT_PATH, "r", encoding="utf-8") as f:
        suggestions = json.load(f)

    ctx = {"suggestions": suggestions}
    return render(request, "tracker/manage_aliases.html", ctx)


@csrf_exempt
def approve_bulk_aliases(request):
    """Persist approved alias→company mappings into patterns.json and log approvals."""
    if request.method == "POST":
        aliases = request.POST.getlist("alias")
        suggested = request.POST.getlist("suggested")

        # Load patterns
        if PATTERNS_PATH.exists():
            with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
                patterns = json.load(f)
        else:
            patterns = {"aliases": {}, "ignore": []}

        for alias, suggestion in zip(aliases, suggested):
            patterns["aliases"][alias] = suggestion
            with open(ALIAS_LOG_PATH, "a", encoding="utf-8") as log:
                log.write(f"{alias},{suggestion},{request.POST.get('timestamp')}\n")

        with open(PATTERNS_PATH, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2)

        return redirect("manage_aliases")


@csrf_exempt
def reject_alias(request):
    """Add an alias to the ignore list in patterns.json and log the rejection."""
    if request.method == "POST":
        alias = request.POST.get("alias")

        # Load patterns
        if PATTERNS_PATH.exists():
            with open(PATTERNS_PATH, "r", encoding="utf-8") as f:
                patterns = json.load(f)
        else:
            patterns = {"aliases": {}, "ignore": []}

        if alias not in patterns["ignore"]:
            patterns["ignore"].append(alias)

        with open(PATTERNS_PATH, "w", encoding="utf-8") as f:
            json.dump(patterns, f, indent=2)

        with open(ALIAS_REJECT_LOG_PATH, "a", encoding="utf-8") as log:
            log.write(f"{alias},{request.POST.get('timestamp')}\n")

        return redirect("manage_aliases")


__all__ = ["manage_aliases", "approve_bulk_aliases", "reject_alias"]
