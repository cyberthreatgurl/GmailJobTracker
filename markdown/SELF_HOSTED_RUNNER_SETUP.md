# Self-Hosted GitHub Actions Runner Setup

Since your docker-server.shaw.local is behind a NAT firewall, you need a self-hosted runner to enable automated deployments.

## 🎯 What is a Self-Hosted Runner?

A GitHub Actions runner that runs on your own infrastructure (docker-server.shaw.local) instead of GitHub's cloud. It can access your local network resources.

## 📋 Prerequisites

- Docker server running Linux
- User with Docker permissions (kelly)
- Internet access from docker-server

## 🚀 Installation Steps

### 1. Navigate to GitHub Settings

Go to your repository settings:
```
https://github.com/cyberthreatgurl/GmailJobTracker/settings/actions/runners/new
```

Or manually:
1. Go to repository page
2. Click **Settings** tab
3. Click **Actions** → **Runners** (left sidebar)
4. Click **New self-hosted runner**

### 2. Select Linux x64

Choose:
- **Runner image**: Linux
- **Architecture**: x64

### 3. Install on docker-server.shaw.local

SSH into your Docker server:

```bash
ssh kelly@docker-server.shaw.local
cd ~
```

Follow the exact commands shown on GitHub (they include your specific token). They'll look like:

```bash
# Create a folder
mkdir actions-runner && cd actions-runner

# Download the latest runner package
curl -o actions-runner-linux-x64-2.XXX.X.tar.gz -L \
  https://github.com/actions/runner/releases/download/vX.XXX.X/actions-runner-linux-x64-2.XXX.X.tar.gz

# Extract the installer
tar xzf ./actions-runner-linux-x64-2.XXX.X.tar.gz
```

### 4. Configure the Runner

```bash
# Configure with the token from GitHub
./config.sh --url https://github.com/cyberthreatgurl/GmailJobTracker --token YOUR_TOKEN_HERE

# When prompted:
# - Runner group: Default
# - Runner name: docker-server (or leave default)
# - Work folder: _work (default)
# - Labels: self-hosted,Linux,X64 (default)
```

### 5. Install as a Service (Recommended)

This ensures the runner starts automatically on boot:

```bash
# Install the service
sudo ./svc.sh install

# Start the service
sudo ./svc.sh start

# Check status
sudo ./svc.sh status
```

### 6. Verify Installation

On GitHub, go back to:
```
https://github.com/cyberthreatgurl/GmailJobTracker/settings/actions/runners
```

You should see your runner listed as **"Idle"** (green dot).

## ✅ Testing the Deployment

### Test Workflow Trigger

```bash
# On your Mac
cd ~/code/GmailJobTracker
git commit --allow-empty -m "Test self-hosted runner deployment"
git push
```

Watch the Actions tab:
```
https://github.com/cyberthreatgurl/GmailJobTracker/actions
```

The **"Build Docker Image"** job runs on GitHub's cloud runners.
The **"Deploy"** job runs on your self-hosted runner.

## � Running Python Scripts & Management Commands

> **Important:** All Python dependencies (`requirements.txt`) are installed **inside the Docker container**, not on the host machine. Running scripts directly with `python3` on the host will fail with `ModuleNotFoundError`.

### ✅ Correct: Run commands inside the container

```bash
# Run any management command
docker exec -it gmailtracker python manage.py ingest_gmail --days-back 7

# Re-authenticate Gmail OAuth (generates token.pickle)
docker exec -it gmailtracker python gmail_auth.py

# Open an interactive shell inside the container
docker exec -it gmailtracker bash

# Reclassify all messages
docker exec -it gmailtracker python manage.py reclassify_messages

# Run migrations
docker exec -it gmailtracker python manage.py migrate
```

### ❌ Wrong: Running directly on the host

```bash
# This will fail — host has no project dependencies installed
python3 gmail_auth.py   # ModuleNotFoundError: No module named 'google'
```

### 🔑 Re-authenticating Gmail OAuth

The `token.pickle` file stores your active Gmail OAuth session. If it expires or is missing, re-authenticate **inside the container**:

