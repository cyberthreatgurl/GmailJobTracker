#!/usr/bin/env python3
"""Create a restorable backup bundle for the current GmailJobTracker state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "backups"
ENV_FILES = [".env", ".env.local"]
CONFIG_DIRS = ["json"]
OPTIONAL_DIRS = ["media"]
SENSITIVE_FILE_CANDIDATES = [
    "credentials.json",
    "token.pickle",
    "json/credentials.json",
    "json/token.pickle",
    "model/token.pickle",
]
RESTORE_NOTES = [
    "Load the same repository state from the included git bundle or source archive.",
    "Restore environment files before running Django commands.",
    "Restore OAuth credentials and tokens to their original paths.",
    "Restore the model directory before running classification or ingestion commands.",
    "Restore media files if you need uploaded assets and generated files.",
    "Restore PostgreSQL globals first when present, then restore the database dump.",
]


class BackupError(RuntimeError):
    """Raised when the backup bundle cannot be created."""


@dataclass
class BackupPaths:
    """Filesystem layout for an individual backup run."""

    root: Path
    payload_dir: Path
    metadata_dir: Path
    archives_dir: Path
    db_dir: Path


def run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and return the completed process."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            capture_output=capture_output,
            text=True,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        details = stderr or stdout or str(exc)
        raise BackupError(details) from exc


def which_or_none(command: str) -> str | None:
    """Return the absolute path for a command when available."""
    return shutil.which(command)


def _brew_versioned_path(major_version: int, binary_name: str) -> Path | None:
    """Return a Homebrew path for a versioned PostgreSQL client binary when present."""
    for prefix in [Path("/opt/homebrew/opt"), Path("/usr/local/opt")]:
        candidate = prefix / f"postgresql@{major_version}" / "bin" / binary_name
        if candidate.exists():
            return candidate
    return None


def _postgres_client_major(binary_path: str) -> int | None:
    """Extract the PostgreSQL client major version from `<binary> --version`."""
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    version_output = result.stdout.strip() or result.stderr.strip()
    match = re.search(r"(PostgreSQL|pg_dump|psql)\)\s+(\d+)(?:\.\d+)?", version_output)
    if match:
        return int(match.group(2))
    fallback = re.search(r"\b(\d+)(?:\.\d+)?\b", version_output)
    return int(fallback.group(1)) if fallback else None


def _postgres_server_major(db_config: dict[str, str]) -> int:
    """Query the PostgreSQL server and return its major version."""
    psql = which_or_none("psql")
    if not psql:
        raise BackupError("psql is required to inspect the PostgreSQL server version.")

    env = {"PGPASSWORD": db_config["DB_PASSWORD"]}
    result = run_command(
        [
            psql,
            "--host",
            db_config["DB_HOST"],
            "--port",
            db_config["DB_PORT"],
            "--username",
            db_config["DB_USERNAME"],
            "--dbname",
            db_config["DB_NAME"],
            "-Atqc",
            "SHOW server_version_num",
        ],
        env=env,
    )
    raw_version = result.stdout.strip()
    if not raw_version.isdigit() or len(raw_version) < 2:
        raise BackupError(f"Unexpected PostgreSQL server version output: {raw_version!r}")
    return int(raw_version[:-4] or raw_version[0])


def resolve_postgres_tools(db_config: dict[str, str]) -> tuple[str, str | None, int]:
    """Find pg_dump and pg_dumpall binaries that match the server major version."""
    server_major = _postgres_server_major(db_config)

    pg_dump_candidates: list[str] = []
    versioned_pg_dump = _brew_versioned_path(server_major, "pg_dump")
    if versioned_pg_dump:
        pg_dump_candidates.append(str(versioned_pg_dump))
    default_pg_dump = which_or_none("pg_dump")
    if default_pg_dump and default_pg_dump not in pg_dump_candidates:
        pg_dump_candidates.append(default_pg_dump)

    matched_pg_dump = next(
        (
            candidate
            for candidate in pg_dump_candidates
            if _postgres_client_major(candidate) == server_major
        ),
        None,
    )
    if not matched_pg_dump:
        available = ", ".join(
            f"{candidate} (v{_postgres_client_major(candidate) or 'unknown'})"
            for candidate in pg_dump_candidates
        ) or "none"
        raise BackupError(
            "No compatible pg_dump client was found for PostgreSQL "
            f"{server_major}. Installed candidates: {available}. "
            f"Install a matching client such as Homebrew postgresql@{server_major} "
            "or libpq from the same server major version."
        )

    pg_dumpall_candidates: list[str] = []
    versioned_pg_dumpall = _brew_versioned_path(server_major, "pg_dumpall")
    if versioned_pg_dumpall:
        pg_dumpall_candidates.append(str(versioned_pg_dumpall))
    default_pg_dumpall = which_or_none("pg_dumpall")
    if default_pg_dumpall and default_pg_dumpall not in pg_dumpall_candidates:
        pg_dumpall_candidates.append(default_pg_dumpall)

    matched_pg_dumpall = next(
        (
            candidate
            for candidate in pg_dumpall_candidates
            if _postgres_client_major(candidate) == server_major
        ),
        None,
    )

    return matched_pg_dump, matched_pg_dumpall, server_major


def sha256_for_path(path: Path) -> str:
    """Compute a SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dotenv_if_present(project_root: Path) -> dict[str, str]:
    """Load key/value pairs from .env files without mutating process environment."""
    parsed: dict[str, str] = {}
    for env_name in ENV_FILES:
        env_path = project_root / env_name
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


