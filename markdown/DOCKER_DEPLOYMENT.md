# GmailJobTracker - Docker Deployment Guide

This guide covers deploying GmailJobTracker in a Docker container for self-hosted servers.

## 📋 Prerequisites

- Docker Engine 20.10+ and Docker Compose 2.0+
- 2GB RAM minimum (4GB recommended)
- 10GB disk space
- Gmail API credentials (`credentials.json`)

## 🚀 Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/cyberthreatgurl/GmailJobTracker.git
cd GmailJobTracker

# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env  # or vim, code, etc.
```

**Required environment variables:**

```bash
DJANGO_SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")
```

### 2. Prepare Gmail Credentials

Place your Gmail OAuth credentials file:

```bash
# Ensure json directory exists
mkdir -p json

# Copy your credentials (obtained from Google Cloud Console)
cp /path/to/your/credentials.json json/credentials.json
```

### 3. Deploy with Docker Compose

```bash
# Build and start the container
docker-compose up -d

# View logs
docker-compose logs -f web

# Check status
docker-compose ps
```

### 4. First-Time Setup

```bash
# Access the container
docker-compose exec web bash

# Create superuser (if not auto-created)
python manage.py createsuperuser

# Exit container
exit
```

### 5. Access the Application

- **Dashboard:** <http://localhost:8000>
- **Admin Panel:** <http://localhost:8000/admin>
- **Default Credentials:** admin / changeme123 (⚠️ **Change immediately!**)

## 📦 Building from Source

### Manual Docker Build

```bash
# Build the image
docker build -t gmailtracker:latest .

# Run with custom settings
docker run -d \
  --name gmailtracker \
  -p 8000:8000 \
  -v $(pwd)/db:/app/db \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/json/credentials.json:/app/json/credentials.json:ro \
  -e GMAIL_JOBHUNT_LABEL_ID=your_label_id \
  gmailtracker:latest
```

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GMAIL_JOBHUNT_LABEL_ID` | *required* | Gmail label ID for job emails |
| `GMAIL_ROOT_FILTER_LABEL` | `#job-hunt` | Parent label for organizing sub-labels |
| `DJANGO_SECRET_KEY` | *auto-generated* | Django secret key |
| `DEBUG` | `False` | Enable debug mode |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `LOG_LEVEL` | `INFO` | Logging level |
| `AUTO_REVIEW_CONFIDENCE` | `0.85` | Auto-review threshold |
| `ML_CONFIDENCE_THRESHOLD` | `0.55` | ML classification threshold |
| `DEFAULT_DAYS_BACK` | `7` | Default ingestion lookback |
| `GHOSTED_DAYS_THRESHOLD` | `30` | Days before marking ghosted |

### Volume Mounts

The following directories are mounted as volumes for data persistence:

- `./db` - SQLite database
- `./logs` - Application logs
- `./model` - ML model artifacts
- `./json/credentials.json` - Gmail OAuth credentials (read-only)
- `./json/token.json` - Gmail OAuth token (read-write)

### Custom Port

Edit `docker-compose.yml`:

```yaml
ports:
  - "3000:8000"  # Change left side to your desired port
```

## 🔄 Management Commands

### Ingest Gmail Messages

```bash
# Ingest last 7 days
docker-compose exec web python manage.py ingest_gmail

# Ingest last 30 days
docker-compose exec web python manage.py ingest_gmail --days-back 30

# Force re-ingest
docker-compose exec web python manage.py ingest_gmail --force
```

### Train ML Model

```bash
docker-compose exec web python train_model.py --verbose
```

### Mark Ghosted Applications

```bash
docker-compose exec web python manage.py mark_ghosted
```

### Reclassify Messages

```bash
docker-compose exec web python manage.py reclassify_messages
```

## 📊 Monitoring & Logs

### View Real-Time Logs

```bash
# All logs
docker-compose logs -f

# Specific service
docker-compose logs -f web

# Last 100 lines
docker-compose logs --tail=100 web
```

### Application Logs

Logs are stored in the `logs/` directory (mounted volume):

```bash
tail -f logs/django.log
tail -f logs/ingestion.log
```

