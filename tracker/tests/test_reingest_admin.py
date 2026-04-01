import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse


pytestmark = pytest.mark.django_db


def test_reingest_admin_requires_train_as_for_folder_import(client, django_user_model, tmp_path):
    user = django_user_model.objects.create_user(username="folder-train-user", password="password")
    client.force_login(user)

    folder = tmp_path / "spam"
    folder.mkdir()

    response = client.post(
        reverse("reingest_admin"),
        {
            "action": "folder_train",
            "training_only": "on",
            "folder_path": str(folder),
            "train_as": "",
        },
    )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Select a 'Train As' label" in body


def test_reingest_admin_shows_default_folder_path(client, django_user_model):
    user = django_user_model.objects.create_user(username="folder-default-user", password="password")
    client.force_login(user)

    response = client.get(reverse("reingest_admin"))

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert 'id="folder-path-select"' in body
    assert '<option value="tests/emails" selected>' in body
    assert 'value="tests/emails/spam"' in body
    assert 'spam</option>' in body


def test_reingest_admin_rejects_folder_outside_dropdown(client, django_user_model):
    user = django_user_model.objects.create_user(username="folder-invalid-user", password="password")
    client.force_login(user)

    response = client.post(
        reverse("reingest_admin"),
        {
            "action": "folder_preview",
            "training_only": "on",
            "folder_path": "../private",
            "train_as": "noise",
        },
    )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Select a folder from the tests/emails dropdown." in body


def test_reingest_admin_requires_csv_label_when_csv_selected(client, django_user_model):
    user = django_user_model.objects.create_user(username="folder-csv-user", password="password")
    client.force_login(user)

    csv_file = SimpleUploadedFile(
        "training.csv",
        b"subject,body\nPromo,Buy now\n",
        content_type="text/csv",
    )

    response = client.post(
        reverse("reingest_admin"),
        {
            "action": "folder_train",
            "training_only": "on",
            "folder_path": "tests/emails",
            "train_as": "noise",
            "include_csv_training": "on",
            "csv_train_as": "",
            "training_csv_file": csv_file,
        },
    )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Select a label for the CSV training file." in body


def test_reingest_admin_folder_preview_shows_summary(client, django_user_model, monkeypatch, tmp_path):
    user = django_user_model.objects.create_user(username="folder-preview-user", password="password")
    client.force_login(user)

    folder = tmp_path / "emails"
    folder.mkdir()

    def fake_resolve_training_folder(folder_path, _base_dir):
        assert folder_path == "tests/emails"
        return folder

    def fake_collect_training_examples_from_folder(resolved_folder, train_as):
        assert resolved_folder == folder
        assert train_as == "noise"
        return {
            "folder_path": str(folder),
            "normalized_label": "noise",
            "discovered_count": 4,
            "parsed_count": 3,
            "parsed_files": ["a.eml", "b.eml", "c.eml"],
            "skipped_count": 1,
            "skipped": [{"file": "d.eml", "reason": "parse failed"}],
            "dataframe": None,
        }

    monkeypatch.setattr(
        "tracker.services.folder_training_service.resolve_training_folder",
        fake_resolve_training_folder,
        raising=False,
    )
    monkeypatch.setattr(
        "tracker.services.folder_training_service.collect_training_examples_from_folder",
        fake_collect_training_examples_from_folder,
        raising=False,
    )

    response = client.post(
        reverse("reingest_admin"),
        {
            "action": "folder_preview",
            "training_only": "on",
            "folder_path": "tests/emails",
            "train_as": "noise",
        },
    )

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Folder Preview" in body
    assert str(folder) in body
    assert "a.eml" in body
    assert "parse failed" in body


def test_reingest_admin_folder_train_uses_training_service(client, django_user_model, monkeypatch, tmp_path):
    user = django_user_model.objects.create_user(username="folder-train-run-user", password="password")
    client.force_login(user)

    folder = tmp_path / "spam"
    folder.mkdir()

    captured = {}

    def fake_train_model_from_imports(
        folder_path,
        train_as,
        *,
        base_dir,
        csv_file=None,
        csv_train_as=None,
        verbose=True,
    ):
        captured["folder_path"] = folder_path
        captured["train_as"] = train_as
        captured["base_dir"] = base_dir
        captured["csv_file"] = csv_file
        captured["csv_train_as"] = csv_train_as
        captured["verbose"] = verbose
        return {
            "folder_path": folder_path,
            "train_as": train_as,
            "messages_parsed": 3,
            "messages_skipped": 0,
            "skipped": [],
            "messages_persisted": 0,
            "csv_file_name": None,
            "csv_train_as": None,
            "csv_row_count": 0,
            "output": "training complete",
            "training_result": {"n_samples": 3, "n_classes": 1},
        }

    monkeypatch.setattr(
        "tracker.services.folder_training_service.train_model_from_imports",
        fake_train_model_from_imports,
        raising=False,
    )

    response = client.post(
        reverse("reingest_admin"),
        {
            "action": "folder_train",
            "training_only": "on",
            "folder_path": "tests/emails/spam",
            "train_as": "noise",
        },
    )

    assert response.status_code == 200
    assert captured["folder_path"] == "tests/emails/spam"
    assert captured["train_as"] == "noise"
    assert captured["csv_file"] is None
    body = response.content.decode("utf-8")
    assert "Folder training import" in body
    assert "Messages persisted: 0" in body


def test_reingest_admin_folder_train_can_include_csv(client, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="folder-train-csv-user", password="password")
    client.force_login(user)

    captured = {}
    csv_file = SimpleUploadedFile(
        "training.csv",
        b"subject,body\nPromo,Buy now\n",
        content_type="text/csv",
    )

    def fake_train_model_from_imports(
        folder_path,
        train_as,
        *,
        base_dir,
        csv_file=None,
        csv_train_as=None,
        verbose=True,
    ):
        _ = (base_dir, verbose)
        captured["folder_path"] = folder_path
        captured["train_as"] = train_as
        captured["csv_file_name"] = csv_file.name if csv_file is not None else None
        captured["csv_train_as"] = csv_train_as
        return {
            "folder_path": folder_path,
            "train_as": train_as,
            "messages_parsed": 3,
            "messages_skipped": 0,
            "skipped": [],
            "messages_persisted": 0,
            "csv_file_name": "training.csv",
            "csv_train_as": "noise",
            "csv_row_count": 1,
            "output": "training complete",
            "training_result": {"n_samples": 4, "n_classes": 1},
        }

    monkeypatch.setattr(
        "tracker.services.folder_training_service.train_model_from_imports",
        fake_train_model_from_imports,
        raising=False,
    )

    response = client.post(
        reverse("reingest_admin"),
        {
            "action": "folder_train",
            "training_only": "on",
            "folder_path": "tests/emails/spam",
            "train_as": "noise",
            "include_csv_training": "on",
            "csv_train_as": "noise",
            "training_csv_file": csv_file,
        },
    )

    assert response.status_code == 200
    assert captured["csv_file_name"] == "training.csv"
    assert captured["csv_train_as"] == "noise"
    body = response.content.decode("utf-8")
    assert "CSV training import: training.csv" in body
    assert "CSV rows: 1" in body