#!/bin/bash

echo "🔄 Resetting GmailJobTracker development environment..."

# Step 1: Remove the correct database
echo "🧹 Removing job_tracker.db..."
rm -f job_tracker.db

# Step 2: Clear old migration files (except __init__.py)
echo "🧹 Clearing migration files..."
find . -path "*/migrations/*.py" -not -name "__init__.py" -delete
find . -path "*/migrations/*.pyc" -delete

# Step 3: Rebuild migrations
echo "🏗️ Rebuilding migrations..."
# source venv/bin/activate
python manage.py makemigrations
python manage.py migrate

# Step 4: Create superuser
echo "🔐 Creating superuser..."
python manage.py createsuperuser

# Step 5: Run ingestion
echo "📥 Running ingestion..."
python main.py

# Step 6: Launch dev server
echo "🚀 Starting development server..."
python manage.py runserver