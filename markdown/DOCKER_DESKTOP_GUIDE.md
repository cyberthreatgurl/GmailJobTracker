# Docker Desktop Installation Guide for GmailJobTracker

## Prerequisites

- ✅ Docker Desktop installed and running on Windows
- ✅ Gmail API credentials file (`credentials.json`)
- ✅ Basic familiarity with PowerShell

## 📁 Required Files (Already in Your Repository)

Your application already has all the necessary files:

### Core Application Files
```
GmailJobTracker/
├── Dockerfile                    # Docker build instructions
├── docker-compose.yml            # Container orchestration
├── docker-entrypoint.sh          # Container startup script
├── .dockerignore                 # Files to exclude from build
├── requirements.txt              # Python dependencies
├── manage.py                     # Django management
├── dashboard/                    # Django project
├── tracker/                      # Django app
├── parser.py                     # Email parsing logic
├── ml_*.py                       # ML components
├── db.py                         # Database helpers
└── json/                         # Configuration files
    ├── patterns.json             # Required
    ├── companies.json            # Required
    ├── credentials.json          # YOU MUST ADD THIS
    └── token.json                # Created automatically
```

### Files YOU Need to Provide

1. **`json/credentials.json`** - Your Gmail OAuth credentials
2. **`.env`** - Environment configuration (copy from `.env.example`)

---

## 🚀 Step-by-Step Installation

### Step 1: Verify Docker Desktop is Running

1. Open Docker Desktop
2. Wait for the whale icon in system tray to show "Docker Desktop is running"
3. Verify in PowerShell:

```powershell
docker --version
docker-compose --version
```

You should see output like:
```
Docker version 28.4.0, build d8eb465
Docker Compose version v2.39.4-desktop.1
```

---

### Step 2: Prepare Configuration Files

#### A. Create Environment File

```powershell
# Navigate to your project
cd C:\Users\kaver\code\GmailJobTracker

# Copy the example environment file
Copy-Item .env.example .env

# Open .env in your editor
notepad .env
```

**Edit `.env` and set AT MINIMUM:**
```bash
# RECOMMENDED: Generate a new secret key
DJANGO_SECRET_KEY=your-random-secret-key-here

# OPTIONAL: Gmail label organization (default: #job-hunt)
GMAIL_ROOT_FILTER_LABEL=#job-hunt

# OPTIONAL: Other settings (defaults are fine)
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
```

**How to get DJANGO_SECRET_KEY:**

Generate a new secret key using Python:
```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Example output:
```
django-insecure-xy9#2k$mz@4n8v!p7q&r3s*t6u+w-a=b%c^d_e(f)g{h|i}j
```

Copy this entire string and paste it in your `.env` file:
```bash
DJANGO_SECRET_KEY=django-insecure-xy9#2k$mz@4n8v!p7q&r3s*t6u+w-a=b%c^d_e(f)g{h|i}j
```

**⚠️ Important:** Keep this secret! Never share it or commit it to git.

#### B. Add Gmail Credentials

```powershell
# Copy your Gmail API credentials file to the json directory
Copy-Item "path\to\your\downloaded\credentials.json" "json\credentials.json"

# Verify it exists
Test-Path json\credentials.json
# Should return: True
```

**Where to get `credentials.json`:**
1. Go to Google Cloud Console: https://console.cloud.google.com
2. Create/select a project
3. Enable Gmail API
4. Create OAuth 2.0 credentials (Desktop app)
5. Download the credentials JSON file

---

### Step 3: Validate Your Setup

```powershell
# Run the validation script
python validate_deployment.py
```

You should see:
```
✅ All critical checks passed!
📦 Ready for deployment!
```

If you see warnings about environment variables not being set, that's OK if you put them in `.env` file.

---

### Step 4: Build the Docker Image

This creates the Docker container image with your application:

```powershell
# Build the image (this takes 5-10 minutes first time)
docker-compose build