def get_db_config(project_root: Path) -> dict[str, str]:
    """Build PostgreSQL connection settings from env files and the live environment."""
    dotenv_values = load_dotenv_if_present(project_root)

    def value_for(key: str, default: str) -> str:
        return os.environ.get(key) or dotenv_values.get(key) or default

    db_engine = value_for("DB_ENGINE", "postgresql").strip().lower()
    if db_engine not in {"postgres", "postgresql", "django.db.backends.postgresql"}:
        raise BackupError(f"Unsupported DB_ENGINE '{db_engine}'. Expected PostgreSQL.")

    return {
        "DB_ENGINE": db_engine,
        "DB_NAME": value_for("DB_NAME", "tracker"),
        "DB_USERNAME": value_for("DB_USERNAME", "sslipper"),
        "DB_PASSWORD": value_for("DB_PASSWORD", "##fl1per!!"),
        "DB_HOST": value_for("DB_HOST", "localhost"),
        "DB_PORT": value_for("DB_PORT", "5432"),
    }


def make_backup_paths(output_dir: Path, timestamp: str) -> BackupPaths:
    """Create the directory layout for a backup run."""
    root = output_dir / f"gmailjobtracker-backup-{timestamp}"
    payload_dir = root / "payload"
    metadata_dir = root / "metadata"
    archives_dir = payload_dir / "archives"
    db_dir = payload_dir / "postgresql"
    for path in [root, payload_dir, metadata_dir, archives_dir, db_dir]:
        path.mkdir(parents=True, exist_ok=False)
    return BackupPaths(
        root=root,
        payload_dir=payload_dir,
        metadata_dir=metadata_dir,
        archives_dir=archives_dir,
        db_dir=db_dir,
    )


