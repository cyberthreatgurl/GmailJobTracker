"""
ASGI config for dashboard project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

from tracker.startup_checks import ensure_default_database_reachable

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")

ensure_default_database_reachable()

application = get_asgi_application()