# You'll see output like:
# [+] Building 245.3s (18/18) FINISHED
```

**What happens during build:**
- Downloads Python 3.11 base image
- Installs all Python dependencies from `requirements.txt`
- Copies your application code
- Downloads spaCy language model
- Collects Django static files
- Creates a non-root user for security

---

### Step 5: Start the Container

```powershell
# Start the container in detached mode (background)
docker-compose up -d

# You'll see:
# [+] Running 2/2
#  ✔ Network gmailjobtracker_gmailtracker-network  Created
#  ✔ Container gmailtracker                        Started
```

**What happens during startup:**
- Checks for required files
- Runs database migrations
- Creates default superuser (username: admin, password: changeme123)
- Collects static files
- Starts Django server on port 8000

---

### Step 6: Verify Container is Running

```powershell
# Check container status
docker-compose ps

# You should see:
# NAME            IMAGE                  STATUS
# gmailtracker    gmailjobtracker-web    Up (healthy)
```

```powershell
# View startup logs
docker-compose logs web

# You should see:
# ✅ Initialization complete!
# 🌐 Application will start on http://0.0.0.0:8000
```

---

### Step 7: Access Your Application

1. **Open your browser** to: http://localhost:8000

2. **Log in to admin panel**: http://localhost:8000/admin
   - Username: `admin`
   - Password: `changeme123`
   - ⚠️ **CHANGE THIS PASSWORD IMMEDIATELY!**

3. **Change the default password:**
```powershell
docker-compose exec web python manage.py changepassword admin
```

---

### Step 8: Initial Gmail Authentication

The first time you ingest emails, you'll need to authenticate with Gmail:

```powershell
# Run the ingest command
docker-compose exec web python manage.py ingest_gmail --days-back 7
```

**If you see an authentication prompt:**
1. The container will generate an OAuth URL
2. Copy the URL and paste it in your browser
3. Log in to your Gmail account
4. Authorize the application
5. Copy the authorization code
6. Paste it back in the terminal

The authentication token will be saved to `json/token.json` for future use.

---

## 🎛️ Common Operations

### View Logs
```powershell
# Real-time logs (Ctrl+C to exit)
docker-compose logs -f web

# Last 100 lines
docker-compose logs --tail=100 web
```

### Access Container Shell
```powershell
# Open bash shell inside container
docker-compose exec web bash

# Inside container, you can run:
python manage.py shell
python manage.py dbshell
exit  # to leave container
```

### Stop the Application
```powershell
# Stop containers (keeps data)
docker-compose down

# Stop and remove volumes (DELETES DATA!)
docker-compose down -v
```

### Restart the Application
```powershell
docker-compose restart
```

### Ingest Gmail Messages
```powershell
# Ingest last 7 days (default)
docker-compose exec web python manage.py ingest_gmail

# Ingest last 30 days
docker-compose exec web python manage.py ingest_gmail --days-back 30

# Force re-ingest
docker-compose exec web python manage.py ingest_gmail --force
```

### Train ML Model
```powershell
# After labeling messages in admin panel
docker-compose exec web python train_model.py --verbose
```

### Backup Your Data
```powershell
# Run backup script
.\docker.ps1 backup

# Or manually:
$date = Get-Date -Format "yyyyMMdd"
New-Item -ItemType Directory -Force -Path "backups\$date"
docker-compose exec web sqlite3 /app/db/job_tracker.db ".backup '/app/db/backup.db'"
Copy-Item "db\backup.db" "backups\$date\job_tracker.db"
```

---

## 📂 Data Persistence

Your data is stored in these directories (mapped from container to host):

```
GmailJobTracker/
├── db/                    # SQLite database (persistent)
├── logs/                  # Application logs (persistent)
├── model/                 # ML model files (persistent)
└── json/
    ├── credentials.json   # OAuth credentials (persistent)
    └── token.json         # OAuth token (persistent)
