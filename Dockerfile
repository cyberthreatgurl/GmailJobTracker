# Multi-stage Dockerfile for GmailJobTracker
# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
# Cache bust: 2025-12-11
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=dashboard.settings

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Create necessary directories with proper permissions
RUN mkdir -p /app/db /app/logs /app/model /app/staticfiles /app/json && \
    chmod -R 755 /app/db /app/logs /app/model /app/staticfiles /app/json

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Collect static files
RUN python manage.py collectstatic --noinput

# Create a non-root user for security
RUN useradd -m -u 1000 gmailtracker && \
    chown -R gmailtracker:gmailtracker /app

USER gmailtracker

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001').read()" || exit 1

# Expose port
EXPOSE 8001

# Entry point script
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/
ENTRYPOINT ["docker-entrypoint.sh"]

# Default command
CMD ["python", "manage.py", "runserver", "0.0.0.0:8001"]
