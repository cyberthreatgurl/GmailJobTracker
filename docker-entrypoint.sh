#!/bin/bash
set -e

echo "🚀 Starting GmailJobTracker..."

# Wait for environment to be ready
echo "⏳ Checking environment..."

# Check if required environment variables are set
if [ -z "$GMAIL_JOBHUNT_LABEL_ID" ]; then
    echo "⚠️  WARNING: GMAIL_JOBHUNT_LABEL_ID not set. Gmail ingestion will not work."
fi

# Check if credentials exist
if [ ! -f "/app/json/credentials.json" ]; then
    echo "⚠️  WARNING: Gmail credentials.json not found. You'll need to mount it as a volume."
fi

# Initialize database if it doesn't exist
if [ ! -f "/app/db/job_tracker.db" ]; then
    echo "📊 Initializing database..."
    python manage.py migrate --noinput
    
    echo "👤 Creating superuser (if not exists)..."
    python manage.py shell << EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'changeme123')
    print('✅ Default superuser created (username: admin, password: changeme123)')
    print('⚠️  CHANGE THE PASSWORD IMMEDIATELY!')
else:
    print('ℹ️  Superuser already exists')
EOF
else
    echo "📊 Running migrations..."
    python manage.py migrate --noinput
fi

# Collect static files
echo "📦 Collecting static files..."
python manage.py collectstatic --noinput --clear

# Run environment checks
echo "🔍 Running environment checks..."
if [ -f "/app/check_env.py" ]; then
    python check_env.py || echo "⚠️  Some environment checks failed. Application may not work correctly."
fi

echo "✅ Initialization complete!"
echo ""
echo "🌐 Application will start on http://0.0.0.0:8001"
echo "🔐 Admin panel: http://localhost:8001/admin"
echo ""

# Execute the main command
exec "$@"
