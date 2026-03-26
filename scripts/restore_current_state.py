#!/usr/bin/env python3
"""Restore a GmailJobTracker backup bundle into a project checkout and PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILES = [".env", ".env.local"]


class BackupError(RuntimeError):
    """Raised when a backup bundle cannot be restored."""


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
    match = re.search(r"(PostgreSQL|pg_restore|psql)\)\s+(\d+)(?:\.\d+)?", version_output)
    if match:
        return int(match.group(2))
    fallback = re.search(r"\b(\d+)(?:\.\d+)?\b", version_output)
    return int(fallback.group(1)) if fallback else None


def _postgres_server_major(db_config: dict[str, str]) -> int:
    """Query the PostgreSQL server and return its major version."""
    psql = which_or_none("psql")
    if not psql:
        raise BackupError("psql is required to inspect the PostgreSQL server version.")

    env = {**os.environ, "PGPASSWORD": db_config["DB_PASSWORD"]}
    result = subprocess.run(
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
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BackupError((result.stderr or result.stdout or "Unable to query PostgreSQL server version.").strip())
    raw_version = result.stdout.strip()
    if not raw_version.isdigit() or len(raw_version) < 2:
        raise BackupError(f"Unexpected PostgreSQL server version output: {raw_version!r}")
    return int(raw_version[:-4] or raw_version[0])


def resolve_restore_tools(db_config: dict[str, str]) -> tuple[str | None, str, int]:
    """Find pg_restore and psql binaries that match the server major version."""
    server_major = _postgres_server_major(db_config)

    pg_restore_candidates: list[str] = []
    versioned_pg_restore = _brew_versioned_path(server_major, "pg_restore")
    if versioned_pg_restore:
        pg_restore_candidates.append(str(versioned_pg_restore))
    default_pg_restore = which_or_none("pg_restore")
    if default_pg_restore and default_pg_restore not in pg_restore_candidates:
        pg_restore_candidates.append(default_pg_restore)
    matched_pg_restore = next(
        (
            candidate
            for candidate in pg_restore_candidates
            if _postgres_client_major(candidate) == server_major
        ),
        None,
    )

    psql_candidates: list[str] = []
    versioned_psql = _brew_versioned_path(server_major, "psql")
    if versioned_psql:
        psql_candidates.append(str(versioned_psql))
    default_psql = which_or_none("psql")
    if default_psql and default_psql not in psql_candidates:
        psql_candidates.append(default_psql)
    matched_psql = next(
        (
            candidate
            for candidate in psql_candidates
            if _postgres_client_major(candidate) == server_major
        ),
        None,
    )

    if not matched_psql:
        available = ", ".join(
            f"{candidate} (v{_postgres_client_major(candidate) or 'unknown'})"
            for candidate in psql_candidates
        ) or "none"
        raise BackupError(
            "No compatible psql client was found for PostgreSQL "
            f"{server_major}. Installed candidates: {available}. "
            f"Install a matching client such as Homebrew postgresql@{server_major} "
            "or libpq from the same server major version."
        )

    return matched_pg_restore, matched_psql, server_major


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_path", help="Path to a backup directory or .tar.gz archive.")
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
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
        help="Skip restoring local files and only restore PostgreSQL.",
    )
    parser.add_argument(
        "--use-plain-sql",
        action="store_true",
        help="Use the plain SQL dump instead of the custom pg_restore dump.",
    )
    parser.add_argument(
        "--restore-globals",
        action="store_true",
        help="Restore PostgreSQL globals when the backup includes them.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow restoring into a non-empty repo target directory or over a dirty git checkout.",
    )
    return parser.parse_args()


def load_backup_root(backup_path: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    """Return the extracted backup root for a directory or tarball input."""
    if backup_path.is_dir():
        return backup_path, None

    suffixes = backup_path.suffixes
    if suffixes[-2:] != [".tar", ".gz"]:
        raise BackupError("backup_path must be a backup directory or .tar.gz archive.")

    temp_dir = tempfile.TemporaryDirectory(prefix="gmailjobtracker-restore-")
    with tarfile.open(backup_path, "r:gz") as archive:
        archive.extractall(temp_dir.name)

    extracted_roots = [path for path in Path(temp_dir.name).iterdir() if path.is_dir()]
    if len(extracted_roots) != 1:
        temp_dir.cleanup()
        raise BackupError("Expected exactly one top-level directory inside the backup archive.")
    return extracted_roots[0], temp_dir


def read_manifest(backup_root: Path) -> dict:
    """Load and validate the backup manifest."""
    manifest_path = backup_root / "manifest.json"
    if not manifest_path.exists():
        raise BackupError(f"Backup manifest not found at {manifest_path}.")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def ensure_repo_target(repo_target_dir: Path, force: bool) -> None:
    """Validate the clone target for repository restoration."""
    if repo_target_dir.exists() and any(repo_target_dir.iterdir()):
        if not force:
            raise BackupError(
                f"Repository target {repo_target_dir} is not empty. Use --force to allow reuse."
            )
        for child in repo_target_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    repo_target_dir.mkdir(parents=True, exist_ok=True)


def restore_repository(backup_root: Path, manifest: dict, repo_target_dir: Path, force: bool) -> None:
    """Clone the git bundle into a target directory and check out the saved commit."""
    ensure_repo_target(repo_target_dir, force)

    bundle_relative = manifest["git"]["bundle"]
    bundle_path = backup_root / bundle_relative
    head_commit = manifest["git"]["head_commit"]

    subprocess.run(
        ["git", "clone", str(bundle_path), str(repo_target_dir)],
        check=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_target_dir), "checkout", "--force", head_commit],
        check=True,
        text=True,
    )


def ensure_clean_worktree(project_root: Path, force: bool) -> None:
    """Refuse to overwrite a dirty checkout unless forced."""
    git_dir = project_root / ".git"
    if not git_dir.exists() or force:
        return
    result = subprocess.run(
        ["git", "-C", str(project_root), "status", "--short"],
        capture_output=True,
        text=True,
        check=True,
    )
    if result.stdout.strip():
        raise BackupError(
            f"Project root {project_root} has uncommitted changes. Use --force to overwrite files."
        )


def copy_tree_contents(source_dir: Path, destination_dir: Path) -> None:
    """Copy the full contents of one directory into another."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    for child in source_dir.iterdir():
        target = destination_dir / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def restore_files(backup_root: Path, manifest: dict, project_root: Path, force: bool) -> None:
    """Restore backed-up files into the target project checkout."""
    ensure_clean_worktree(project_root, force)
    payload_root = backup_root / "payload"
    copied = manifest.get("copied_files", {})

    for env_name in copied.get("env_files", []):
        source = payload_root / env_name
        if source.exists():
            shutil.copy2(source, project_root / env_name)

    for relative_file in copied.get("sensitive_files", []):
        source = payload_root / relative_file
        if source.exists():
            destination = project_root / relative_file
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    for relative_dir in copied.get("config_dirs", []):
        source = payload_root / relative_dir
        if source.exists():
            copy_tree_contents(source, project_root / relative_dir)

    for relative_dir in copied.get("required_dirs", []):
        source = payload_root / relative_dir
        if source.exists():
            copy_tree_contents(source, project_root / relative_dir)

    for relative_dir in copied.get("optional_dirs", []):
        source = payload_root / relative_dir
        if source.exists():
            copy_tree_contents(source, project_root / relative_dir)