```

**Important:** These directories are mounted as Docker volumes, so your data persists even if you:
- Stop the container
- Restart your computer
- Rebuild the image

---

## 🔍 Troubleshooting

### Container Won't Start

**Check logs:**
```powershell
docker-compose logs web
```

**Common issues:**
- Missing `json/credentials.json` - Add your Gmail credentials
- Missing `.env` file - Copy from `.env.example`
- Port 8000 already in use - Stop other services or change port in `docker-compose.yml`

**Solution:**
```powershell
docker-compose down
docker-compose up -d --build
```

---

### Can't Access http://localhost:8000

**Check if container is running:**
```powershell
docker-compose ps
```

**Check if port is accessible:**
```powershell
# Test connection
curl http://localhost:8000
```

**If using WSL2:**
- Docker Desktop on Windows with WSL2 backend should work automatically
- Try: http://127.0.0.1:8000

**Firewall issues:**
- Check Windows Firewall settings
- Allow Docker Desktop through firewall

---

### Gmail Authentication Fails

**Remove old token:**
```powershell
Remove-Item json\token.json -Force
docker-compose restart web
```

**Re-authenticate:**
```powershell
docker-compose exec web python manage.py ingest_gmail
```

---

### Database Locked Error

**Stop all containers:**
```powershell
docker-compose down
```

**Remove lock files:**
```powershell
Remove-Item db\.*.lock -Force
```

**Restart:**
```powershell
docker-compose up -d
```

---

### Permission Errors

**On Windows, this is rare, but if it happens:**

```powershell
# Ensure you have write permissions to project directory
icacls . /grant ${env:USERNAME}:F /t
```

---

## 🔄 Updating the Application

### Update to Latest Code

```powershell
# Pull latest code
git pull origin main

# Rebuild container
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Run migrations
docker-compose exec web python manage.py migrate
```

---

## 🎯 Quick Reference Commands

### Using PowerShell Helper Script

```powershell
.\docker.ps1 help          # Show all commands
.\docker.ps1 install       # First-time setup
.\docker.ps1 up            # Start containers
.\docker.ps1 down          # Stop containers
.\docker.ps1 logs          # View logs
.\docker.ps1 shell         # Open shell
.\docker.ps1 ingest        # Ingest Gmail
.\docker.ps1 train         # Train ML model
.\docker.ps1 backup        # Backup data
.\docker.ps1 test          # Run tests
.\docker.ps1 clean         # Clean up
```

### Using Docker Compose Directly

```powershell
docker-compose build       # Build image
docker-compose up -d       # Start in background
docker-compose down        # Stop and remove
docker-compose ps          # Show status
docker-compose logs -f     # Follow logs
docker-compose restart     # Restart containers
docker-compose exec web bash  # Shell access
```

---

## 📊 Docker Desktop GUI

You can also manage containers through Docker Desktop GUI:

1. **Open Docker Desktop**
2. **Go to Containers tab**
3. **Find "gmailtracker" container**
4. **Click on it to see:**
   - Logs (real-time)
   - Stats (CPU, memory usage)
   - Exec (open shell)
   - Files (browse container filesystem)

**Actions available:**
- ▶️ Start
- ⏸️ Stop
- 🔄 Restart
- 🗑️ Delete
- 📊 Stats

---

## ✅ Verification Checklist

After installation, verify everything works:

- [ ] Docker Desktop is running
- [ ] `docker-compose ps` shows container as "Up (healthy)"
- [ ] http://localhost:8000 loads the dashboard
- [ ] http://localhost:8000/admin loads admin panel
- [ ] Can log in with admin credentials
- [ ] Can ingest Gmail messages
- [ ] Data persists after `docker-compose restart`
- [ ] Logs visible with `docker-compose logs`

---

## 🆘 Getting Help

If you encounter issues:

1. **Check logs:** `docker-compose logs web`
2. **Run validation:** `python validate_deployment.py`
3. **Check documentation:** `DOCKER_DEPLOYMENT.md`
4. **Docker Desktop logs:** Settings → Troubleshoot → View logs

---

## 🎉 Success!

You now have GmailJobTracker running in Docker Desktop!

**Next steps:**
1. Change admin password
2. Ingest your Gmail messages
3. Label some messages in admin panel
4. Train the ML model
5. Enjoy automated job application tracking!

---

*For advanced deployment options, see `DOCKER_DEPLOYMENT.md`*
