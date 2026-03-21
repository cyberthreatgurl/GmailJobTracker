# Documentation Index

Central index of all documentation files in GmailJobTracker.

---

## 📘 Getting Started

### [GETTING_STARTED.md](GETTING_STARTED.md)
**Full first-time setup guide**
- Installation steps
- Gmail API setup
- First email ingestion
- Dashboard overview
- Common startup and authentication troubleshooting
- Troubleshooting

**Start here if you're new to the project!**

---

## 📖 Core Documentation

### [README.md](README.md)
**Project overview and features**
- Feature list
- Setup instructions
- Management commands overview
- Privacy statement
- Logging configuration
- Classification system overview
- Header hints system
- Company extraction order

### [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md)
**Docker and container deployment guide**
- Docker Compose setup
- Environment variables and volumes
- Startup behavior when PostgreSQL is unavailable
- Troubleshooting and operations

### [CONTRIBUTING.md](CONTRIBUTING.md)
**Contributor workflow and standards**
- Pull request process
- Testing expectations
- `companies.json` update order
- Documentation maintenance expectations

---

### [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md)
**Complete command documentation**
- All Django management commands with examples
- Standalone scripts reference
- Environment variables
- Web interface routes
- Quick reference workflows
- Performance tips
- Backup & recovery
- Common issues and solutions

**Use this for detailed command syntax and options.**

---

### [DASHBOARD_OVERVIEW.md](DASHBOARD_OVERVIEW.md)
**Dashboard architecture and features**
- Core functionality overview
- Intelligent classification system
- Company extraction pipeline
- Architecture details
- Data models
- Management commands summary
- Security features
- Recent enhancements history

---

## 🔍 Technical Documentation

### [EXTRACTION_LOGIC.md](EXTRACTION_LOGIC.md)
**Classification and company extraction logic**
- Message classification rules
- Company extraction algorithms
- Pattern matching details
- ATS detection logic
- Confidence scoring
- Label priority order

---

### [SCHEMA_CHANGELOG.md](SCHEMA_CHANGELOG.md)
**Database schema changes**
- Migration history
- Schema modifications
- Index additions
- Performance improvements

---

## 📝 Project Management

### [CHANGELOG.md](CHANGELOG.md)
**Version history and release notes**
- Feature additions
- Bug fixes
- Breaking changes
- Migration notes

---

### [todo.md](todo.md)
**Planned features and enhancements**
- High priority tasks
- Medium priority improvements
- Future ideas
- Known issues
- Completed items

---

### [BACKLOG.md](BACKLOG.md)
**Development backlog**
- Planned features
- Technical debt
- Enhancement requests
- Long-term goals

---

## 🔒 Security

### [SECURITY.md](SECURITY.md)
**Security policies and practices**
- Credential management
- Secret scanning enforcement
- Privacy guarantees
- Security best practices
- Vulnerability reporting

---

## 📊 Session Notes

### [SESSION_STATE.md](SESSION_STATE.md)
**Development session context**
- Current work in progress
- Recent changes
- Active debugging sessions
- Temporary notes

---

### [NOTES.md](NOTES.md)
**General development notes**
- Design decisions
- Implementation notes
- Performance observations
- Future considerations

---

## 🗂️ Quick Reference by Task

### I want to...

#### Get Started
→ [GETTING_STARTED.md](GETTING_STARTED.md)

#### Learn about a specific command
→ [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md)

#### Understand how classification works
→ [EXTRACTION_LOGIC.md](EXTRACTION_LOGIC.md)

#### See what's new
→ [CHANGELOG.md](CHANGELOG.md)

#### Find out what features are planned
→ [todo.md](todo.md)

#### Understand the dashboard architecture
→ [DASHBOARD_OVERVIEW.md](DASHBOARD_OVERVIEW.md)

#### Learn about security practices
→ [SECURITY.md](SECURITY.md)

#### Troubleshoot an issue
→ [GETTING_STARTED.md](GETTING_STARTED.md) → Troubleshooting section
→ [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) → Common Issues section

#### Set up the project for the first time
→ [GETTING_STARTED.md](GETTING_STARTED.md) → Installation section

