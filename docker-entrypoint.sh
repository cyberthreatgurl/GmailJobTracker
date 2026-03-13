#!/bin/bash
set -e

echo "🚀 Starting GmailJobTracker..."

# Check for Gmail credentials
if [ ! -f "/app/json/credentials.json" ]; then
    echo "⚠️  WARNING: Gmail credentials.json not found. Gmail ingestion will not work."
    echo "   Mount it via: -v /path/to/credentials.json:/app/json/credentials.json"
fi
if [ ! -f "/app/model/token.pickle" ]; then
    echo "⚠️  WARNING: model/token.pickle not found. Gmail ingestion will not work until you authenticate."
fi

# Wait for PostgreSQL to be ready (DB_HOST defaults to 'db' in docker-compose)
DB_HOST_CHECK="${DB_HOST:-db}"
DB_PORT_CHECK="${DB_PORT:-5432}"
echo "⏳ Waiting for PostgreSQL at ${DB_HOST_CHECK}:${DB_PORT_CHECK}..."
for i in $(seq 1 30); do
    if python -c "
import socket, sys
try:
    s = socket.create_connection(('${DB_HOST_CHECK}', ${DB_PORT_CHECK}), timeout=2)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        echo "✅ PostgreSQL is ready."
        break
    fi
    echo "   Still waiting... ($i/30)"
    sleep 2
done

# Run migrations
echo "📊 Running database migrations..."
python manage.py migrate --noinput

# Create default superuser if none exists
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(is_superuser=True).exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'changeme123')
    print('✅ Default superuser created (username: admin, password: changeme123)')
    print('⚠️  CHANGE THE PASSWORD IMMEDIATELY at /admin/')
else:
    print('ℹ️  Superuser already exists')
"

# Collect static files
echo "📦 Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "✅ Initialization complete!"
echo ""
echo "🌐 Application will start on http://0.0.0.0:8001"
echo "🔐 Admin panel: http://localhost:8001/admin"
echo ""

# Execute the main command (gunicorn by default via Dockerfile CMD)
exec "$@"
