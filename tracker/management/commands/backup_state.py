from pathlib import Path
import subprocess
import sys

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a full local backup bundle for PostgreSQL, models, config, and repo state."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            help="Directory where the backup bundle should be written.",
        )
        parser.add_argument(
            "--skip-compress",
            action="store_true",
            help="Leave the expanded backup directory in place without creating a tar.gz archive.",
        )

    def handle(self, *args, **options):
        project_root = Path(__file__).resolve().parents[3]
        script_path = project_root / "scripts" / "backup_current_state.py"

        command = [sys.executable, str(script_path)]
        if options.get("output_dir"):
            command.extend(["--output-dir", options["output_dir"]])
        if options.get("skip_compress"):
            command.append("--skip-compress")

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
