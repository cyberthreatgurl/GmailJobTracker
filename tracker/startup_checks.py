"""Fail-fast startup checks for application boot."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.db.utils import OperationalError


class DatabaseStartupError(ImproperlyConfigured):
    """Raised when the default database is unreachable during startup."""


def describe_default_database() -> str:
    """Return a human-readable description of the default database target."""
    db_settings = settings.DATABASES.get("default", {})
    engine = db_settings.get("ENGINE", "")

    if "postgresql" in engine or "postgres" in engine:
        host = db_settings.get("HOST", "localhost")
        port = db_settings.get("PORT", 5432)
        name = db_settings.get("NAME", "")
        return f"PostgreSQL {host}:{port}/{name}"

    if "sqlite" in engine:
        return f"SQLite {db_settings.get('NAME', '')}"

    if engine:
        return f"{engine} database"

    return "default database"


def format_database_unreachable_message() -> str:
    """Return a concise startup error for an unreachable default database."""
    db_settings = settings.DATABASES.get("default", {})
    engine = db_settings.get("ENGINE", "")

    if "postgresql" in engine or "postgres" in engine:
        host = db_settings.get("HOST", "localhost")
        port = db_settings.get("PORT", 5432)
        name = db_settings.get("NAME", "")
        return f"PostgrSQL {name} {host}:{port} is unreachable."

    if "sqlite" in engine:
        name = db_settings.get("NAME", "")
        return f"SQLite {name} is unreachable."

    return f"{describe_default_database()} is unreachable."


def ensure_default_database_reachable() -> None:
    """Raise a startup error when the default database cannot be reached."""
    try:
        connections["default"].ensure_connection()
    except OperationalError as exc:
        raise DatabaseStartupError(format_database_unreachable_message()) from exc