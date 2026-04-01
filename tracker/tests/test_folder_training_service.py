from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tracker.models import Message
from tracker.services import folder_training_service


pytestmark = pytest.mark.django_db


def _write_eml(path: Path, subject: str, body: str):
    path.write_text(
        "\n".join(
            [
                'From: "Sender" <sender@example.com>',
                f"Subject: {subject}",
                "Date: Tue, 31 Mar 2026 06:47:08 -0700",
                "To: <user@example.com>",
                'Content-Type: text/plain; charset="utf-8"',
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )


def test_train_model_from_folder_parses_rows_and_does_not_persist_messages(tmp_path, monkeypatch):
    folder = tmp_path / "tests" / "emails" / "spam"
    folder.mkdir(parents=True)
    _write_eml(folder / "sample-1.eml", "Cheap pills", "Buy now and save big.")
    _write_eml(folder / "sample-2.eml", "Weekly deals", "Limited time offer.")

    captured = {}

    def fake_train_message_classifier(extra_training_data=None, verbose=False, persist_metrics=True):
        assert extra_training_data is not None
        captured["extra_training_data"] = extra_training_data.copy()
        captured["verbose"] = verbose
        captured["persist_metrics"] = persist_metrics
        return {
            "output": "training complete",
            "n_samples": len(extra_training_data),
            "n_classes": 1,
            "label_distribution": {"noise": len(extra_training_data)},
            "report": "ok",
        }

    monkeypatch.setattr(
        folder_training_service,
        "train_message_classifier",
        fake_train_message_classifier,
    )

    before_count = Message.objects.count()
    result = folder_training_service.train_model_from_folder(
        "tests/emails/spam",
        "noise",
        base_dir=tmp_path,
        verbose=True,
    )

    assert result["messages_parsed"] == 2
    assert result["messages_persisted"] == 0
    assert Message.objects.count() == before_count
    assert list(captured["extra_training_data"]["label"].unique()) == ["noise"]


def test_collect_training_examples_rejects_unsupported_label(tmp_path):
    folder = tmp_path / "spam"
    folder.mkdir()
    _write_eml(folder / "sample.eml", "Subject", "Body")

    with pytest.raises(folder_training_service.FolderTrainingImportError):
        folder_training_service.collect_training_examples_from_folder(folder, "not_a_label")


def test_resolve_training_folder_rejects_paths_outside_tests_emails(tmp_path):
    allowed_root = tmp_path / "tests" / "emails"
    allowed_root.mkdir(parents=True)
    outside_folder = tmp_path / "outside"
    outside_folder.mkdir()

    with pytest.raises(folder_training_service.FolderTrainingImportError):
        folder_training_service.resolve_training_folder(str(outside_folder), tmp_path)


def test_collect_training_examples_from_csv_applies_selected_label():
    csv_file = SimpleUploadedFile(
        "training.csv",
        b"subject,body\nPromo,Buy now\nAlert,Click here\n",
        content_type="text/csv",
    )

    result = folder_training_service.collect_training_examples_from_csv(csv_file, "noise")

    assert result["file_name"] == "training.csv"
    assert result["row_count"] == 2
    assert list(result["dataframe"]["label"].unique()) == ["noise"]


def test_train_model_from_imports_combines_folder_and_csv_rows(tmp_path, monkeypatch):
    folder = tmp_path / "tests" / "emails" / "spam"
    folder.mkdir(parents=True)
    _write_eml(folder / "sample-1.eml", "Cheap pills", "Buy now and save big.")

    csv_file = SimpleUploadedFile(
        "training.csv",
        b"subject,body\nPromo,Buy now\nAlert,Click here\n",
        content_type="text/csv",
    )
    captured = {}

    def fake_train_message_classifier(extra_training_data=None, verbose=False, persist_metrics=True):
        assert extra_training_data is not None
        captured["extra_training_data"] = extra_training_data.copy()
        _ = (verbose, persist_metrics)
        return {
            "output": "training complete",
            "n_samples": len(extra_training_data),
            "n_classes": 1,
            "label_distribution": {"noise": len(extra_training_data)},
            "report": "ok",
        }

    monkeypatch.setattr(
        folder_training_service,
        "train_message_classifier",
        fake_train_message_classifier,
    )

    result = folder_training_service.train_model_from_imports(
        "tests/emails/spam",
        "noise",
        base_dir=tmp_path,
        csv_file=csv_file,
        csv_train_as="noise",
        verbose=True,
    )

    assert result["messages_parsed"] == 1
    assert result["csv_row_count"] == 2
    assert result["csv_file_name"] == "training.csv"
    assert len(captured["extra_training_data"]) == 3