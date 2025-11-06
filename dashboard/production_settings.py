# Production settings override for Docker deployment
# This file contains production-specific Django settings
# Import this in settings.py when running in Docker

import os

# Security settings
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-docker-default-key-change-me")

# Allowed hosts from environment
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Database
DB_PATH = os.getenv("DATABASE_PATH", "/app/db/job_tracker.db")

# Static files
STATIC_ROOT = os.getenv("STATIC_ROOT", "/app/staticfiles")

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/app/logs/django.log",
            "maxBytes": 1024 * 1024 * 10,  # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "tracker": {
            "handlers": ["console", "file"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

# Security headers (only in production)
if not DEBUG:
    SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "False").lower() == "true"
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True

# Application-specific settings
AUTO_REVIEW_CONFIDENCE = float(os.getenv("AUTO_REVIEW_CONFIDENCE", "0.85"))
ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.55"))
DEFAULT_DAYS_BACK = int(os.getenv("DEFAULT_DAYS_BACK", "7"))
MAX_MESSAGES_PER_BATCH = int(os.getenv("MAX_MESSAGES_PER_BATCH", "500"))
GHOSTED_DAYS_THRESHOLD = int(os.getenv("GHOSTED_DAYS_THRESHOLD", "30"))
GMAIL_JOBHUNT_LABEL_ID = os.getenv("GMAIL_JOBHUNT_LABEL_ID", "")
