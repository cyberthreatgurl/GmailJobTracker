# Quick Start Guide - Docker Deployment

This is a quick reference for deploying GmailJobTracker with Docker. For detailed documentation, see [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md).

## 🚀 5-Minute Setup

### Prerequisites

- Docker & Docker Compose installed
- Gmail API credentials file

### Getting Required Values

Before starting, you need two important values:

**1. DJANGO_SECRET_KEY** - Generate with:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

**2. GMAIL_JOBHUNT_LABEL_ID** - Get your Gmail label ID:

- Open Gmail → Settings → Labels
- Note your job hunting label name (or create one)
- Run: `python -c "from gmail_auth import get_gmail_service; service = get_gmail_service(); labels = service.users().labels().list(userId='me').execute(); [print(f'{l['name']}: {l['id']}') for l in labels['labels']]"`
- Copy the ID for your label (starts with `Label_`)

For detailed instructions, see [DOCKER_DESKTOP_GUIDE.md](DOCKER_DESKTOP_GUIDE.md)

### Windows (PowerShell)

```powershell
# 1. Clone repository
git clone https://github.com/cyberthreatgurl/GmailJobTracker.git
cd GmailJobTracker

# 2. Configure environment
Copy-Item .env.example .env
# Edit .env and set GMAIL_JOBHUNT_LABEL_ID

# 3. Add credentials
Copy-Item path\to\your\credentials.json json\credentials.json

# 4. Install and start
.\docker.ps1 install

# 5. Access application
Start-Process http://localhost:8000
```

### Linux/macOS

```bash
# 1. Clone repository
git clone https://github.com/cyberthreatgurl/GmailJobTracker.git
cd GmailJobTracker

# 2. Configure environment
cp .env.example .env
# Edit .env and set GMAIL_JOBHUNT_LABEL_ID

# 3. Add credentials
cp /path/to/your/credentials.json json/credentials.json

# 4. Install and start
make install

# 5. Access application
open http://localhost:8000
```

## 📋 Common Commands

### Windows (PowerShell)

```powershell
.\docker.ps1 up          # Start application
.\docker.ps1 down        # Stop application
.\docker.ps1 logs        # View logs
.\docker.ps1 shell       # Open shell
.\docker.ps1 ingest      # Ingest Gmail
.\docker.ps1 backup      # Create backup
.\docker.ps1 help        # Show all commands
```

### Linux/macOS (Makefile)

```bash
make up                  # Start application
make down                # Stop application
make logs                # View logs
make shell               # Open shell
make ingest              # Ingest Gmail
make backup              # Create backup
make help                # Show all commands
```

## 🔑 Default Credentials

- **Username:** admin
- **Password:** changeme123

⚠️ **Change immediately after first login!**

## 📚 Next Steps

1. **Change admin password:**

   ```bash
   docker-compose exec web python manage.py changepassword admin
   ```

2. **Ingest your emails:**
   - Click "📥 Ingest New Messages" in the dashboard
   - Or run: `docker-compose exec web python manage.py ingest_gmail`

3. **Train the ML model:**
   - Label some messages in the admin panel
   - Run: `docker-compose exec web python train_model.py`

## 📖 Documentation

- **[DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md)** - Complete deployment guide
- **[CI_CD_DOCUMENTATION.md](CI_CD_DOCUMENTATION.md)** - CI/CD pipeline details
- **[markdown/README.md](markdown/README.md)** - Application documentation

## 🆘 Troubleshooting

**Container won't start:**

```bash
docker-compose logs web
```

**Database issues:**

```bash
docker-compose down -v
docker-compose up -d --build
```

**Gmail authentication:**

```bash
rm json/token.json
docker-compose restart web
```

For more help, see [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md#-troubleshooting)
