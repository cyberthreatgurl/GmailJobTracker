# Contributing to GmailJobTracker

Thank you for considering contributing to GmailJobTracker! This document outlines the process and guidelines for contributing.

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help maintain a welcoming environment for all contributors

## How to Contribute

### Reporting Bugs

**Before submitting a bug report:**
1. Check existing [Issues](https://github.com/<your-username>/GmailJobTracker/issues) to avoid duplicates
2. Run `python check_env.py` to verify your environment
3. Collect relevant logs from `logs/` directory

**Bug report should include:**
- **Description:** Clear summary of the issue
- **Steps to reproduce:** Numbered list of exact steps
- **Expected behavior:** What should happen
- **Actual behavior:** What actually happens
- **Environment:**
  - OS: (e.g., Windows 11, Ubuntu 22.04)
  - Python version: `python --version`
  - Django version: `pip show django`
- **Logs/Screenshots:** Attach relevant error messages
- **Configuration:** Sanitized `.env` settings (remove secrets!)

**Example bug report:**
```markdown
## Bug: Company resolution fails for ATS domains

**Steps to reproduce:**
1. Ingest message from greenhouse.io domain
2. Check Company field in admin panel
3. Company shows as "Unknown" instead of mapped company

**Environment:**
- OS: Windows 11
- Python: 3.12.10
- Django: 5.2.6

**Logs:**
```
[2025-01-15 10:30:45] WARNING: Company not resolved for domain: greenhouse.io
```

**Expected:** Should map to company via domain_to_company in companies.json
**Actual:** Falls back to "Unknown"
```

### Suggesting Features

**Feature requests should include:**
- **Problem statement:** What pain point does this solve?
- **Proposed solution:** How would this feature work?
- **Alternatives considered:** Other approaches you've thought about
- **Use case:** Example scenario where this would be useful

**Label your issue:** Use `enhancement` label for feature requests

### Submitting Pull Requests

**Before starting work:**
1. Check [Issues](https://github.com/<your-username>/GmailJobTracker/issues) for existing discussions
2. Comment on the issue to claim it (avoid duplicate work)
3. Fork the repository and create a feature branch

**Branch naming convention:**
- `feature/description` - New features
- `bugfix/issue-number-description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring

**Example:**
```bash
git checkout -b feature/add-calendar-export
git checkout -b bugfix/42-company-resolution
```

**Development workflow:**

1. **Set up development environment:**
   ```bash
   git clone https://github.com/<your-fork>/GmailJobTracker.git
   cd GmailJobTracker
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   source .venv/bin/activate  # Linux/macOS
   pip install -r requirements.txt
   python init_db.py
   ```

2. **Make your changes:**
   - Follow existing code style (see Code Style section below)
   - Add tests for new functionality
   - Update documentation if needed

3. **Test your changes:**
   ```bash
   # Run tests
   pytest
   
   # Check coverage
   pytest --cov=tracker --cov-report=html
   
   # Run linters
   black .
   flake8
   
   # Test manually
   python manage.py runserver
   ```

4. **Commit your changes:**
   ```bash
   git add .
   git commit -m "feat: Add calendar export functionality"
   ```
   
   **Commit message format:**
   - `feat:` - New feature
   - `fix:` - Bug fix
   - `docs:` - Documentation changes
   - `test:` - Test additions/fixes
   - `refactor:` - Code refactoring
   - `style:` - Code style changes (formatting, etc.)
   - `chore:` - Maintenance tasks

5. **Push and create PR:**
   ```bash
   git push origin feature/add-calendar-export
   ```
   
   Then open a Pull Request on GitHub with:
   - **Title:** Clear, concise description
   - **Description:** 
     - What changes were made
     - Why they were made
     - Link to related issue (e.g., "Closes #42")
   - **Testing:** How you tested the changes
   - **Screenshots:** For UI changes

**PR checklist:**
- [ ] Code follows project style guidelines
- [ ] Tests pass (`pytest`)
- [ ] New tests added for new functionality
- [ ] Documentation updated (if applicable)
- [ ] No merge conflicts with main branch
- [ ] Commit messages are descriptive
- [ ] No sensitive data (credentials, tokens) committed

## Updating companies.json

When you add a new company, use this order so parser behavior stays predictable:

1. Pick the canonical company name and keep the exact casing consistent everywhere.
2. Add the real company domain to `domain_to_company`.
3. Add the careers URL to `JobSites`.
4. Add abbreviations, recruiter display-name variants, and common short forms to `aliases`.
5. Add the canonical company name to `known`.
6. Only add `ats_domains` when the sender domain is a shared ATS platform that is not already handled by `ats_heuristic_patterns`.

Guidelines:

- Do not map shared ATS domains such as Jobvite or Workday directly in `domain_to_company` unless the domain is company-specific.
- Keep `domain_to_company`, `JobSites`, `aliases`, and `known` aligned to the same canonical company name.
- If you change company resolution behavior, update `README.md`, `markdown/EXTRACTION_LOGIC.md`, and the changelog in the same PR.

## Code Style Guidelines

- **Indentation:** 4 spaces (no tabs)
- **Quotes:** Prefer double quotes `"` for strings
- **Imports:** Organized by stdlib → third-party → local
  from ml_subject_classifier import predict_subject_type
  
  
  ```

**Use Black for formatting:**
```bash
black .
```python
def extract_company_name(email_body: str, domain: str) -> tuple[str, float]:
  
  
    """
    Extract company name from email body with confidence score.
    
  
  
    Args:
        email_body: HTML or plain text email content
        domain: Sender's email domain
  
  
    
    Returns:
        Tuple of (company_name, confidence_score)
  
  
        
    Example:
        >>> extract_company_name("<html>Thanks from Acme Corp</html>", "acme.com")

**Type hints:**
```python
from typing import Optional, List, Dict

def ingest_message(
    msg_id: str, 
    service: object, 
    force: bool = False
) -> Optional[Dict[str, str]]:
    pass
```

class Company(models.Model):  # Singular, PascalCase
    name = models.CharField(max_length=200)  # lowercase, snake_case
  
  
    
    class Meta:
        verbose_name_plural = "Companies"  # Proper plural
  
  
```

**View naming:**
```python
# Function-based views: verb_noun format
def label_messages(request):
    pass

# Class-based views: NounVerb format
class CompanyDetailView(DetailView):
  
  
    pass
```

**URL patterns:**
```python
  
  
urlpatterns = [
    path("company/<int:pk>/", views.company_detail, name="company_detail"),  # lowercase, underscores
]
```

### JavaScript/HTML

  
  
**Template naming:**
- Lowercase with underscores: `label_messages.html`
- Component templates prefix with underscore: `_sidebar.html`
  
  

**JavaScript:**
- Use `camelCase` for function names
- Add comments for complex logic
- Avoid inline JavaScript (use `<script>` blocks)

### Testing

**Test file naming:**
  
  
- `test_<module>.py` (e.g., `test_ingest_message.py`)

**Test function naming:**
  
  
```python
def test_company_resolution_with_known_domain():
    """Test that known domains resolve correctly."""
    pass

  
  
def test_ml_classification_falls_back_to_rules_on_low_confidence():
    """Test rule fallback when ML confidence < 0.55."""
    pass
```
```python
result = classify_message(message)

# Assert
## Project Structure

**Understanding the codebase:**

```
├── tracker/                  # Django app
│   ├── models.py             # Database models
│   ├── views.py              # View functions/classes
  
  
│   ├── urls.py               # URL routing
│   ├── admin.py              # Admin customizations
├── ml_entity_extraction.py   # spaCy entity extraction
├── train_model.py            # Model training script
├── db_helpers.py             # Database utility functions
├── gmail_auth.py             # OAuth authentication
└── json/                     # Configuration files
    ├── patterns.json         # Regex patterns
    └── companies.json        # Company mappings
  
  
```

**Key files for contributors:**
  
  
- **Adding features:** Modify `tracker/views.py`, `tracker/models.py`, templates
- **Improving parsing:** Edit `parser.py`, `ml_entity_extraction.py`
- **Enhancing ML:** Update `train_model.py`, `ml_subject_classifier.py`
- **Configuration:** Adjust `json/patterns.json`, `json/companies.json`

## Development Tips

### Local Testing

**Use test database:**
```python
# settings.py
  
  
if os.environ.get("TESTING"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db" / "test_db.sqlite3",
        }
    }
```

**Run with test data:**
```bash
TESTING=1 python manage.py runserver
```

### Debugging

**Enable verbose logging:**
```python
# In parser.py
DEBUG = True
```

**Django shell for testing:**
from tracker.models import Message, Company
from ml_subject_classifier import predict_subject_type

msg = Message.objects.first()
result = predict_subject_type(msg.subject, msg.body)
print(result)
```
```

### Common Pitfalls

1. **Forgot to activate venv:** Always run `.venv\Scripts\activate` first
2. **Migration conflicts:** Run `python manage.py makemigrations` before committing
3. **Circular imports:** Keep imports at module level, avoid in functions
4. **Hardcoded paths:** Use `Path(__file__).parent.resolve()` for relative paths
5. **Committed secrets:** Run `detect-secrets scan` before pushing

## Getting Help

- **Questions:** Open a [Discussion](https://github.com/<your-username>/GmailJobTracker/discussions)
- **Bugs:** Open an [Issue](https://github.com/<your-username>/GmailJobTracker/issues)
- **Chat:** Join our [Discord/Slack] (if applicable)

## Recognition

Contributors will be listed in `CONTRIBUTORS.md` and credited in release notes.

Thank you for contributing! 🎉
