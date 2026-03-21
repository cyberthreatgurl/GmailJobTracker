import importlib
import sys

import pytest
from django.core.management.base import CommandError
from django.core.management.commands.runserver import Command as DjangoRunserverCommand
from django.db.utils import OperationalError

from tracker.management.commands.runserver import Command
from tracker.startup_checks import (
    DatabaseStartupError,
    describe_default_database,
    ensure_default_database_reachable,
    format_database_unreachable_message,
)


def test_describe_default_database_for_postgres(settings):
    settings.DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "db",
        "PORT": 5432,
        "NAME": "tracker",
    }

    assert describe_default_database() == "PostgreSQL db:5432/tracker"


def test_format_database_unreachable_message_for_postgres(settings):
    settings.DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "db",
        "PORT": 5432,
        "NAME": "tracker",
    }

    assert format_database_unreachable_message() == (
        "PostgrSQL tracker db:5432 is unreachable."
    )


def test_ensure_default_database_reachable_raises_startup_error(monkeypatch, settings):
    settings.DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "db",
        "PORT": 5432,
        "NAME": "tracker",
    }

    class FailingConnection:
        def ensure_connection(self):
            raise OperationalError("connection refused")

    monkeypatch.setattr(
        importlib.import_module("tracker.startup_checks"),
        "connections",
        {"default": FailingConnection()},
    )

    with pytest.raises(DatabaseStartupError, match="PostgrSQL tracker db:5432 is unreachable"):
        ensure_default_database_reachable()


def test_runserver_stops_when_database_is_unreachable(monkeypatch):
    command = Command()

    def raise_startup_error():
        raise DatabaseStartupError("PostgrSQL tracker localhost:5432 is unreachable.")

    monkeypatch.setattr(
        "tracker.management.commands.runserver.ensure_default_database_reachable",
        raise_startup_error,
    )
    monkeypatch.setattr(DjangoRunserverCommand, "run", lambda self, **options: None)

    with pytest.raises(CommandError, match="PostgrSQL tracker localhost:5432 is unreachable"):
        command.run(use_reloader=False)


@pytest.mark.parametrize(
    ("module_name", "application_factory"),
    [
        ("dashboard.wsgi", "django.core.wsgi.get_wsgi_application"),
        ("dashboard.asgi", "django.core.asgi.get_asgi_application"),
    ],
)
def test_server_entrypoints_fail_fast_on_database_error(
    monkeypatch,
    module_name,
    application_factory,
):
    def raise_startup_error():
        raise DatabaseStartupError("startup database failure")

    factory_called = False

    def fake_application_factory():
        nonlocal factory_called
        factory_called = True
        return object()

    monkeypatch.setattr(
        "tracker.startup_checks.ensure_default_database_reachable",
        raise_startup_error,
    )
    monkeypatch.setattr(application_factory, fake_application_factory)

    sys.modules.pop(module_name, None)

    with pytest.raises(DatabaseStartupError, match="startup database failure"):
        importlib.import_module(module_name)

    assert not factory_called