"""
Custom runserver command that displays .env configuration on startup.
"""
import os
import subprocess
from django.core.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    """Extended runserver command that displays environment configuration."""
    
    help = "Starts a lightweight web server for development (displays .env configuration)"

    def inner_run(self, *args, **options):
        """Display .env values before starting the server."""
        # Use stderr to ensure visibility during server startup
        self.stderr.write(self.style.SUCCESS('\n' + '=' * 70))
        self.stderr.write(self.style.SUCCESS('Environment Configuration (.env)'))
        self.stderr.write(self.style.SUCCESS('=' * 70))
        
        # Define the env vars to display (in order)
        env_vars = [
            ('GMAIL_ROOT_FILTER_LABEL', 'Gmail Root Filter Label'),
            ('USER_EMAIL_ADDRESS', 'User Email Address'),
            ('DEBUG', 'Debug Mode'),
            ('ALLOWED_HOSTS', 'Allowed Hosts'),
            ('DATABASE_PATH', 'Database Path'),
            ('LOG_LEVEL', 'Log Level'),
            ('REPORTING_DEFAULT_START_DATE', 'Reporting Default Start Date'),
            ('AUTO_REVIEW_CONFIDENCE', 'Auto-Review Confidence'),
            ('ML_CONFIDENCE_THRESHOLD', 'ML Confidence Threshold'),
            ('DEFAULT_DAYS_BACK', 'Default Days Back'),
            ('MAX_MESSAGES_PER_BATCH', 'Max Messages Per Batch'),
            ('GHOSTED_DAYS_THRESHOLD', 'Ghosted Days Threshold'),
        ]


        
        # Display each configured value
        found_any = False
        for env_key, label in env_vars:
            value = os.environ.get(env_key, '').strip()
            if value:
                found_any = True
                # Mask sensitive values
                if 'SECRET' in env_key or 'PASSWORD' in env_key or 'KEY' in env_key:
                    display_value = '***' + value[-4:] if len(value) > 4 else '***'
                elif 'EMAIL' in env_key:
                    # Show email with middle part masked
                    if '@' in value:
                        local, domain = value.split('@', 1)
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
                self.style.WARNING('  No environment variables configured in .env file')
            )
            self.stderr.write(
                self.style.WARNING('  See .env.example or INSTALL.md for setup instructions')
            )
        
        self.stderr.write(self.style.SUCCESS('=' * 70 + '\n'))
        
        # Display recent commit history
        self._display_recent_commits()
        
        # Call the parent class's inner_run to start the server
        return super().inner_run(*args, **options)
    
    def _display_recent_commits(self):
        """Display the last 6 commits (recent fixes/features)."""
        try:
            result = subprocess.run(
                ['git', 'log', '--oneline', '-6'],
                capture_output=True,
                text=True,
                check=True,
                cwd=os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.dirname(__file__))
                ))
            )
            
            if result.stdout.strip():
                self.stderr.write(self.style.SUCCESS('=' * 70))
                self.stderr.write(
                    self.style.SUCCESS('Recent Commits (Last 6 Issues Fixed)')
                )
                self.stderr.write(self.style.SUCCESS('=' * 70))
                
                for line in result.stdout.strip().split('\n'):
                    if line:
                        # Split hash and message
                        parts = line.split(' ', 1)
                        if len(parts) == 2:
                            commit_hash, message = parts
                            # Truncate message if too long
                            if len(message) > 55:
                                message = message[:52] + '...'
                            self.stderr.write(
                                f"  {self.style.WARNING(commit_hash)} {message}"
                            )
                        else:
                            self.stderr.write(f"  {line}")
                
                self.stderr.write(self.style.SUCCESS('=' * 70 + '\n'))
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Silently skip if git is not available or not a git repo
            pass
