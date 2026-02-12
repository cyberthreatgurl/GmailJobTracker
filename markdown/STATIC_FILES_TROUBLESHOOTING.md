# Static Files Troubleshooting

## Symptom: JavaScript/CSS Not Loading (404 Errors)

If you see console errors like:
```
Failed to load resource: the server responded with a status of 404 (Not Found)
Refused to execute script from 'http://127.0.0.1:8000/static/...' 
because its MIME type ('text/html') is not executable
```

## Root Cause

Django is returning a 404 HTML page instead of the actual static file. This happens when static files haven't been collected to the `staticfiles/` directory.

## Solution

Run Django's `collectstatic` management command:

```bash
python manage.py collectstatic --noinput
```

This copies all static files from:
- `tracker/static/` (app-specific static files)
- `theme/static/` (Tailwind CSS build output)
- Any other app static directories

Into the centralized `staticfiles/` directory that Django serves in production mode or when `DEBUG=False`.

## When to Run collectstatic

Run this command after:
- Creating new JavaScript/CSS files in `tracker/static/`
- Modifying existing JS/CSS files
- Running `python manage.py tailwind build`
- Pulling changes from git that include static file updates
- Any time static assets aren't loading in the browser

## Development Workflow

For active development with live reload:

```bash
# Terminal 1: Django dev server
python manage.py runserver

# Terminal 2: Tailwind watcher (auto-rebuilds CSS)
python manage.py tailwind start

# Terminal 3: Collect static after JS changes
python manage.py collectstatic --noinput
```

## Quick Diagnostic

If UI features aren't working:

1. **Open Browser Console (F12 / Cmd+Option+I)**
2. **Check for 404 errors** in the Network or Console tab
3. **If you see 404s for static files** → Run `collectstatic`
4. **Hard refresh** the browser (Cmd+Shift+R / Ctrl+Shift+R)

## Alternative: DEBUG Mode

In `dashboard/settings.py`, if `DEBUG = True`, Django will serve static files automatically from app directories without needing `collectstatic`. However, production deployment (`DEBUG = False`) always requires collected static files.

---

**Last Updated:** 2026-02-12  
**Related Commands:** `python manage.py runserver`, `python manage.py tailwind build`
