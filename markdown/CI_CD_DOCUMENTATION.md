# CI/CD Pipeline Documentation

This document describes the Continuous Integration and Continuous Deployment (CI/CD) pipeline for GmailJobTracker.

## 🔄 Pipeline Overview

The CI/CD pipeline is implemented using GitHub Actions and consists of four main jobs:

1. **Lint & Code Quality** - Code formatting and security checks
2. **Test** - Automated testing with coverage
3. **Build** - Docker image build and push to registry
4. **Deploy** - Deployment artifact creation

## 🎯 Trigger Events

The pipeline runs on:
- **Push** to `main` or `develop` branches
- **Pull Requests** targeting `main` or `develop`
- **Release** publication (tagged releases)

## 📊 Pipeline Jobs

### 1. Lint & Code Quality

**Purpose:** Ensure code quality and security standards

**Steps:**
- Run Black formatter check (PEP 8 compliance)
- Run Flake8 linter (syntax errors)
- Run detect-secrets scan (credential leak detection)

**When it runs:** On every push and PR

**Configuration:**
```yaml
# .flake8 (create this file if needed)
[flake8]
max-line-length = 120
exclude = .git,__pycache__,venv,migrations
ignore = E203,W503
```

### 2. Test

**Purpose:** Run automated tests with coverage reporting

**Steps:**
- Install dependencies
- Download spaCy model
- Create test environment
- Run Django migrations
- Execute pytest with coverage
- Upload coverage to Codecov

**When it runs:** After lint job succeeds

**Test Command:**
```bash
pytest --cov=tracker --cov=. --cov-report=xml --cov-report=html
```

**Coverage Threshold:** 70% recommended

### 3. Build

**Purpose:** Build Docker image and push to GitHub Container Registry

**Steps:**
- Set up Docker Buildx (multi-platform builds)
- Log in to GitHub Container Registry (ghcr.io)
- Extract metadata for tags
- Build and push Docker image
- Run Docker Scout CVE scan

**When it runs:** After test job succeeds

**Image Tags:**
- `latest` - Latest main branch build
- `main-<sha>` - Specific commit on main
- `develop-<sha>` - Specific commit on develop
- `v1.2.3` - Semantic version tags (on releases)

**Platforms:** linux/amd64, linux/arm64

**Registry:** `ghcr.io/cyberthreatgurl/gmailjobtracker`

### 4. Deploy

**Purpose:** Create deployment artifacts and documentation

**Steps:**
- Create deployment package (docker-compose, configs)
- Upload artifact to GitHub
- Generate release notes (for releases)
- Comment on PR with deployment status

**When it runs:** On release publication or push to main branch

**Artifact Contents:**
- `docker-compose.yml`
- `.env.template`
- Configuration files (json/)
- Deployment instructions

## 🔐 Secrets & Environment Variables

### Required Secrets

Configure in GitHub repository settings (Settings → Secrets and variables → Actions):

| Secret | Description | Required |
|--------|-------------|----------|
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions | ✅ Auto |
| `CODECOV_TOKEN` | Codecov upload token | ⚠️ Optional |

### Environment Variables

Set in `.env` file (not in repo, used locally):
- See `.env.example` for all variables
- Required: `DJANGO_SECRET_KEY`

## 📦 Docker Registry

### GitHub Container Registry (GHCR)

Images are automatically pushed to: `ghcr.io/cyberthreatgurl/gmailjobtracker`

**Pull an image:**
```bash
docker pull ghcr.io/cyberthreatgurl/gmailjobtracker:latest
```

**Authentication (if private):**
```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

### Making Registry Public

1. Go to package settings: https://github.com/users/cyberthreatgurl/packages/container/gmailjobtracker/settings
2. Click "Change visibility"
3. Select "Public"
4. Confirm

## 🧪 Local Testing

### Test Lint Job

```bash
# Install lint tools
pip install black flake8 detect-secrets

# Run black check
black --check .

# Run flake8
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Run detect-secrets
detect-secrets scan --baseline .secrets.baseline
```

### Test Build Job

```bash
# Build Docker image locally
docker build -t gmailtracker:test .

# Test the image
docker run --rm gmailtracker:test python manage.py check
```

### Test Entire Pipeline Locally

Use [act](https://github.com/nektos/act) to run GitHub Actions locally:

```bash
# Install act
# On Windows (with Chocolatey)
choco install act-cli

# On macOS
brew install act

