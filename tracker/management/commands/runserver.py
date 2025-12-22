"""
Custom runserver command that displays .env configuration on startup.
"""

import os
import pickle
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from django.core.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    """Extended runserver command that displays environment configuration."""

    help = (
        "Starts a lightweight web server for development (displays .env configuration)"
    )

    def inner_run(self, *args, **options):
        """Display .env values before starting the server."""
        # Use stderr to ensure visibility during server startup
        self.stderr.write(self.style.SUCCESS("\n" + "=" * 70))
        self.stderr.write(self.style.SUCCESS("Environment Configuration (.env)"))
        self.stderr.write(self.style.SUCCESS("=" * 70))

        # Define the env vars to display (in order)
        env_vars = [
            ("USER_EMAIL_ADDRESS", "User Email Address"),
            ("DEBUG", "Debug Mode"),
            ("ALLOWED_HOSTS", "Allowed Hosts"),
            ("DATABASE_PATH", "Database Path"),
            ("LOG_LEVEL", "Log Level"),
            ("REPORTING_DEFAULT_START_DATE", "Reporting Default Start Date"),
            ("AUTO_REVIEW_CONFIDENCE", "Auto-Review Confidence"),
            ("ML_CONFIDENCE_THRESHOLD", "ML Confidence Threshold"),
            ("DEFAULT_DAYS_BACK", "Default Days Back"),
            ("MAX_MESSAGES_PER_BATCH", "Max Messages Per Batch"),
            ("GHOSTED_DAYS_THRESHOLD", "Ghosted Days Threshold"),
        ]

        # Display each configured value
        found_any = False
        for env_key, label in env_vars:
            value = os.environ.get(env_key, "").strip()
            if value:
                found_any = True
                # Mask sensitive values
                if "SECRET" in env_key or "PASSWORD" in env_key or "KEY" in env_key:
                    display_value = "***" + value[-4:] if len(value) > 4 else "***"
                elif "EMAIL" in env_key:
                    # Show email with middle part masked
                    if "@" in value:
                        local, domain = value.split("@", 1)
                        if len(local) > 3:
                            display_value = f"{local[:2]}***{local[-1]}@{domain}"
                        else:
                            display_value = f"***@{domain}"
                    else:
                        display_value = value
                else:
                    display_value = value

                self.stderr.write(f"  {label:.<45} {display_value}")

        if not found_any:
            self.stderr.write(
                self.style.WARNING("  No environment variables configured in .env file")
            )
            self.stderr.write(
                self.style.WARNING(
                    "  See .env.example or INSTALL.md for setup instructions"
                )
            )

        self.stderr.write(self.style.SUCCESS("=" * 70 + "\n"))

        # Display Gmail authentication status
        self._display_gmail_auth_status()

        # Display recent commit history
        self._display_recent_commits()

        # Call the parent class's inner_run to start the server
        return super().inner_run(*args, **options)

    def _display_recent_commits(self):
        """Display build version and recent commits."""
        version_file = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            ),
            "VERSION",
        )

        # Try reading VERSION file (Docker deployments)
        if os.path.exists(version_file):
            try:
                with open(version_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    self._display_version_info(content)
                    return
            except (OSError, IOError):
                pass

        # Fall back to git command (local development)
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-6"],
                capture_output=True,
                text=True,
                check=True,
                cwd=os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                ),
            )
            if result.stdout.strip():
                self._display_version_info(f"RECENT_COMMITS:\n{result.stdout.strip()}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    def _display_version_info(self, content):
        """Parse and display version information."""
        lines = content.strip().split("\n")
        build_info = {}
        commits = []
        in_commits = False

        for line in lines:
            if line.startswith("RECENT_COMMITS:"):
                in_commits = True
                continue
            elif in_commits:
                if line.strip():
                    commits.append(line)
            elif "=" in line and not in_commits:
                key, value = line.split("=", 1)
                build_info[key] = value

        # Display build metadata if available
        if build_info:
            self.stderr.write(self.style.SUCCESS("=" * 70))
            self.stderr.write(self.style.SUCCESS("Build Information"))
            self.stderr.write(self.style.SUCCESS("=" * 70))

            if "VERSION" in build_info:
                self.stderr.write(
                    f"  Version: {self.style.WARNING(build_info['VERSION'])}"
                )
            if "VCS_REF" in build_info:
                self.stderr.write(
                    f"  Commit: {self.style.WARNING(build_info['VCS_REF'])}"
                )
            if "BUILD_DATE" in build_info:
                self.stderr.write(f"  Built: {build_info['BUILD_DATE']}")

            self.stderr.write(self.style.SUCCESS("=" * 70 + "\n"))

        # Display recent commits
        if commits:
            self.stderr.write(self.style.SUCCESS("=" * 70))
            self.stderr.write(
                self.style.SUCCESS("Recent Commits (Last 6 Issues Fixed)")
            )
            self.stderr.write(self.style.SUCCESS("=" * 70))

            for line in commits[:6]:
                if line:
                    parts = line.split(" ", 1)
                    if len(parts) == 2:
                        commit_hash, message = parts
                        if len(message) > 55:
                            message = message[:52] + "..."
                        self.stderr.write(
                            f"  {self.style.WARNING(commit_hash)} {message}"
                        )
                    else:
                        self.stderr.write(f"  {line}")

            self.stderr.write(self.style.SUCCESS("=" * 70 + "\n"))

    def _display_gmail_auth_status(self):
        """Check and display Gmail API authentication status."""
        self.stderr.write(self.style.SUCCESS("=" * 70))
        self.stderr.write(self.style.SUCCESS("Gmail API Authentication Status"))
        self.stderr.write(self.style.SUCCESS("=" * 70))

        project_root = Path(__file__).resolve().parents[4]
        credentials_path = project_root / "json" / "credentials.json"
        token_path = project_root / "model" / "token.pickle"

        # Check credentials.json
        if credentials_path.exists():
            try:
                import json

                with open(credentials_path, "r", encoding="utf-8") as f:
                    creds_data = json.load(f)

                # Check if it's the correct structure
                if "installed" in creds_data or "web" in creds_data:
                    client_info = creds_data.get("installed") or creds_data.get("web")
                    client_id = client_info.get("client_id", "")[:20] + "..."
                    self.stderr.write(
                        f"  credentials.json............. "
                        f"{self.style.SUCCESS('✓ Valid')} (Client ID: {client_id})"
                    )
                else:
                    self.stderr.write(
                        f"  credentials.json............. "
                        f"{self.style.ERROR('✗ Invalid format')}"
                    )
            except (json.JSONDecodeError, IOError) as e:
                self.stderr.write(
                    f"  credentials.json............. "
                    f"{self.style.ERROR('✗ Error reading: ' + str(e)[:30])}"
                )
        else:
            self.stderr.write(
                f"  credentials.json............. " f"{self.style.ERROR('✗ Not found')}"
            )
            self.stderr.write(
                f"    {self.style.WARNING('→ Run: python gmail_auth.py')}"
            )

        # Check token.pickle
        if token_path.exists():
            try:
                with open(token_path, "rb") as token_file:
                    creds = pickle.load(token_file)

                # Check if credentials are valid
                if hasattr(creds, "valid") and creds.valid:
                    if hasattr(creds, "expiry"):
                        expiry_str = creds.expiry.strftime("%Y-%m-%d %H:%M:%S")
                        # Use timezone-aware datetime for comparison
                        now = datetime.now(timezone.utc)
                        # Make expiry timezone-aware if it isn't already
                        expiry = creds.expiry
                        if expiry.tzinfo is None:
                            expiry = expiry.replace(tzinfo=timezone.utc)
                        time_left = expiry - now
                        days_left = time_left.days

                        if days_left > 7:
                            status = self.style.SUCCESS(f"✓ Valid until {expiry_str}")
                        elif days_left > 0:
                            status = self.style.WARNING(
                                f"⚠ Expires {expiry_str} ({days_left}d left)"
                            )
                        else:
                            status = self.style.ERROR(f"✗ Expired on {expiry_str}")

                        self.stderr.write(f"  token.pickle................. {status}")
                    else:
                        self.stderr.write(
                            f"  token.pickle................. "
                            f"{self.style.SUCCESS('✓ Valid (no expiry)')}"
                        )
                elif hasattr(creds, "expired") and creds.expired:
                    if hasattr(creds, "refresh_token"):
                        self.stderr.write(
                            f"  token.pickle................. "
                            f"{self.style.WARNING('⚠ Expired (can refresh)')}"
                        )
                        self.stderr.write(
                            f"    {self.style.WARNING('→ Token will auto-refresh on next API call')}"
                        )
                    else:
                        self.stderr.write(
                            f"  token.pickle................. "
                            f"{self.style.ERROR('✗ Expired (no refresh token)')}"
                        )
                        self.stderr.write(
                            f"    {self.style.ERROR('→ Run: python gmail_auth.py')}"
                        )
                else:
                    self.stderr.write(
                        f"  token.pickle................. "
                        f"{self.style.WARNING('⚠ Unknown validity state')}"
                    )
            except (pickle.UnpicklingError, IOError, AttributeError, ImportError) as e:
                self.stderr.write(
                    f"  token.pickle................. "
                    f"{self.style.ERROR('✗ Error reading: ' + str(e)[:30])}"
                )
        else:
            self.stderr.write(
                f"  token.pickle................. " f"{self.style.ERROR('✗ Not found')}"
            )
            self.stderr.write(f"    {self.style.ERROR('→ Run: python gmail_auth.py')}")

        self.stderr.write(self.style.SUCCESS("=" * 70 + "\n"))
