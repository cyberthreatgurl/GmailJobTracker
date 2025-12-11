# Deployment Setup for docker-server.shaw.local

This guide walks you through setting up automated deployment to your local Docker server.

## 🔑 Required GitHub Secrets

You need to add these secrets to your GitHub repository:

### 1. `DOCKER_SERVER_SSH_KEY`
**Private SSH key for authentication to docker-server.shaw.local**

#### Generate SSH Key (if you don't have one):
```bash
# On your local machine
ssh-keygen -t ed25519 -C "github-actions@gmailtracker" -f ~/.ssh/docker_deploy_key

# Copy the private key (you'll paste this into GitHub)
cat ~/.ssh/docker_deploy_key

# Copy the public key to your Docker server
ssh-copy-id -i ~/.ssh/docker_deploy_key.pub user@docker-server.shaw.local
```

#### Add to GitHub:
1. Go to: https://github.com/cyberthreatgurl/GmailJobTracker/settings/secrets/actions
2. Click **"New repository secret"**
3. Name: `DOCKER_SERVER_SSH_KEY`
4. Value: Paste the **entire private key** including `-----BEGIN` and `-----END` lines
5. Click **"Add secret"**

---

### 2. `DOCKER_SERVER_USER`
**Username for SSH login**

- Name: `DOCKER_SERVER_USER`
- Value: Your SSH username (e.g., `ashaw`, `docker`, `admin`)

---

### 3. `DOCKER_SERVER_DEPLOY_PATH` (Optional)
**Path where the application is deployed**

- Name: `DOCKER_SERVER_DEPLOY_PATH`
- Value: `/opt/gmailtracker` (or your preferred path)
- Default: If not set, uses `/opt/gmailtracker`

---

## 🖥️ Server Setup

On your `docker-server.shaw.local`, prepare the deployment directory:

```bash
# SSH into your Docker server
ssh user@docker-server.shaw.local

# Create deployment directory
sudo mkdir -p /opt/gmailtracker
sudo chown $USER:$USER /opt/gmailtracker
cd /opt/gmailtracker

# Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  gmailtracker:
    image: ghcr.io/cyberthreatgurl/gmailjobtracker:latest
    container_name: gmailtracker
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./db:/app/db
      - ./logs:/app/logs
      - ./json:/app/json
    env_file:
      - .env
    environment:
      - DJANGO_SETTINGS_MODULE=dashboard.settings
EOF

# Create .env file with your configuration
cp .env.example .env
nano .env  # Edit with your actual values
```

---

## 🔒 Required .env Variables

Create `/opt/gmailtracker/.env` with:

```bash
# Django
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=docker-server.shaw.local,localhost

# Gmail API
GMAIL_JOBHUNT_LABEL_ID=your-label-id

# Database (optional, uses SQLite by default)
# DATABASE_URL=postgresql://user:pass@host:5432/dbname
```

---

## 🚀 Test Deployment

### Manual Test:
```bash
# On docker-server.shaw.local
cd /opt/gmailtracker

# Login to GitHub Container Registry
echo "YOUR_GITHUB_TOKEN" | docker login ghcr.io -u cyberthreatgurl --password-stdin

# Pull and run
docker-compose pull
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f
```

### Test from GitHub Actions:
```bash
# On your local machine
git add .
git commit -m "Test deployment workflow"
git push origin main

# Watch the Actions tab on GitHub
# https://github.com/cyberthreatgurl/GmailJobTracker/actions
```

---

## 🔍 Troubleshooting

### SSH Connection Issues
```bash
# Test SSH connection manually
ssh -i ~/.ssh/docker_deploy_key user@docker-server.shaw.local

# Check SSH logs on server
sudo tail -f /var/log/auth.log
```

### Docker Login Issues
```bash
# Generate a GitHub Personal Access Token with `read:packages` permission
# https://github.com/settings/tokens
```

### Deployment Verification
```bash
# Check running containers
ssh user@docker-server.shaw.local "docker ps"

# View logs
ssh user@docker-server.shaw.local "cd /opt/gmailtracker && docker-compose logs -f"
```

---

## 📋 Deployment Workflow

When you push to `main` branch:

1. ✅ **Build** - Docker image built and pushed to GHCR
2. ✅ **Deploy** - GitHub Actions SSHs to docker-server.shaw.local
3. ✅ **Pull** - Latest image pulled from registry
4. ✅ **Restart** - Containers stopped, removed, and recreated
5. ✅ **Verify** - Deployment status checked

---

## 🛡️ Security Best Practices

1. **Use SSH keys** (not passwords) ✅
2. **Restrict SSH key permissions** to deployment directory only
3. **Use GitHub's built-in GITHUB_TOKEN** for container registry auth
4. **Store secrets in GitHub Secrets** (never commit to repo)
5. **Use firewall** to restrict access to docker-server.shaw.local
6. **Enable SSH key-only auth** (disable password auth)

---

## 🎯 Next Steps

1. [ ] Generate SSH key pair
2. [ ] Add public key to docker-server.shaw.local
3. [ ] Add secrets to GitHub repository
4. [ ] Set up deployment directory on server
5. [ ] Create .env file with configuration
6. [ ] Test manual deployment
7. [ ] Push to main branch to trigger automated deployment

---

## 📞 Support

If deployment fails, check:
- GitHub Actions logs: https://github.com/cyberthreatgurl/GmailJobTracker/actions
- Server logs: `ssh user@docker-server.shaw.local "docker-compose logs"`
- SSH connectivity: `ssh -vvv user@docker-server.shaw.local`
