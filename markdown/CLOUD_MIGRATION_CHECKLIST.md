# Cloud Migration Checklist

This document lists everything you must manually transfer when migrating
GmailJobTracker from a local machine to a cloud-hosted Docker container
(Azure Container Apps, ACI, AWS ECS Fargate, etc.).

None of these files exist in the Docker image — they are gitignored secrets,
personal data, or trained model artifacts that must be copied by hand.

---

## 1. PostgreSQL Database

The app uses PostgreSQL. You must export your local database and
import it into the cloud-managed database service.

```bash
# On your local machine — dump the database
pg_dump -Fc -h localhost -U sslipper tracker > tracker_backup.dump

# On the cloud — restore into the new database
# (replace connection params with your cloud DB credentials)
pg_restore -h <cloud-host> -U <db-user> -d tracker tracker_backup.dump
```

**Cloud services:**
- **Azure**: Azure Database for PostgreSQL – Flexible Server
- **AWS**: Amazon RDS for PostgreSQL

---

## 2. Gmail OAuth Credentials

These two files are required for Gmail API access. **Never commit them to git.**

| File | Default path in container | Notes |
|---|---|---|
| `json/credentials.json` | `/app/json/credentials.json` | OAuth 2.0 client credentials downloaded from Google Cloud Console |
| `model/token.pickle` | `/app/model/token.pickle` | OAuth access/refresh token — generated after first `authenticate_gmail` run |

**How to migrate:**
1. Copy both files to your cloud file share / secret store
2. Mount them as volumes (or inject `credentials.json` as a secret):
   ```yaml
   volumes:
     - ./json/credentials.json:/app/json/credentials.json:ro
     - ./model/token.pickle:/app/model/token.pickle
   ```

> ⚠️ `token.pickle` may expire after ~6 months or if Google revokes it.
> If it stops working, re-run the OAuth flow from the new server:
> `python manage.py authenticate_gmail` (requires temporary browser access).

---

## 3. Trained ML Model Files

Located in the `model/` directory. These are the scikit-learn classifiers
trained on your personal email history — they cannot be reconstructed without
your original training data.

| File | Purpose |
|---|---|
| `model/message_classifier.pkl` | Main message type classifier |
| `model/message_vectorizer.pkl` | TF-IDF vectorizer for message body |
| `model/subject_vectorizer.pkl` | TF-IDF vectorizer for subject line |
| `model/body_vectorizer.pkl` | Body text vectorizer |
| `model/message_label_encoder.pkl` | Label encoder for classifier output |
| `model/model_info.json` | Model metadata and training stats |

**How to migrate:** Copy the entire `model/` directory to a persistent volume
mounted at `/app/model` inside the container.

```bash
# Azure: upload to an Azure File Share, then mount as a volume
# AWS: upload to EFS, then mount via ECS task definition
rsync -av model/ user@cloud-server:/path/to/share/model/
```

---

## 4. Configuration JSON Files

Located in the `json/` directory. The image ships with default versions of
these files, but your customizations (known companies, domain mappings, ignore
patterns, etc.) live only on your local machine.

| File | Purpose |
|---|---|
| `json/companies.json` | Company whitelist, domain→company mappings, ATS domains |
| `json/patterns.json` | Message classification regex patterns and ignore rules |
| `json/personal_domains.json` | Your personal/non-work email domains |
| `json/company_career_pages.json` | Manually tracked company career page URLs |

**How to migrate:** Mount the entire `json/` directory as a volume so your
customizations override the image defaults:
```yaml
volumes:
  - ./json:/app/json
```

---

## 5. Environment Variables / `.env` File

All secrets and configuration values must be set in the cloud service's
environment variable store (never committed to git).

Copy `.env.example` → `.env` on the new server and fill in every value:

```bash
# Core
DJANGO_SECRET_KEY=<generate a new one>
DEBUG=False
ALLOWED_HOSTS=<your-cloud-domain.azurecontainerapps.io>

# PostgreSQL
DB_NAME=tracker
DB_USERNAME=<cloud db user>
DB_PASSWORD=<cloud db password>
DB_HOST=<cloud db hostname>
DB_PORT=5432

# Gmail
GMAIL_ROOT_FILTER_LABEL=#job-hunt
USER_EMAIL_ADDRESS=your-gmail@gmail.com

# API keys
SAM_GOV_API_KEY=<your key from sam.gov>

# App settings
TZ=America/New_York
LOG_LEVEL=INFO
DEFAULT_DAYS_BACK=7
MAX_MESSAGES_PER_BATCH=500
GHOSTED_DAYS_THRESHOLD=30
AUTO_REVIEW_CONFIDENCE=0.85
ML_CONFIDENCE_THRESHOLD=0.55
REPORTING_DEFAULT_START_DATE=2025-01-01
```

**Azure**: Store secrets in Azure Container Apps environment variables or Key Vault.  
**AWS**: Use ECS task definition environment variables or AWS Secrets Manager.

---

## 6. Django Superuser

The entrypoint script creates a default `admin` / `changeme123` superuser on
first boot if no superuser exists. **Change this password immediately** after
your first login at `/admin/`.

Or create your own before launch:
```bash
python manage.py createsuperuser
```

---

## Quick Reference: File Transfer Checklist

```
[ ] PostgreSQL dump exported and restored on cloud DB
[ ] json/credentials.json  →  uploaded to volume / secret store
[ ] model/token.pickle     →  uploaded to model volume
[ ] model/*.pkl (5 files)  →  uploaded to model volume
[ ] model/model_info.json  →  uploaded to model volume
[ ] json/companies.json    →  uploaded to json volume
[ ] json/patterns.json     →  uploaded to json volume
[ ] json/personal_domains.json  →  uploaded to json volume
[ ] .env configured on cloud with all required variables
[ ] DJANGO_SECRET_KEY set to a fresh generated value
[ ] DEBUG=False
[ ] ALLOWED_HOSTS includes your cloud domain
[ ] Admin password changed after first login
```

---

## Cloud Platform Notes

### Azure Container Apps
- Use **Azure Database for PostgreSQL – Flexible Server** for the DB
- Use **Azure Files** (SMB file share) mounted as volumes for `model/` and `json/`
- Set `ALLOWED_HOSTS` to your `.azurecontainerapps.io` domain
- Store `DJANGO_SECRET_KEY` and DB password in **Azure Key Vault** secrets

### AWS ECS Fargate
- Use **Amazon RDS for PostgreSQL** for the DB
- Use **Amazon EFS** for persistent `model/` and `json/` volumes
- Store secrets in **AWS Secrets Manager** and inject via task definition
- Set `ALLOWED_HOSTS` to your ALB or CloudFront domain

---

*Last updated: 2026-03-13*
