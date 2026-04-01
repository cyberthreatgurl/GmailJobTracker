"""Folder-based training imports for message classification."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from parser import parse_raw_message
from train_model import normalize_training_label, train_message_classifier

TRAINING_FOLDER_ROOT = Path("tests/emails")
TRAINABLE_LABELS = (
    "noise",
    "job_application",
    "other",
    "rejection",
    "interview_invite",
    "prescreen",
)
SUPPORTED_EXTENSIONS = {".eml", ".txt", ".json"}


class FolderTrainingImportError(ValueError):
    """Raised when folder training input is invalid."""


def get_training_folder_root(base_dir: Path) -> Path:
    """Return the resolved root directory allowed for folder training."""
    return (base_dir / TRAINING_FOLDER_ROOT).resolve()


def list_training_folder_options(base_dir: Path) -> list[str]:
    """List allowed training folders under tests/emails, including subfolders."""
    root = get_training_folder_root(base_dir)
    if not root.exists() or not root.is_dir():
        return []

    folders = [root]
    folders.extend(
        path
        for path in sorted(root.rglob("*"))
        if path.is_dir() and not path.name.startswith(".")
    )
    return [folder.relative_to(base_dir).as_posix() for folder in folders]


def resolve_training_folder(folder_path: str, base_dir: Path) -> Path:
    """Resolve a folder path under tests/emails only."""
    raw_path = (folder_path or "").strip()
    if not raw_path:
        raise FolderTrainingImportError("Folder path is required.")

    allowed_root = get_training_folder_root(base_dir)
    path = Path(raw_path)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()

    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise FolderTrainingImportError(
            "Folder must be inside tests/emails."
        ) from exc

    if not path.exists():
        raise FolderTrainingImportError(f"Folder does not exist: {path}")
    if not path.is_dir():
        raise FolderTrainingImportError(f"Path is not a directory: {path}")
    return path


def _parse_json_message(raw_text: str) -> dict[str, str] | None:
    """Parse a JSON-backed message fixture when possible."""
    try:
        payload = json.loads(raw_text)
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    subject = str(payload.get("subject") or payload.get("Subject") or "").strip()
    body = str(payload.get("body") or payload.get("text") or payload.get("snippet") or "").strip()
    if subject or body:
        return {"subject": subject, "body": body}
    return None


def parse_training_email_file(file_path: Path) -> dict[str, str]:
    """Parse a single email-like file into subject/body training fields."""
    raw_text = file_path.read_text(encoding="utf-8", errors="replace")
    if file_path.suffix.lower() == ".json":
        parsed_json = _parse_json_message(raw_text)
        if parsed_json is not None:
            return parsed_json

    metadata = parse_raw_message(raw_text)
    subject = str(metadata.get("subject") or "").strip()
    body = str(metadata.get("body") or "").strip()

    if not subject and not body:
        raise FolderTrainingImportError(f"Could not parse message content from {file_path.name}")

    return {"subject": subject, "body": body}


def collect_training_examples_from_folder(folder_path: Path, train_as: str) -> dict[str, Any]:
    """Collect parsed training rows from a folder without persisting messages."""
    normalized_label = normalize_training_label(train_as)
    if normalized_label not in TRAINABLE_LABELS:
        raise FolderTrainingImportError(f"Unsupported training label: {train_as}")

    files = sorted(
        file_path
        for file_path in folder_path.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not files:
        raise FolderTrainingImportError(
            f"No supported message files found in {folder_path}"
        )

    rows: list[dict[str, str]] = []
    parsed_files: list[str] = []
    skipped: list[dict[str, str]] = []
    for file_path in files:
        try:
            parsed = parse_training_email_file(file_path)
            rows.append(
                {
                    "subject": parsed["subject"],
                    "body": parsed["body"],
                    "label": normalized_label,
                }
            )
            parsed_files.append(file_path.name)
        except Exception as exc:
            skipped.append({"file": file_path.name, "reason": str(exc)})

    if not rows:
        raise FolderTrainingImportError(
            f"No training examples could be parsed from {folder_path}"
        )

    return {
        "folder_path": str(folder_path),
        "normalized_label": normalized_label,
        "discovered_count": len(files),
        "parsed_count": len(rows),
        "parsed_files": parsed_files,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "dataframe": pd.DataFrame(rows),
    }


def collect_training_examples_from_csv(csv_file: Any, train_as: str) -> dict[str, Any]:
    """Collect labeled training rows from an uploaded CSV without persisting messages."""
    normalized_label = normalize_training_label(train_as)
    if normalized_label not in TRAINABLE_LABELS:
        raise FolderTrainingImportError(f"Unsupported training label: {train_as}")
    if csv_file is None:
        raise FolderTrainingImportError("CSV file is required.")

    file_name = Path(str(getattr(csv_file, "name", "training.csv"))).name
    try:
        raw_bytes = csv_file.read()
    except Exception as exc:
        raise FolderTrainingImportError(f"Could not read CSV file {file_name}: {exc}") from exc

    if not raw_bytes:
        raise FolderTrainingImportError(f"CSV file is empty: {file_name}")

    try:
        csv_df = pd.read_csv(BytesIO(raw_bytes))
    except Exception as exc:
        raise FolderTrainingImportError(f"Could not parse CSV file {file_name}: {exc}") from exc

    if csv_df.empty:
        raise FolderTrainingImportError(f"CSV file is empty: {file_name}")
    if "subject" not in csv_df.columns and "body" not in csv_df.columns:
        raise FolderTrainingImportError(
            f"CSV file must include a 'subject' or 'body' column: {file_name}"
        )

    csv_df = csv_df.copy()
    if "subject" not in csv_df.columns:
        csv_df["subject"] = ""
    if "body" not in csv_df.columns:
        csv_df["body"] = ""

    csv_df["subject"] = csv_df["subject"].fillna("").astype(str)
    csv_df["body"] = csv_df["body"].fillna("").astype(str)
    csv_df = csv_df[
        (csv_df["subject"].str.strip() != "") | (csv_df["body"].str.strip() != "")
    ].copy()
    if csv_df.empty:
        raise FolderTrainingImportError(
            f"CSV file does not contain any usable subject/body rows: {file_name}"
        )

    csv_df["label"] = normalized_label
    return {
        "file_name": file_name,
        "normalized_label": normalized_label,
        "row_count": len(csv_df),
        "dataframe": csv_df[["subject", "body", "label"]].copy(),
    }


def train_model_from_imports(
    folder_path: str,
    train_as: str,
    *,
    base_dir: Path,
    csv_file: Any = None,
    csv_train_as: str | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Parse selected imports and retrain using only explicitly provided rows."""
    resolved_folder = resolve_training_folder(folder_path, base_dir)
    folder_collection = collect_training_examples_from_folder(resolved_folder, train_as)

    extra_frames = [folder_collection["dataframe"]]
    csv_collection = None
    if csv_file is not None:
        csv_collection = collect_training_examples_from_csv(csv_file, csv_train_as or "")
        extra_frames.append(csv_collection["dataframe"])

    extra_training_df = pd.concat(extra_frames, ignore_index=True)
    train_result = train_message_classifier(
        extra_training_data=extra_training_df,
        verbose=verbose,
    )

    return {
        "folder_path": folder_collection["folder_path"],
        "train_as": folder_collection["normalized_label"],
        "messages_parsed": folder_collection["parsed_count"],
        "messages_skipped": folder_collection["skipped_count"],
        "skipped": folder_collection["skipped"],
        "messages_persisted": 0,
        "csv_file_name": csv_collection["file_name"] if csv_collection else None,
        "csv_train_as": csv_collection["normalized_label"] if csv_collection else None,
        "csv_row_count": csv_collection["row_count"] if csv_collection else 0,
        "training_result": train_result,
        "output": train_result["output"],
    }


def train_model_from_folder(
    folder_path: str,
    train_as: str,
    *,
    base_dir: Path,
    verbose: bool = True,
) -> dict[str, Any]:
    """Parse a folder of email files and retrain using the selected label."""
    return train_model_from_imports(
        folder_path,
        train_as,
        base_dir=base_dir,
        verbose=verbose,
    )