```bash
docker exec -it gmailtracker python gmail_auth.py
```

Then copy the generated token out of the container to persist it across container restarts (since `model/` is volume-mounted, `token.pickle` already persists if it lives at `/app/model/token.pickle`):

```bash
# Verify token location inside container
docker exec -it gmailtracker ls /app/model/token.pickle
```

---

## �🔧 Troubleshooting

### Runner Not Starting

```bash
# Check service status
sudo ./svc.sh status

# View logs
sudo journalctl -u actions.runner.* -f
```

### Runner Shows "Offline"

```bash
# Restart the service
sudo ./svc.sh stop
sudo ./svc.sh start
```

### Permission Issues

Ensure the runner user can run Docker:

```bash
# Add runner user to docker group
sudo usermod -aG docker $(whoami)

# Restart runner service
sudo ./svc.sh restart
```

### Docker Compose Not Found

```bash
# Install docker-compose
sudo apt-get update
sudo apt-get install docker-compose-plugin

# Or install standalone
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

## 🛠️ Management Commands

```bash
# Check runner status
sudo ./svc.sh status

# View runner logs
sudo journalctl -u actions.runner.* -f

# Stop runner
sudo ./svc.sh stop

# Start runner
sudo ./svc.sh start

# Restart runner
sudo ./svc.sh restart

# Uninstall runner
sudo ./svc.sh uninstall
```

## 🔒 Security Considerations

**✅ Good:**
- Runner only pulls images from trusted registry (ghcr.io)
- No inbound connections required
- Runner connects outbound to GitHub (port 443)
- No SSH keys needed in GitHub Secrets

**⚠️ Important:**
- Runner has full access to docker-server
- Only use for trusted repositories
- Keep runner updated regularly

## 🔄 Updating the Runner

```bash
cd ~/actions-runner

# Stop the service
sudo ./svc.sh stop

# Download latest version
curl -o actions-runner-linux-x64-2.XXX.X.tar.gz -L \
  https://github.com/actions/runner/releases/latest/download/actions-runner-linux-x64-2.XXX.X.tar.gz

# Extract (overwrites old version)
tar xzf ./actions-runner-linux-x64-2.XXX.X.tar.gz

# Start the service
sudo ./svc.sh start
```

## 📊 Monitoring

### Check Runner Health

```bash
# View recent jobs
ls -lh ~/actions-runner/_work/_actions/

# Check Docker containers
docker ps -a

# View application logs
cd /home/kelly/apps/GmailJobTracker
docker-compose logs -f
```

### GitHub Actions Dashboard

View runner activity:
```
https://github.com/cyberthreatgurl/GmailJobTracker/settings/actions/runners
```

## 🎯 Alternative: Pull-Based Deployment (No Runner Needed)

If you prefer not to run a self-hosted runner, use this pull-based approach:

### Option: Watchtower (Auto-Update Containers)

Add to your docker-compose.yml:

```yaml
services:
  watchtower:
    image: containrrr/watchtower
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - WATCHTOWER_POLL_INTERVAL=300  # Check every 5 minutes
      - WATCHTOWER_CLEANUP=true
    command: gmailtracker  # Only watch specific container
```

This automatically pulls and updates when new images are pushed.

### Option: Cron Job

```bash
# Create update script
cat > ~/update-gmailtracker.sh << 'EOF'
#!/bin/bash
cd /home/kelly/apps/GmailJobTracker
echo "$GITHUB_TOKEN" | docker login ghcr.io -u cyberthreatgurl --password-stdin
docker-compose pull
docker-compose up -d
docker image prune -f
EOF

chmod +x ~/update-gmailtracker.sh

# Add to crontab (runs every 15 minutes)
crontab -e
# Add: */15 * * * * /home/kelly/update-gmailtracker.sh >> /var/log/gmailtracker-update.log 2>&1
```

## 📞 Support

- GitHub Actions Docs: https://docs.github.com/en/actions/hosting-your-own-runners
- Runner Releases: https://github.com/actions/runner/releases
- Troubleshooting: https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/monitoring-and-troubleshooting-self-hosted-runners