#### Understand Label Companies workflow
→ [DASHBOARD_OVERVIEW.md](DASHBOARD_OVERVIEW.md)
→ [EXTRACTION_LOGIC.md](EXTRACTION_LOGIC.md)

#### Run daily ingestion
→ [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) → Daily Workflow section

#### Clean up newsletters
→ [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) → `mark_newsletters_ignored`

#### Add a new company mapping
→ [QUICK_START.md](QUICK_START.md) → Common Tasks section

#### Understand database schema
→ [SCHEMA_CHANGELOG.md](tests/SCHEMA_CHANGELOG.md)
→ [DASHBOARD_OVERVIEW.md](DASHBOARD_OVERVIEW.md) → Data Models section

---

## 📁 File Locations

```
markdown/
├── README.md                    # Project overview
├── GETTING_STARTED.md          # First-time setup guide
├── COMMAND_REFERENCE.md        # Complete command docs
├── DASHBOARD_OVERVIEW.md       # Dashboard architecture
├── DOCKER_DEPLOYMENT.md        # Docker deployment guide
├── CONTRIBUTING.md             # Contributor workflow
├── EXTRACTION_LOGIC.md         # Classification logic
├── CHANGELOG.md                # Version history
├── todo.md                     # Planned features
├── BACKLOG.md                  # Development backlog
├── NOTES.md                    # Dev notes
├── SESSION_STATE.md            # Current session context
├── SECURITY.md                 # Security policies
└── DOCUMENTATION_INDEX.md      # This file

tests/
└── SCHEMA_CHANGELOG.md         # Database schema history
```

---

## 🆕 Recent Documentation Updates (March 2026)

### Major Updates
- Added startup fail-fast notes for `runserver`, WSGI/ASGI, and Docker PostgreSQL startup.
- Documented the current `label_companies` workflow, including homepage-derived domains and in-place contract refresh.
- Added contributor guidance for the preferred `companies.json` update order.

### New Files Created
- **COMMAND_REFERENCE.md**: Comprehensive command documentation
- **QUICK_START.md**: Beginner-friendly setup guide
- **DOCUMENTATION_INDEX.md**: Central navigation hub

### Major Updates
- **README.md**: Added features list, classification system details
- **DASHBOARD_OVERVIEW.md**: Expanded with header hints, company extraction pipeline
- **todo.md**: Reorganized into priority levels, added completed items

### Documentation Improvements
- Added emoji icons for better visual navigation
- Consistent formatting across all docs
- Cross-references between related documents
- Code examples with syntax highlighting
- Troubleshooting sections in key docs

---

## 🛠️ Maintaining Documentation

### When to Update

**README.md**
- New major features
- Changed setup process
- Updated privacy/security policies

**COMMAND_REFERENCE.md**
- New management commands
- Changed command syntax
- New options/flags
- New troubleshooting solutions

**QUICK_START.md**
- Changed installation steps
- New prerequisites
- Updated first-time setup process

**DASHBOARD_OVERVIEW.md**
- Architecture changes
- New models or tables
- Classification algorithm updates
- New web routes

**CHANGELOG.md**
- Every release
- Bug fixes
- Breaking changes
- New features

**todo.md**
- New feature requests
- Completed tasks (move to Completed section)
- Discovered bugs
- Changed priorities

---

## 📮 Documentation Standards

### File Naming
- Use SCREAMING_SNAKE_CASE for major docs (README.md, CHANGELOG.md)
- Use lowercase with underscores for utility docs (todo.md, notes.md)
- Use descriptive names (COMMAND_REFERENCE not COMMANDS)

### Formatting
- Use markdown headers (##, ###) for structure
- Include code blocks with language tags
- Use tables for comparisons
- Add emoji icons sparingly for visual hierarchy
- Keep line length under 120 characters

### Content
- Start with overview/purpose
- Include examples for code/commands
- Add troubleshooting sections
- Cross-reference related docs
- Update "last updated" dates

---

## 🔗 External Resources

- **Django Documentation**: https://docs.djangoproject.com/
- **Gmail API Reference**: https://developers.google.com/gmail/api
- **Python Best Practices**: https://peps.python.org/pep-0008/
- **Markdown Guide**: https://www.markdownguide.org/

---

**Last Updated**: November 8, 2025