### Health Check

```bash
# Check container health
docker-compose ps

# Manual health check
curl http://localhost:8000
```

## 🔄 Updating

### Pull Latest Changes

```bash
# Stop containers
docker-compose down

# Pull latest code
git pull origin main

# Rebuild and restart
docker-compose up -d --build

# Run migrations
docker-compose exec web python manage.py migrate
```

### Using Pre-Built Images (from GitHub Registry)

```bash
# Pull from GitHub Container Registry
docker pull ghcr.io/cyberthreatgurl/gmailjobtracker:latest

# Update docker-compose.yml to use pre-built image
# Replace 'build: .' with:
# image: ghcr.io/cyberthreatgurl/gmailjobtracker:latest

# Start with pre-built image
docker-compose up -d
```

## 🛡️ Security Best Practices

### 1. Change Default Credentials

```bash
docker-compose exec web python manage.py changepassword admin
```

### 2. Use Strong Secret Key

Generate a new secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Add to `.env`:

```bash
DJANGO_SECRET_KEY=your-generated-secret-key
```

### 3. Disable Debug in Production

```bash
# In .env
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
```

### 4. Secure Credentials

```bash
# Set proper permissions
chmod 600 json/credentials.json
chmod 600 json/token.json
chmod 600 .env
```

### 5. Use HTTPS (Reverse Proxy)

Example with Nginx:

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 🧪 Testing the Deployment

```bash
# Run environment checks
docker-compose exec web python check_env.py

# Run tests
docker-compose exec web pytest

# Verify database
docker-compose exec web python manage.py dbshell
```

## 🐛 Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs web

# Verify environment
docker-compose config

# Rebuild from scratch
docker-compose down -v
docker-compose up -d --build
```

### Database Locked Errors

```bash
# Stop all containers
docker-compose down

# Remove database lock
rm db/.*.lock

# Restart
docker-compose up -d
```

### Gmail Authentication Issues

```bash
# Remove old token
rm json/token.json

# Restart container (will trigger re-auth)
docker-compose restart web
```

### Permission Errors

```bash
# Fix permissions on host
sudo chown -R $USER:$USER db/ logs/ model/ json/

# Inside container
docker-compose exec web chown -R gmailtracker:gmailtracker /app/db /app/logs
```

## 📈 Performance Tuning

### Increase Memory Limit

Edit `docker-compose.yml`:

```yaml
services:
  web:
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G
```

### Enable Production Server (Gunicorn)

```bash
# Install gunicorn in container
docker-compose exec web pip install gunicorn

# Run with gunicorn
docker-compose exec web gunicorn dashboard.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

Or update `docker-compose.yml` command:

```yaml
command: gunicorn dashboard.wsgi:application --bind 0.0.0.0:8000 --workers 4
```

## 🔄 Backup & Restore

### Backup

```bash
# Create backup directory
mkdir -p backups/$(date +%Y%m%d)

# Backup database
docker-compose exec web sqlite3 /app/db/job_tracker.db ".backup '/app/db/backup.db'"
cp db/backup.db backups/$(date +%Y%m%d)/job_tracker.db

# Backup model and configs
tar -czf backups/$(date +%Y%m%d)/gmailtracker-backup.tar.gz db/ model/ json/
```

### Restore

```bash
# Stop containers
docker-compose down

# Restore database
cp backups/20251106/job_tracker.db db/

# Restore configs
tar -xzf backups/20251106/gmailtracker-backup.tar.gz

# Restart
docker-compose up -d
```

## 📚 Additional Resources

- [GitHub Repository](https://github.com/cyberthreatgurl/GmailJobTracker)
- [Gmail API Setup](../markdown/README.md)
- [Development Guide](../markdown/NOTES.md)
- [Security Documentation](../markdown/SECURITY.md)

## 🆘 Getting Help

- **Issues:** <https://github.com/cyberthreatgurl/GmailJobTracker/issues>
- **Discussions:** <https://github.com/cyberthreatgurl/GmailJobTracker/discussions>
- **Email:** <support@yourdomain.com>
