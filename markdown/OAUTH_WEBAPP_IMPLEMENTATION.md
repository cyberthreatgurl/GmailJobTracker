# Web-Based Gmail OAuth Implementation Plan

## Current State (Desktop/CLI Only)

The app currently uses **InstalledAppFlow** which:
- ✅ Works for local development
- ✅ Works for single-user CLI deployment
- ❌ **Fails for web-hosted multi-user deployment**
- ❌ Requires file-based token storage
- ❌ Needs browser access on the same machine

## Required Changes for Web Deployment

### Architecture Changes

```
Current (Desktop):
User → CLI Script → Opens Browser → OAuth → Saves token.pickle

Needed (Web):
User → Django View → Redirects to Google → Callback → Saves to DB
```

### Implementation Options

#### Option 1: Django OAuth (Recommended for Multi-User)

Use `django-allauth` or `google-auth` with Django views.

**Benefits:**
- Each user authenticates via web UI
- Tokens stored per-user in database
- Proper multi-tenant support
- Users can revoke/re-auth from settings

**Implementation:**

1. **Install dependencies:**
```python
# requirements.txt
google-auth-oauthlib==1.2.2
google-auth-httplib2==0.2.0
django-allauth==0.57.0  # Optional, for full OAuth flow
```

2. **Create OAuth views:**
```python
# tracker/views_oauth.py
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from google_auth_oauthlib.flow import Flow
from django.conf import settings
import os

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

@login_required
def gmail_authorize(request):
    """Initiate Gmail OAuth flow"""
    flow = Flow.from_client_secrets_file(
        'json/credentials.json',
        scopes=SCOPES,
        redirect_uri=request.build_absolute_uri('/oauth2callback/')
    )
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    
    # Store state in session to verify callback
    request.session['oauth_state'] = state
    return redirect(authorization_url)

@login_required
def gmail_oauth_callback(request):
    """Handle OAuth callback from Google"""
    state = request.session.get('oauth_state')
    
    flow = Flow.from_client_secrets_file(
        'json/credentials.json',
        scopes=SCOPES,
        state=state,
        redirect_uri=request.build_absolute_uri('/oauth2callback/')
    )
    
    # Exchange authorization code for credentials
    flow.fetch_token(authorization_response=request.build_absolute_uri())
    credentials = flow.credentials
    
    # Save to user's profile in database
    profile = request.user.profile
    profile.gmail_token = credentials.to_json()
    profile.save()
    
    return redirect('dashboard')
```

3. **Add User Profile model:**
```python
# tracker/models.py
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    gmail_token = models.TextField(blank=True, null=True)  # Store JSON credentials
    gmail_authenticated = models.BooleanField(default=False)
    last_sync = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.user.username}'s profile"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
```

4. **Update Gmail service function:**
```python
# gmail_auth.py (new version)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json

def get_gmail_service_for_user(user):
    """Get Gmail service for specific Django user"""
    profile = user.profile
    
    if not profile.gmail_token:
        return None
    
    # Load credentials from database
    creds_data = json.loads(profile.gmail_token)
    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
    
    # Refresh if expired
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        
        # Save refreshed token
        profile.gmail_token = creds.to_json()
        profile.save()
    
    return build('gmail', 'v1', credentials=creds)
```

5. **Add URLs:**
```python
# dashboard/urls.py
from tracker import views_oauth

urlpatterns = [
    path('authorize-gmail/', views_oauth.gmail_authorize, name='gmail_authorize'),
    path('oauth2callback/', views_oauth.gmail_oauth_callback, name='gmail_oauth_callback'),
    # ... existing patterns
]
```

6. **Update Google Cloud Console:**
```
Authorized redirect URIs:
https://your-domain.com/oauth2callback/
http://localhost:8001/oauth2callback/  # For development
```

7. **Add UI in dashboard:**
```html
{% if not user.profile.gmail_authenticated %}
  <div class="alert alert-warning">
    <a href="{% url 'gmail_authorize' %}" class="btn btn-primary">
      Connect Gmail Account
    </a>
  </div>
{% endif %}
```