def restore_database(backup_root: Path, manifest: dict, use_plain_sql: bool, restore_globals: bool) -> None:
    """Restore PostgreSQL globals and the application database from the backup dump."""
    db_config = get_db_config(PROJECT_ROOT)
    dump_info = manifest["database"]["dumps"]
    db_root = backup_root / "payload" / "postgresql"
    env = {**os.environ, "PGPASSWORD": db_config["DB_PASSWORD"]}
    pg_restore, psql, server_major = resolve_restore_tools(db_config)

    if restore_globals and dump_info.get("globals_dump"):
        if _postgres_client_major(psql) != server_major:
            raise BackupError(
                f"psql client {psql} is not compatible with PostgreSQL {server_major}."
            )
        globals_path = db_root / dump_info["globals_dump"]
        subprocess.run(
            [
                psql,
                "-h",
                db_config["DB_HOST"],
                "-p",
                db_config["DB_PORT"],
                "-U",
                db_config["DB_USERNAME"],
                "-f",
                str(globals_path),
                "postgres",
            ],
            env=env,
            check=True,
            text=True,
        )

    if use_plain_sql:
        sql_path = db_root / dump_info["plain_sql_dump"]
        subprocess.run(
            [
                psql,
                "-h",
                db_config["DB_HOST"],
                "-p",
                db_config["DB_PORT"],
                "-U",
                db_config["DB_USERNAME"],
                "-d",
                db_config["DB_NAME"],
                "-f",
                str(sql_path),
            ],
            env=env,
            check=True,
            text=True,
        )
        return

    if not pg_restore:
        raise BackupError(
            "No compatible pg_restore client was found for the PostgreSQL server. "
            f"Install Homebrew postgresql@{server_major} or a matching libpq package."
        )

    dump_path = db_root / dump_info["custom_dump"]
    subprocess.run(
        [
            pg_restore,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "-h",
            db_config["DB_HOST"],
            "-p",
            db_config["DB_PORT"],
            "-U",
            db_config["DB_USERNAME"],
            "-d",
            db_config["DB_NAME"],
            str(dump_path),
        ],
        env=env,
        check=True,
        text=True,
    )


def main() -> int:
    """Restore a backup bundle into a project checkout and PostgreSQL."""
    args = parse_args()
    temp_dir = None
    try:
        backup_path = Path(args.backup_path).expanduser().resolve()
        if not backup_path.exists():
            raise BackupError(f"Backup path does not exist: {backup_path}")

        backup_root, temp_dir = load_backup_root(backup_path)
        manifest = read_manifest(backup_root)
        project_root = Path(args.project_root).expanduser().resolve()

        if args.repo_target_dir:
            repo_target_dir = Path(args.repo_target_dir).expanduser().resolve()
            restore_repository(backup_root, manifest, repo_target_dir, args.force)
            project_root = repo_target_dir

        if not args.skip_files:
            restore_files(backup_root, manifest, project_root, args.force)

        if not args.skip_db:
            restore_database(
                backup_root,
                manifest,
                use_plain_sql=args.use_plain_sql,
                restore_globals=args.restore_globals,
            )
    except BackupError as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    print(f"Restore complete for project root: {project_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())