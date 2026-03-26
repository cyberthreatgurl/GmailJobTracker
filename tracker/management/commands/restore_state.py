from pathlib import Path
import subprocess
import sys

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Restore a backup bundle into a checkout and PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument("backup_path", help="Path to a backup directory or tar.gz archive.")
        parser.add_argument(
            "--project-root",
            help="Project directory that should receive restored files.",
        )
        parser.add_argument(
            "--repo-target-dir",
            help="Clone the backed-up git bundle into this directory before restoring files.",
        )
        parser.add_argument(
            "--skip-db",
            action="store_true",
            help="Skip PostgreSQL restore and only restore files.",
        )
        parser.add_argument(
            "--skip-files",
            action="store_true",
            help="Skip restoring files and only restore PostgreSQL.",
        )
        parser.add_argument(
            "--use-plain-sql",
            action="store_true",
            help="Restore from the plain SQL dump instead of the custom pg_restore dump.",
        )
        parser.add_argument(
            "--restore-globals",
            action="store_true",
            help="Restore PostgreSQL globals when the backup includes them.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow restoring into a dirty checkout or a non-empty repo target directory.",
        )

    def handle(self, *args, **options):
        project_root = Path(__file__).resolve().parents[3]
        script_path = project_root / "scripts" / "restore_current_state.py"

        command = [sys.executable, str(script_path), options["backup_path"]]
        for option_name in [
            "project_root",
            "repo_target_dir",
        ]:
            if options.get(option_name):
                command.extend([f"--{option_name.replace('_', '-')}", options[option_name]])

        for option_name in [
            "skip_db",
            "skip_files",
            "use_plain_sql",
            "restore_globals",
            "force",
        ]:
            if options.get(option_name):
                command.append(f"--{option_name.replace('_', '-')}")

        try:
            result = subprocess.run(
                command,
                cwd=project_root,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else str(exc)
            raise CommandError(stderr) from exc

        if result.stdout.strip():
            self.stdout.write(result.stdout.strip())
