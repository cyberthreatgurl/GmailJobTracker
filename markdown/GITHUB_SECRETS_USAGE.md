# Using GitHub Secrets in GmailJobTracker

## Overview

GitHub Secrets allow you to use sensitive credentials in GitHub Actions workflows without exposing them in code. This guide covers how to use them in this project.

---

## ⚠️ Important Clarification

**For local/home hosting (your current setup):**
- You **DO NOT** need GitHub Secrets for production
- Your local `json/credentials.json` file works as-is
- GitHub Secrets are only for CI/CD workflows and Codespaces

**Use GitHub Secrets when:**
- Running integration tests in GitHub Actions
- Testing Gmail API functionality in CI
- Developing in GitHub Codespaces
- Contributing via forks (maintainer-only tests)

---

## 📦 Currently Configured Secrets

### `GMAIL_CREDENTIALS_JSON`

**Purpose:** Gmail API OAuth 2.0 client credentials for CI testing

**Format:** Raw JSON content of your `json/credentials.json` file

**Where it's used:**
- `.github/workflows/ci-cd.yml` - Creates credentials file for tests

**How to update:**
1. Go to [Repository Settings → Secrets](https://github.com/cyberthreatgurl/GmailJobTracker/settings/secrets/actions)
2. Edit `GMAIL_CREDENTIALS_JSON`
3. Paste entire contents of your local `json/credentials.json`
4. Save

---

## 🔧 How It Works in CI/CD

### Workflow Step Breakdown

```yaml
- name: Setup Gmail credentials (if available)
  if: ${{ secrets.GMAIL_CREDENTIALS_JSON != '' }}
  run: |
    echo '${{ secrets.GMAIL_CREDENTIALS_JSON }}' > json/credentials.json
  continue-on-error: true
```

**What this does:**
1. Checks if secret exists (optional - won't fail if missing)
2. Writes secret content to `json/credentials.json` in workflow runner
3. Continues even if step fails (doesn't break CI for forks)

**Security notes:**
- File only exists in workflow runner (ephemeral, deleted after run)
- Never visible in logs (GitHub automatically masks secrets)
- Fork PRs cannot access this secret (by design)

---

## 🧪 Testing Gmail Integration in CI

### Option 1: Mock Gmail API (Recommended for Public CI)

Most tests should use mocked Gmail responses:

```python
# tests/test_gmail_integration.py
from unittest.mock import Mock, patch

@patch('gmail_api.authenticate_gmail')
def test_ingest_message(mock_auth):
    """Test message ingestion with mocked Gmail API."""
    mock_service = Mock()
    mock_service.users().messages().get().execute.return_value = {
        'id': 'test123',
        'payload': {'headers': [...], 'body': {'data': '...'}}
    }
    mock_auth.return_value = mock_service
    
    # Your test code here
    result = ingest_message('test123')
    assert result is not None
```

### Option 2: Real Gmail API (Private Tests Only)

For integration tests that need real Gmail access:

```python
# tests/test_gmail_real.py
import pytest
import os

@pytest.mark.skipif(
    not os.path.exists('json/credentials.json'),
    reason="Gmail credentials not available in CI"
)
def test_real_gmail_connection():
    """Integration test with real Gmail API (maintainer-only)."""
    from gmail_api import authenticate_gmail
    service = authenticate_gmail()
    assert service is not None
```

**Run locally:**
```bash
pytest tests/test_gmail_real.py  # Uses your local credentials.json
```

**Run in CI:**
- Only runs if `GMAIL_CREDENTIALS_JSON` secret exists
- Automatically skipped in fork PRs (secure by default)

---

## 🔐 Adding More Secrets

### When to Add GitHub Secrets

Add secrets for:
- ✅ API credentials (Gmail, external services)
- ✅ Database connection strings (if testing with hosted DB)
- ✅ Encryption keys or tokens
- ✅ Service account credentials

**Do NOT add secrets for:**
- ❌ Configuration values (use environment variables)
- ❌ Public API endpoints
- ❌ Non-sensitive feature flags

### How to Add a New Secret

1. **Identify the secret:**
   ```bash
   # Example: Database connection string
   export DB_URL="postgresql://user:pass@host:5432/db"
   ```

2. **Add to GitHub:**
   - Go to Settings → Secrets → Actions
   - Click "New repository secret"
   - Name: `DATABASE_URL`
   - Value: `postgresql://user:pass@host:5432/db`

3. **Use in workflow:**
   ```yaml
   - name: Run database tests
     env:
       DATABASE_URL: ${{ secrets.DATABASE_URL }}
     run: pytest tests/test_database.py
   ```

4. **Update documentation:**
   Add to this file under "Currently Configured Secrets"

---

## 🌐 GitHub Codespaces Setup

If you develop using Codespaces, set up secrets for your development environment:

### Repository Codespaces Secrets

1. Go to **Settings** → **Secrets** → **Codespaces**
2. Add secrets (same as Actions secrets, but for Codespaces)
3. Secrets automatically available in Codespaces terminal

### Usage in Codespaces

```bash
# In Codespaces terminal
echo "$GMAIL_CREDENTIALS_JSON" > json/credentials.json
echo "$USER_EMAIL_ADDRESS" >> .env

# Now run normally
python gmail_auth.py
python manage.py ingest_gmail --days 7
```

---

## 🔍 Verifying Secrets Work

### Check Secret is Set (locally)

```bash
# Check if secret exists in your repository
gh secret list

# Output should include:
# GMAIL_CREDENTIALS_JSON  Updated 2025-12-19
```

### Test in Workflow Run

1. Push a commit or manually trigger workflow
2. Go to Actions tab → Select workflow run
3. Check "Setup Gmail credentials" step:
   - ✅ Green check = Secret loaded successfully
   - ⚠️ Yellow = Skipped (secret not available - OK for forks)
   - ❌ Red = Error (check secret format)

### View Logs (Secrets are Masked)

```
Run echo '***' > json/credentials.json
  echo '***' > json/credentials.json
  shell: /usr/bin/bash -e {0}
✓ Credentials file created
```

GitHub automatically replaces secret values with `***` in logs.

---

## 🚨 Security Best Practices

### DO:
- ✅ Rotate secrets every 90 days
- ✅ Use fine-grained permissions (read-only Gmail scope)
- ✅ Test with mock data in public CI
- ✅ Use `continue-on-error: true` for optional secrets
- ✅ Check secret exists before using: `if: ${{ secrets.SECRET_NAME != '' }}`

### DON'T:
- ❌ Echo secret values in logs (`echo ${{ secrets.SECRET }}` will be masked, but avoid anyway)
- ❌ Write secrets to files that get uploaded as artifacts
- ❌ Use secrets in pull requests from forks (GitHub blocks this automatically)
- ❌ Store secrets in environment files committed to repo

### Common Mistakes

**Mistake 1: Wrong JSON formatting**
```yaml
# ❌ WRONG - Don't add extra quotes
run: echo "${{ secrets.GMAIL_CREDENTIALS_JSON }}" > file.json

# ✅ CORRECT - Single quotes, no extra escaping
run: echo '${{ secrets.GMAIL_CREDENTIALS_JSON }}' > file.json
```

**Mistake 2: Expecting secrets in fork PRs**
```yaml
# ❌ WRONG - Will fail for forks
- name: Test Gmail
  run: python test_gmail.py
  # Fails if credentials.json doesn't exist

# ✅ CORRECT - Skip if not available
- name: Test Gmail
  if: ${{ secrets.GMAIL_CREDENTIALS_JSON != '' }}
  run: python test_gmail.py
  continue-on-error: true
```

**Mistake 3: Committing .env with secrets**
```bash
# ❌ WRONG
echo "API_KEY=abc123" >> .env
git add .env  # Don't commit secrets!

# ✅ CORRECT
echo "API_KEY=abc123" >> .env
# .env already in .gitignore - won't be committed
```

---

## 📚 Related Documentation

- [GitHub Secrets Documentation](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [Gmail API OAuth Setup](../GETTING_STARTED.md#gmail-api-setup)
- [PUBLIC_REPOSITORY_SETUP.md](PUBLIC_REPOSITORY_SETUP.md) - Making repo public safely
- [CI/CD Pipeline](.github/workflows/ci-cd.yml) - Current workflow implementation

---

## 🆘 Troubleshooting

### "Secret not found" Error

**Symptom:** Workflow step fails with secret not found

**Solutions:**
1. Verify secret name matches exactly (case-sensitive!)
2. Check secret exists: `gh secret list`
3. Ensure workflow has permission to access secrets
4. For environment-specific secrets, add `environment:` to job

### Gmail API Tests Failing in CI

**Symptom:** Tests pass locally but fail in GitHub Actions

**Possible causes:**
1. `GMAIL_CREDENTIALS_JSON` secret not set
2. OAuth redirect URI doesn't include GitHub Actions domain
3. Token expired (need `token.pickle` as secret too - not recommended)

**Solution:**
Use mocked tests in CI, real integration tests locally only:
```python
@pytest.mark.skipif('CI' in os.environ, reason="Skip in CI")
def test_real_gmail():
    # Only runs locally
    pass
```

### Fork PR Can't Access Secrets

**This is intentional security behavior!**

Fork contributors cannot access repository secrets. Solutions:
1. Mock external services in tests
2. Use `continue-on-error: true` for optional integrations
3. Maintainer runs sensitive tests after merging

---

**Last Updated:** December 19, 2025  
**Maintainer:** @cyberthreatgurl