# Run all jobs
act

# Run specific job
act -j test

# Run with secrets
act --secret-file .env
```

## 🚀 Deployment Workflow

### Automated Deployment (Main Branch)

```bash
# Merge to main triggers automatic build
git checkout main
git merge develop
git push origin main

# Pipeline automatically:
# 1. Runs tests
# 2. Builds Docker image
# 3. Pushes to ghcr.io
# 4. Creates deployment artifact
```

### Release Deployment

```bash
# Create a release tag
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0

# Or create release via GitHub UI:
# Releases → Draft a new release → Create tag → Publish

# Pipeline automatically:
# 1. Runs full test suite
# 2. Builds multi-platform images
# 3. Tags with semantic version
# 4. Creates deployment package
# 5. Generates release notes
```

### Manual Deployment

Download deployment artifact from GitHub Actions:
1. Go to Actions tab
2. Click on successful workflow run
3. Download "deployment-package" artifact
4. Extract and deploy:

```bash
tar -xzf gmailtracker-deploy.tar.gz
cd deploy
cp .env.template .env
# Edit .env with your settings
docker-compose up -d
```

## 🔍 Monitoring Pipeline Status

### GitHub Actions Dashboard

View at: `https://github.com/cyberthreatgurl/GmailJobTracker/actions`

**Status badges** (add to README.md):
```markdown
![CI/CD](https://github.com/cyberthreatgurl/GmailJobTracker/actions/workflows/ci-cd.yml/badge.svg)
![Docker](https://img.shields.io/docker/pulls/cyberthreatgurl/gmailjobtracker)
[![codecov](https://codecov.io/gh/cyberthreatgurl/GmailJobTracker/branch/main/graph/badge.svg)](https://codecov.io/gh/cyberthreatgurl/GmailJobTracker)
```

### Email Notifications

Configure in GitHub settings:
- Settings → Notifications → Actions
- Enable "Send notifications for failed workflows only"

## 🐛 Troubleshooting

### Pipeline Failures

**Lint failures:**
```bash
# Fix locally
black .  # Auto-format
flake8 . --show-source
```

**Test failures:**
```bash
# Run locally
pytest -v
pytest --lf  # Re-run last failed
```

**Build failures:**
```bash
# Check Docker build
docker build -t test .

# Check for large files
find . -type f -size +100M

# Check .dockerignore
cat .dockerignore
```

### Authentication Issues

**Docker registry push fails:**
- Check `GITHUB_TOKEN` has package write permissions
- Verify organization/repo settings allow GHCR

**Codecov upload fails:**
- Codecov token may be required for private repos
- Add `CODECOV_TOKEN` to repository secrets

### Cache Issues

**Stale dependencies:**
```yaml
# Force cache refresh in workflow
- uses: actions/setup-python@v5
  with:
    cache: 'pip'
    cache-dependency-path: '**/requirements.txt'
```

**Docker layer caching:**
```yaml
# Clear cache by changing cache key
cache-from: type=gha,scope=main-v2
cache-to: type=gha,mode=max,scope=main-v2
```

## 📈 Performance Optimization

### Parallel Jobs

Jobs run in parallel when possible:
- `lint` and `test` run independently
- `build` waits for `test`
- `deploy` waits for `build`

### Caching Strategy

**Python dependencies:**
```yaml
- uses: actions/setup-python@v5
  with:
    cache: 'pip'  # Caches pip packages
```

**Docker layers:**
```yaml
cache-from: type=gha  # Uses GitHub Actions cache
cache-to: type=gha,mode=max
```

### Build Matrix (Future Enhancement)

Test on multiple Python versions:
```yaml
test:
  strategy:
    matrix:
      python-version: [3.10, 3.11, 3.12]
  steps:
    - uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
```

## 🔄 Continuous Improvement

### Planned Enhancements

- [ ] Add integration tests
- [ ] Implement staging environment
- [ ] Add performance benchmarks
- [ ] Set up automatic dependency updates (Dependabot)
- [ ] Add security scanning (Snyk, Trivy)
- [ ] Implement blue-green deployments
- [ ] Add rollback automation

### Metrics to Track

- Build time (target: < 5 minutes)
- Test coverage (target: > 80%)
- Docker image size (target: < 500MB)
- Deployment success rate (target: > 95%)

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Build Documentation](https://docs.docker.com/build/)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Codecov Documentation](https://docs.codecov.com/)