#### Option 2: Admin-Only OAuth (Simpler, Current Model)

Keep current single-user model but add web-based auth for the admin.

**Benefits:**
- Simpler implementation
- Single Gmail account for all ingestion
- Less database changes

**Drawbacks:**
- Not truly multi-user
- All users see same emails
- Single point of failure

**Implementation:**

Same as Option 1 but simpler:
- Only admin user can authenticate
- Store credentials in settings/environment
- Everyone uses same Gmail connection

### Database Migration

```python
# migrations/0XXX_add_gmail_oauth.py
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('tracker', 'XXXX_previous_migration'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('gmail_token', models.TextField(blank=True, null=True)),
                ('gmail_authenticated', models.BooleanField(default=False)),
                ('last_sync', models.DateTimeField(blank=True, null=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='profile', to='auth.user')),
            ],
        ),
    ]
```

## Configuration Requirements

### Google Cloud Console Setup

1. **Update OAuth Client Type:**
   - Change from "Desktop app" to "Web application"
   - Or create new OAuth client for web

2. **Add Authorized Redirect URIs:**
   ```
   https://yourdomain.com/oauth2callback/
   https://docker-server.shaw.local:8001/oauth2callback/
   http://localhost:8001/oauth2callback/
   ```

3. **Update credentials.json:**
   - Download new web application credentials
   - Replace `json/credentials.json`

### Environment Variables

```bash
# .env
OAUTH_REDIRECT_URI=https://yourdomain.com/oauth2callback/
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
```

## Testing Checklist

- [ ] User can click "Connect Gmail" in dashboard
- [ ] Redirects to Google OAuth consent screen
- [ ] After approval, returns to app with success message
- [ ] Token stored in database (not file)
- [ ] Token automatically refreshes when expired
- [ ] Multiple users can authenticate independently (Option 1)
- [ ] Ingestion works with web-authenticated credentials

## Backward Compatibility

To support both CLI and web authentication:

```python
def get_gmail_service(user=None):
    """Get Gmail service - supports both web and CLI auth"""
    if user:
        # Web-based auth (from database)
        return get_gmail_service_for_user(user)
    else:
        # CLI-based auth (from token.pickle) - legacy
        return get_gmail_service_legacy()
```

## Security Considerations

1. **Token Storage:**
   - Encrypt `gmail_token` field in database
   - Use Django's `encrypt` field or `django-encrypted-model-fields`

2. **Scope Limitation:**
   - Keep read-only scope: `gmail.readonly`
   - Don't request more permissions than needed

3. **Token Rotation:**
   - Implement automatic refresh
   - Allow users to revoke access from settings

4. **HTTPS:**
   - **Required** for production OAuth
   - Google won't redirect to HTTP in production

## Migration Path

### Phase 1: Add Web OAuth (Non-Breaking)
1. Add UserProfile model
2. Add OAuth views and URLs
3. Keep existing CLI auth working
4. Test with single user

### Phase 2: Update Ingestion (Breaking)
1. Modify `ingest_gmail` to require user parameter
2. Update management command to specify user
3. Add per-user ingestion support

### Phase 3: Deprecate CLI Auth
1. Remove file-based token support
2. Remove `gmail_auth.py` CLI script
3. Document web-only authentication

## Documentation Updates Needed

- [ ] README: Add web OAuth setup instructions
- [ ] DEPLOYMENT: Update OAuth configuration steps
- [ ] USER_GUIDE: Add "Connect Gmail" tutorial with screenshots
- [ ] DOCKER: Update environment variable documentation
- [ ] SECURITY: Document token encryption and rotation

## Estimated Effort

- **Option 1 (Multi-User):** 2-3 days development + testing
- **Option 2 (Admin-Only):** 1 day development + testing
- **Testing & Documentation:** 1 day
- **Total:** 2-4 days depending on option chosen

## Recommendation

For **public release**, implement **Option 1 (Multi-User)**:
- Future-proof architecture
- Better user experience
- More secure (per-user tokens)
- Scales to multiple users naturally

Start with Phase 1 to maintain backward compatibility with your current deployment.
