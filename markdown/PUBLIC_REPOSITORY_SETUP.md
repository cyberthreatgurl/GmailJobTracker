# Making Repository Public While Protecting CI/CD Workflows

This guide explains how to open the GmailJobTracker repository to the public while keeping your CI/CD deployment workflows and credentials secure.

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Step-by-Step Instructions](#step-by-step-instructions)
4. [GitHub Secrets Configuration](#github-secrets-configuration)
5. [Environment Protection Rules](#environment-protection-rules)
6. [Workflow Security Patterns](#workflow-security-patterns)
7. [Verification Steps](#verification-steps)
8. [Troubleshooting](#troubleshooting)

---

## Overview

**Goal**: Make the repository publicly visible while ensuring:
- CI/CD workflows remain private and controlled
- Deployment credentials are never exposed
- Only authorized users can trigger deployments
- Workflow runs are visible only to repository collaborators

**Key Strategy**: Use GitHub's environment protection rules, secrets management, and workflow permissions to create security boundaries.

---

## Prerequisites

Before making your repository public, ensure you have:

- [ ] Repository admin access
- [ ] All deployment credentials identified
- [ ] Current CI/CD workflows documented
- [ ] List of authorized deployers (GitHub usernames)
- [ ] Backup of current repository settings

---

## Step-by-Step Instructions

### Phase 1: Audit and Secure Credentials

#### 1.1 Identify All Secrets in Workflows

Review all workflow files in `.github/workflows/` and list every secret:

```bash
# Find all secrets referenced in workflows
grep -r "secrets\." .github/workflows/
```

**Current secrets in this repository (as of Dec 2025):**
- ✅ `secrets.GITHUB_TOKEN` - Automatically provided by GitHub (safe, no action needed)
- ✅ No deployment secrets currently used
- ✅ No custom API keys or credentials

**If you add deployment workflows in the future, you may need:**
- Azure/AWS credentials (if deploying to cloud)
- Database credentials (if using hosted database)
- API keys for external services

#### 1.2 Document Current Workflow Behavior

For each workflow file, document:
- What it deploys/does
- Which secrets it uses
- When it runs (triggers)
- Who should be able to run it

---

### Phase 2: Configure GitHub Secrets

#### 2.1 Move Secrets to Repository Secrets

1. Go to **Repository Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** for each credential
3. Name secrets using UPPERCASE_WITH_UNDERSCORES format
4. Paste secret values (never commit these!)

**Example secrets to create:**

| Secret Name | Description | Where to Find |
|-------------|-------------|---------------|
| `AZURE_CREDENTIALS` | Service principal JSON | Azure Portal → App Registrations |
| `AZURE_SUBSCRIPTION_ID` | Subscription GUID | Azure Portal → Subscriptions |
| `AZURE_RESOURCE_GROUP` | Resource group name | Azure Portal |
| `AZURE_TENANT_ID` | Azure AD tenant ID | Azure Portal → Azure Active Directory |
| `GMAIL_CREDENTIALS_JSON` | Gmail API credentials | Google Cloud Console |
| `USER_EMAIL_ADDRESS` | Your email for filtering | Your email |

#### 2.2 Update Workflows to Use Secrets

Ensure workflows reference secrets correctly:

```yaml
env:
  AZURE_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
  AZURE_RESOURCE_GROUP: ${{ secrets.AZURE_RESOURCE_GROUP }}

steps:
  - name: Azure Login
    uses: azure/login@v1
    with:
      creds: ${{ secrets.AZURE_CREDENTIALS }}
```

**⚠️ Never hardcode credentials:**
```yaml
# ❌ NEVER DO THIS
env:
  API_KEY: "abc123-hardcoded-key"  # Exposed in public repo!

# ✅ DO THIS INSTEAD
env:
  API_KEY: ${{ secrets.API_KEY }}
```

---

### Phase 3: Create Protected Environments (Optional - Public Repos Only)

**⚠️ Important:** Environment protection rules (required reviewers) are only available for:
- Public repositories (all GitHub accounts)
- Private repositories on GitHub Pro/Team/Enterprise

**If your repo is currently private on a free account:** Skip to Phase 6 and make it public first, then return here to configure environments.

#### 3.1 Create Production Environment

1. Go to **Repository Settings** → **Environments**
2. Click **New environment**
3. Name it `production` and click **Configure environment**
   - This automatically opens the environment configuration page

#### 3.2 Configure Deployment Branches (Available Now)

**Deployment Branches:**
1. Under "Deployment branches and tags", click dropdown
2. Select **Selected branches and tags**
3. Click **Add deployment branch or tag rule**
4. Enter pattern: `main` (or `refs/heads/main`)
5. Click **Add rule**
6. This prevents deployments from forks or unauthorized branches

#### 3.3 Configure Environment Protection Rules (Only After Going Public)

**After making repository public**, you'll see a new section called "Deployment protection rules":

**Required Reviewers:**
1. Under "Deployment protection rules", enable **Required reviewers**
2. Add your GitHub username and any trusted collaborators
3. Set "Wait timer" to 0 minutes (or add delay if desired)

**Note:** This section will NOT appear until the repository is public (on free accounts).

#### 3.3 Add Environment Secrets

1. In the environment configuration, scroll to **Environment secrets**
2. Click **Add secret** for each deployment credential
3. Environment secrets override repository secrets when workflow uses that environment

**When to use environment secrets:**
- Production credentials different from dev/staging
- Multi-environment deployments (dev, staging, prod)
- Extra-sensitive credentials needing approval

---

### Phase 4: Update Workflow Files for Security

#### 4.1 Add Environment Protection to Deployment Workflows

Update `.github/workflows/deploy.yml` (or similar) to use the protected environment:

```yaml
name: Deploy to Azure

on:
  workflow_dispatch:  # Manual trigger only
    inputs:
      environment:
        description: 'Environment to deploy to'
        required: true
        default: 'production'

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production  # ← This enforces protection rules!
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Azure Login
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      
      # ... rest of deployment steps
```

**Key points:**
- `environment: production` enforces approval requirement
- `workflow_dispatch` requires manual triggering (no automatic deployments)
- Secrets are scoped to the environment

#### 4.2 Restrict Workflow Permissions

Add permissions block to limit what workflows can do:

```yaml
name: CI Build

on: [push, pull_request]

permissions:
  contents: read  # Read-only access to repository
  pull-requests: write  # Can comment on PRs
  # No other permissions granted

jobs:
  build:
    # ... build steps
```

**Recommended permissions for different workflows:**

| Workflow Type | Permissions |
|---------------|-------------|
| CI/Test | `contents: read` |
| PR Comments | `contents: read, pull-requests: write` |
| Deployment | `contents: read, deployments: write` |
| Release | `contents: write` (for tagging) |

#### 4.3 Disable Fork PRs from Accessing Secrets

Add this to workflows that use secrets:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  build:
    runs-on: ubuntu-latest
    # Only run on PRs from same repo, not forks
    if: github.event.pull_request.head.repo.full_name == github.repository
    
    steps:
      # ... steps that need secrets
```

Or use `pull_request_target` carefully (see [GitHub Security Best Practices](https://securitylab.github.com/research/github-actions-preventing-pwn-requests/)).

---

### Phase 5: Configure Branch Protection

Protect `main` branch from unauthorized changes:

1. Go to **Repository Settings** → **Branches**
2. Click **Add rule**
3. Branch name pattern: `main`
4. Enable these rules:

**Required Settings:**
- ✅ **Require a pull request before merging**
  - Require approvals: 1 (or more if team)
  - Dismiss stale PR approvals when new commits are pushed
- ✅ **Require status checks to pass before merging**
  - Add any CI checks (tests, linting, etc.)
- ✅ **Require conversation resolution before merging**
- ✅ **Do not allow bypassing the above settings**
  - Uncheck "Allow specified actors to bypass" (unless you need it)
- ✅ **Restrict who can push to matching branches**
  - Add only trusted maintainers

**Optional but Recommended:**
- ✅ **Require signed commits** (if using GPG)
- ✅ **Require linear history** (prevents merge commits)
- ✅ **Lock branch** (prevents any pushes - use for production tags)

---

### Phase 6: Make Repository Public

**⚠️ CRITICAL: Complete Phases 1-5 BEFORE this step!**

#### 6.1 Final Pre-Publication Checklist

**✅ Already Complete (Dec 2025):**
- [x] All secrets moved to GitHub Secrets (only `GITHUB_TOKEN` used, auto-provided)
- [x] Workflows use `secrets.*` references only
- [x] `.gitignore` excludes all credential files (`credentials.json`, `token.pickle`, `.env`)
- [x] No deployment workflows that need protection (CI/CD only builds/tests)

**⚠️ Still Need to Do:**
- [ ] Run local secret scan with `detect-secrets` (see command below)
- [ ] Review commit history for any accidentally committed secrets
- [ ] README already public-facing ✅
- [ ] Configure environment deployment branches (limit to `main`)

**📝 After Going Public (features unlock automatically):**
- [ ] Verify secret scanning is enabled (auto-enabled for public repos)
- [ ] Enable push protection if available
- [ ] Add required reviewers to `production` environment
- [ ] Test environment approval workflow
- [ ] Add deployment secrets to environment (if needed)
- [ ] Update deployment workflows to use `environment:` protection

**Quick local secret check:**
```bash
pip install detect-secrets
detect-secrets scan --exclude-files '\.git/.*|\.env|credentials\.json|token\.pickle'
```

#### 6.2 Enable Secret Scanning (After Going Public)

**⚠️ Important:** Secret scanning is only available for:
- Public repositories (all accounts) - **Enabled automatically**
- Private repositories on GitHub Advanced Security plans

**If your repo is private on a free account:** Secret scanning features will automatically become available AFTER you make the repository public.

**Steps after making repository public:**

1. Go to **Repository Settings** → **Security** (left sidebar)
2. Look for **Code security and analysis** section (appears after going public)
3. Verify **Secret scanning** is enabled (auto-enabled for public repos)
4. Enable **Push protection** if available (prevents accidental secret commits)

**Alternative: Check for secrets before going public:**

```bash
# Install detect-secrets (already in your requirements-dev.txt)
pip install detect-secrets

# Scan your repository
detect-secrets scan --exclude-files '\.git/.*|\.env|credentials\.json|token\.pickle'

# Review any findings
# False positives are OK - just verify they're not real credentials
```

#### 6.3 Make Repository Public

1. Go to **Repository Settings** → **General**
2. Scroll to **Danger Zone**
3. Click **Change visibility**
4. Select **Make public**
5. Type repository name to confirm
6. Click **I understand, change repository visibility**

**What happens immediately:**
- Repository code becomes publicly visible
- Workflow **definitions** become public (in `.github/workflows/`)
- Workflow **runs** and logs remain private to collaborators
- Secrets remain encrypted and inaccessible
- Your current workflows continue working normally (only use `GITHUB_TOKEN`)
3. Click **Change visibility**
4. Select **Make public**
5. Type repository name to confirm
6. Click **I understand, change repository visibility**

**What happens immediately:**
- Repository code becomes publicly visible
- Workflow **definitions** become public (in `.github/workflows/`)
- Workflow **runs** and logs remain private to collaborators
- Secrets remain encrypted and inaccessible

---

## GitHub Secrets Configuration

### Secret Hierarchy and Precedence

GitHub has three levels of secrets:

1. **Organization Secrets** (highest precedence)
   - Shared across multiple repositories
   - Managed by org admins

2. **Repository Secrets** (middle precedence)
   - Specific to one repository
   - Available to all workflows

3. **Environment Secrets** (lowest precedence, most specific)
   - Scoped to specific environment
   - Require environment protection to access

**Precedence rule**: Environment secrets override repository secrets, which override organization secrets.

### Secret Naming Conventions

Use clear, descriptive names:

```
✅ Good names:
AZURE_SUBSCRIPTION_ID
PROD_DATABASE_PASSWORD
GMAIL_API_CREDENTIALS_JSON
AWS_ACCESS_KEY_ID

❌ Bad names:
SECRET1
PASSWORD
KEY
CREDS
```

### Rotating Secrets

Establish a rotation schedule:

1. Generate new credential in external system (Azure, AWS, etc.)
2. Add new secret to GitHub with temporary name (e.g., `AZURE_CREDENTIALS_NEW`)
3. Update workflow to use new secret
4. Test deployment
5. Delete old secret
6. Rename new secret to standard name

**Recommended rotation frequency:**
- Production credentials: Every 90 days
- Development credentials: Every 180 days
- API keys: Per vendor requirements
- Passwords: Every 60-90 days

---

## Environment Protection Rules

### Use Cases for Environments

| Environment | Purpose | Protection Rules |
|-------------|---------|------------------|
| `development` | Dev/test deployments | None (auto-deploy on push) |
| `staging` | Pre-production testing | Optional: 1 reviewer |
| `production` | Live system | **Required**: 2 reviewers, branch rules |

### Setting Up Multiple Environments

For projects with dev/staging/prod:

```yaml
name: Multi-Environment Deploy

on:
  push:
    branches: [develop, staging, main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ github.ref == 'refs/heads/main' && 'production' || github.ref == 'refs/heads/staging' && 'staging' || 'development' }}
    
    steps:
      - name: Deploy to ${{ environment }}
        run: |
          echo "Deploying to $(environment)"
          # Deployment commands here
```

### Environment Variables vs Secrets

**Use Environment Variables for:**
- Non-sensitive configuration (region names, resource names)
- Public URLs or endpoints
- Feature flags

**Use Environment Secrets for:**
- Credentials (passwords, keys, tokens)
- Connection strings with passwords
- Private certificates

---

## Workflow Security Patterns

### Pattern 1: Manual Deployment Only

Prevent automatic deployments:

```yaml
name: Production Deploy

on:
  workflow_dispatch:  # Manual trigger only
    inputs:
      confirm:
        description: 'Type "deploy" to confirm'
        required: true

jobs:
  deploy:
    if: github.event.inputs.confirm == 'deploy'
    environment: production
    # ... deployment steps
```

### Pattern 2: Separate CI and CD

Keep build/test separate from deployment:

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: pytest

# .github/workflows/deploy.yml  
name: CD
on: workflow_dispatch  # Manual only
jobs:
  deploy:
    environment: production
    steps:
      - name: Deploy
        run: ./deploy.sh
```

### Pattern 3: Deployment Approval Workflow

Require explicit approval:

```yaml
name: Deploy with Approval

on: workflow_dispatch

jobs:
  request-approval:
    runs-on: ubuntu-latest
    environment: production-approval  # Environment with reviewers
    steps:
      - name: Request Deployment Approval
        run: echo "Approval granted, proceeding..."
  
  deploy:
    needs: request-approval
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Deploy Application
        run: ./deploy.sh
```

### Pattern 4: Conditional Secret Access

Only expose secrets when absolutely necessary:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Build without secrets
        run: npm run build
      
      - name: Deploy (with secrets)
        if: github.ref == 'refs/heads/main' && github.event_name == 'push'
        env:
          DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}
        run: npm run deploy
```

---

**Before going public, run local scans:**

```bash
# Your repository already has detect-secrets in CI/CD
# Run the same check locally:
pip install detect-secrets

# Scan for secrets in codebase
detect-secrets scan --exclude-files '\.git/.*|\.env|credentials\.json|token\.pickle'

# Search for common secret patterns manually
git grep -i "password\s*="
git grep -i "api.key"
git grep -i "secret\s*="
git grep -E "[A-Za-z0-9]{32,}"  # Long strings that might be keys

# Check commit history for leaked secrets
git log -p --all | grep -i "password"
```

**After making repository public:**

GitHub will automatically enable secret scanning (for public repos):
1. Go to **Settings** → **Security**
2. Look for **Code security and analysis** section (now visible)
3. Verify **Secret scanning** is enabled
4. Enable **Push protection** if available
```

Use GitHub's built-in secret scanning:
1. Go to **Settings** → **Security** → **Code security and analysis**
2. Enable **Secret scanning**
3. Enable **Push protection** (prevents pushes with secrets)

#### 2. Test Workflow Access Controls

1. **Create a test fork** (use another account or ask colleague)
2. Try to trigger protected workflows → Should be blocked
3. Try to view workflow run logs → Should see "Workflow run logs are private"
4. Submit a PR from fork → Should run CI but not access secrets

#### 3. Verify Environment Protection

1. Manually trigger a deployment workflow
2. Confirm approval request appears
3. Approve as authorized reviewer
4. Verify deployment succeeds
5. Check deployment logs are private to collaborators

#### 4. Test Branch Protection

1. Try to push directly to `main` → Should be blocked
2. Create PR with changes → Should require approval
3. Try to merge without checks passing → Should be blocked

---

## Troubleshooting

### "Secret not found" Error

**Symptom**: Workflow fails with error about missing secret.

**Solutions:**
1. Verify secret name matches exactly (case-sensitive!)
2. Check secret is in correct scope (repo vs environment)
3. Ensure workflow has `environment:` declaration if using environment secrets
4. For forks: Secrets are not available in fork PRs (by design)

### Workflow Stuck on "Waiting for approval"

**Symptom**: Deployment paused indefinitely.

**Solutions:**
1. Check environment has correct reviewers configured
2. Verify reviewer has permissions to approve
3. Look for approval notification in GitHub notifications
4. Check if "Wait timer" is set too high

### Public Can See Workflow Runs

**Symptom**: Workflow run history visible to non-collaborators.

**Explanation**: This is expected behavior. Workflow **definitions** and **run status** are public, but **logs** and **secrets** remain private.

**What public users see:**
- ✅ Workflow triggered (yes/no)
- ✅ Status (success/failure)
- ✅ Run duration
- ❌ Logs/output (private)
- ❌ Secret values (encrypted)

**To hide runs completely**: Keep repository private (only option).

### Deployment Fails After Going Public

**Symptom**: Workflows that worked before now fail.

**Common causes:**
1. Secrets not migrated to GitHub Secrets
2. Workflow referencing wrong secret names
3. Branch protection preventing deployment branch
4. Missing environment configuration

**Debug steps:**
1. Check workflow logs (if you have access)
2. Re-run with debug logging: Set `ACTIONS_RUNNER_DEBUG` secret to `true`
3. Verify all secrets exist in correct scope
4. Test locally with same credentials

---

## Additional Security Best Practices

### 1. Use OIDC Instead of Long-Lived Secrets

For Azure deployments, use OpenID Connect (OIDC) instead of service principal JSON:

```yaml
- name: Azure Login
  uses: azure/login@v1
  with:
    client-id: ${{ secrets.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

Benefits:
- No long-lived credentials stored
- Automatic token rotation
- Better audit trail

### 2. Audit Workflow Permissions Regularly

Monthly review:
- Which workflows have access to secrets
- Who can approve deployments
- What branches can trigger deployments

### 3. Enable GitHub Advanced Security

If available:
- **Dependabot alerts** - Vulnerable dependencies
- **Code scanning** - Security vulnerabilities
- **Secret scanning** - Exposed credentials

### 4. Monitor Workflow Activity

Set up notifications for:
- Deployment approvals requested
- Workflow failures
- Unusual activity patterns

### 5. Document for Contributors

Add to `CONTRIBUTING.md`:

```markdown
## Secrets and Credentials

⚠️ **Never commit secrets or credentials!**

- Use environment variables for configuration
- Store secrets in GitHub Secrets (for maintainers)
- Contact @maintainer if you need access to test environments
```

---

## Quick Reference

### Commands

```bash
# Check for exposed secrets in code
git grep -i "password"
git grep -E "[A-Za-z0-9]{32,}"

# View workflow runs
gh run list --workflow=deploy.yml

# Manually trigger workflow
gh workflow run deploy.yml -f environment=production

# View repository secrets (names only, not values)
gh secret list
```

### Useful GitHub URLs

- Repository Settings: `https://github.com/cyberthreatgurl/GmailJobTracker/settings`
- Secrets Management: `https://github.com/cyberthreatgurl/GmailJobTracker/settings/secrets/actions`
- Environments: `https://github.com/cyberthreatgurl/GmailJobTracker/settings/environments`
- Branch Protection: `https://github.com/cyberthreatgurl/GmailJobTracker/settings/branches`
- Security: `https://github.com/cyberthreatgurl/GmailJobTracker/settings/security_analysis`

---

## Summary Checklist

Before making your repository public:

- [ ] All credentials moved to GitHub Secrets
- [ ] No secrets in commit history
- [ ] Protected environments created and configured
- [ ] Required reviewers assigned to production environment
- [ ] Branch protection enabled on main branch
- [ ] Workflows reference `secrets.*` only
- [ ] Deployment workflows use `environment:` protection
- [ ] Fork PR workflows don't expose secrets
- [ ] Secret scanning enabled
- [ ] Push protection enabled
- [ ] Documentation updated for public audience
- [ ] `.gitignore` excludes all sensitive files

After making repository public:

- [ ] Verify secrets not exposed via search
- [ ] Test workflow access from fork
- [ ] Confirm logs are private to collaborators
- [ ] Test deployment approval process
- [ ] Monitor for leaked secrets alerts
- [ ] Review contributor access levels

---

## Additional Resources

- [GitHub Encrypted Secrets Documentation](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [GitHub Environments Documentation](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)
- [GitHub Security Hardening](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [Branch Protection Rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/about-protected-branches)

---

**Last Updated**: December 17, 2025  
**Repository**: GmailJobTracker  
**Maintainer**: @cyberthreatgurl