def copy_path(source: Path, destination: Path) -> None:
    """Copy a file or directory into the backup payload."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return
    shutil.copy2(source, destination)


def copy_restore_files(project_root: Path, backup_paths: BackupPaths) -> dict[str, list[str]]:
    """Copy local restore-critical files into the backup payload."""
    copied: dict[str, list[str]] = {
        "env_files": [],
        "sensitive_files": [],
        "config_dirs": [],
        "optional_dirs": [],
        "required_dirs": [],
    }

    model_dir = project_root / "model"
    if not model_dir.exists():
        raise BackupError("Expected model directory is missing.")
    copy_path(model_dir, backup_paths.payload_dir / "model")
    copied["required_dirs"].append("model")

    for env_name in ENV_FILES:
        source = project_root / env_name
        if source.exists():
            copy_path(source, backup_paths.payload_dir / env_name)
            copied["env_files"].append(env_name)

    for relative_dir in CONFIG_DIRS:
        source = project_root / relative_dir
        if source.exists():
            copy_path(source, backup_paths.payload_dir / relative_dir)
            copied["config_dirs"].append(relative_dir)

    for relative_dir in OPTIONAL_DIRS:
        source = project_root / relative_dir
        if source.exists():
            copy_path(source, backup_paths.payload_dir / relative_dir)
            copied["optional_dirs"].append(relative_dir)

    for relative_file in SENSITIVE_FILE_CANDIDATES:
        source = project_root / relative_file
        if source.exists():
            destination = backup_paths.payload_dir / relative_file
            copy_path(source, destination)
            copied["sensitive_files"].append(relative_file)

    return copied


def dump_postgres(db_config: dict[str, str], backup_paths: BackupPaths) -> dict[str, str | None]:
    """Create PostgreSQL globals and database dumps."""
    pg_dump, pg_dumpall, _server_major = resolve_postgres_tools(db_config)

    env = {"PGPASSWORD": db_config["DB_PASSWORD"]}
    host = db_config["DB_HOST"]
    port = db_config["DB_PORT"]
    user = db_config["DB_USERNAME"]
    database = db_config["DB_NAME"]

    custom_dump = backup_paths.db_dir / "tracker_database.dump"
    run_command(
        [
            pg_dump,
            "--format=custom",
            "--blobs",
            "--verbose",
            "--host",
            host,
            "--port",
            port,
            "--username",
            user,
            "--file",
            str(custom_dump),
            database,
        ],
        env=env,
    )

    plain_dump = backup_paths.db_dir / "tracker_database.sql"
    run_command(
        [
            pg_dump,
            "--format=plain",
            "--no-owner",
            "--no-privileges",
            "--host",
            host,
            "--port",
            port,
            "--username",
            user,
            "--file",
            str(plain_dump),
            database,
        ],
        env=env,
    )

    globals_dump_name: str | None = None
    if pg_dumpall:
        globals_dump = backup_paths.db_dir / "postgres_globals.sql"
        with globals_dump.open("w", encoding="utf-8") as handle:
            process = subprocess.run(
                [
                    pg_dumpall,
                    "--globals-only",
                    "--host",
                    host,
                    "--port",
                    port,
                    "--username",
                    user,
                ],
                env={**os.environ, **env},
                stdout=handle,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        if process.returncode != 0:
            raise BackupError(process.stderr.strip() or "pg_dumpall --globals-only failed.")
        globals_dump_name = globals_dump.name

    return {
        "custom_dump": custom_dump.name,
        "plain_sql_dump": plain_dump.name,
        "globals_dump": globals_dump_name,
    }


def create_git_metadata(project_root: Path, backup_paths: BackupPaths) -> dict[str, Any]:
    """Capture repository state and portable source snapshots."""
    metadata: dict[str, Any] = {}

    git_bundle = backup_paths.archives_dir / "repository.bundle"
    run_command(["git", "bundle", "create", str(git_bundle), "--all"], cwd=project_root)

    source_archive = backup_paths.archives_dir / "tracked-source.tar.gz"
    with source_archive.open("wb") as handle:
        process = subprocess.run(
            ["git", "archive", "--format=tar.gz", "HEAD"],
            cwd=project_root,
            stdout=handle,
            stderr=subprocess.PIPE,
            text=False,
            check=False,
        )
    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace") if isinstance(process.stderr, bytes) else str(process.stderr)
        raise BackupError(stderr.strip() or "git archive failed.")

    head_commit = run_command(["git", "rev-parse", "HEAD"], cwd=project_root).stdout.strip()
    branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_root).stdout.strip()
    status = run_command(["git", "status", "--short", "--branch"], cwd=project_root).stdout
    diff = run_command(["git", "diff", "HEAD"], cwd=project_root).stdout

    (backup_paths.metadata_dir / "git-status.txt").write_text(status, encoding="utf-8")
    (backup_paths.metadata_dir / "git-diff.txt").write_text(diff, encoding="utf-8")

    metadata["head_commit"] = head_commit
    metadata["branch"] = branch
    metadata["bundle"] = git_bundle.relative_to(backup_paths.root).as_posix()
    metadata["source_archive"] = source_archive.relative_to(backup_paths.root).as_posix()
    metadata["working_tree_clean"] = not bool(diff.strip())
    return metadata


def create_environment_metadata(project_root: Path, backup_paths: BackupPaths) -> dict[str, Any]:
    """Capture Python and dependency metadata helpful for restoration."""
    metadata: dict[str, Any] = {
        "python_executable": sys.executable,
        "python_version": sys.version,
    }

    pip_freeze = run_command([sys.executable, "-m", "pip", "freeze"], cwd=project_root).stdout
    (backup_paths.metadata_dir / "pip-freeze.txt").write_text(pip_freeze, encoding="utf-8")
    metadata["pip_freeze"] = "metadata/pip-freeze.txt"

    for filename in ["requirements.txt", "requirements-dev.txt", "requirements-prod.txt", "docker-compose.yml", "Dockerfile"]:
        source = project_root / filename
        if source.exists():
            copy_path(source, backup_paths.metadata_dir / filename)

    return metadata


def create_restore_instructions(
    backup_paths: BackupPaths,
    db_config: dict[str, str],
    copied_files: dict[str, list[str]],
    db_dump_metadata: dict[str, str | None],
) -> None:
    """Write a human-readable restore guide into the bundle."""
    globals_note = ""
    if db_dump_metadata.get("globals_dump"):
        globals_note = (
            "1. Restore PostgreSQL globals first if roles or grants are missing:\n"
            f"   psql -h <host> -U <user> -f payload/postgresql/{db_dump_metadata['globals_dump']} postgres\n\n"
        )

    sensitive_targets = "\n".join(f"- {path}" for path in copied_files["sensitive_files"])
    env_targets = "\n".join(f"- {path}" for path in copied_files["env_files"])

    instructions = f"""GmailJobTracker backup restore notes
=================================

This bundle was created on {datetime.now(timezone.utc).isoformat()}.

Included backup categories:
- PostgreSQL dumps under payload/postgresql/
- Entire model directory under payload/model/
- Config directory copies under payload/json/
- Environment files:
{env_targets or '- none found'}
- Sensitive auth/token files:
{sensitive_targets or '- none found'}

Suggested restore order:
{globals_note}2. Restore the application source from payload/archives/repository.bundle or payload/archives/tracked-source.tar.gz.
3. Copy the environment files back into the project root.
4. Copy OAuth files and token files back to their original paths.
5. Copy payload/model/ back to model/.
6. Copy payload/json/ back to json/ if you need exact config state.
7. Restore optional directories such as media/ when needed.
8. Recreate the PostgreSQL database if needed, then restore the main dump:
   pg_restore --clean --if-exists --no-owner --no-privileges -h {db_config['DB_HOST']} -p {db_config['DB_PORT']} -U {db_config['DB_USERNAME']} -d {db_config['DB_NAME']} payload/postgresql/{db_dump_metadata['custom_dump']}

Alternative plain SQL restore:
   psql -h {db_config['DB_HOST']} -p {db_config['DB_PORT']} -U {db_config['DB_USERNAME']} -d {db_config['DB_NAME']} -f payload/postgresql/{db_dump_metadata['plain_sql_dump']}

Notes:
"""
    instructions += "\n".join(f"- {note}" for note in RESTORE_NOTES)
    instructions += "\n"
    (backup_paths.root / "RESTORE.md").write_text(instructions, encoding="utf-8")


def build_manifest(
    backup_paths: BackupPaths,
    db_config: dict[str, str],
    copied_files: dict[str, list[str]],
    db_dump_metadata: dict[str, str | None],
    git_metadata: dict[str, Any],
    environment_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Assemble a machine-readable manifest for the backup bundle."""
    manifest: dict[str, Any] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "database": {
            "engine": db_config["DB_ENGINE"],
            "name": db_config["DB_NAME"],
            "host": db_config["DB_HOST"],
            "port": db_config["DB_PORT"],
            "username": db_config["DB_USERNAME"],
            "dumps": db_dump_metadata,
        },
        "copied_files": copied_files,
        "git": git_metadata,
        "environment": environment_metadata,
        "files": [],
    }

    for file_path in sorted(backup_paths.root.rglob("*")):
        if file_path.is_file():
            manifest["files"].append(
                {
                    "path": file_path.relative_to(backup_paths.root).as_posix(),
                    "size": file_path.stat().st_size,
                    "sha256": sha256_for_path(file_path),
                }
            )

    manifest_path = backup_paths.root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def compress_backup(backup_root: Path) -> Path:
    """Create a compressed tarball of the backup directory."""
    tarball_path = backup_root.with_suffix(".tar.gz")
    with tarfile.open(tarball_path, "w:gz") as archive:
        archive.add(backup_root, arcname=backup_root.name)
    return tarball_path


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where the backup folder and archive will be written.",
    )
    parser.add_argument(
        "--skip-compress",
        action="store_true",
        help="Leave the expanded backup directory in place without creating a tar.gz archive.",
    )
    return parser.parse_args()


def main() -> int:
    """Create a backup bundle and print its location."""
    args = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    backup_paths = make_backup_paths(output_dir, timestamp)
    try:
        db_config = get_db_config(PROJECT_ROOT)
        copied_files = copy_restore_files(PROJECT_ROOT, backup_paths)
        db_dump_metadata = dump_postgres(db_config, backup_paths)
        git_metadata = create_git_metadata(PROJECT_ROOT, backup_paths)
        environment_metadata = create_environment_metadata(PROJECT_ROOT, backup_paths)
        create_restore_instructions(backup_paths, db_config, copied_files, db_dump_metadata)
        build_manifest(
            backup_paths,
            db_config,
            copied_files,
            db_dump_metadata,
            git_metadata,
            environment_metadata,
        )
        tarball_path = None if args.skip_compress else compress_backup(backup_paths.root)
    except BackupError as exc:
        shutil.rmtree(backup_paths.root, ignore_errors=True)
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        shutil.rmtree(backup_paths.root, ignore_errors=True)
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

    print(f"Backup directory: {backup_paths.root}")
    if tarball_path:
        print(f"Compressed archive: {tarball_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())