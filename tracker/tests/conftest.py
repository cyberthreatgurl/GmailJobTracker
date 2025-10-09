import pytest
from tracker.tests.test_helpers import FakeManager

@pytest.fixture
def fake_message_model(monkeypatch):
    fake_manager = FakeManager()

    class FakeMessage:
        objects = fake_manager

    monkeypatch.setattr("parser.Message", FakeMessage)
    return fake_manager.queryset, fake_manager

@pytest.fixture
def fake_stats():
    class Stats:
        total_ignored = 0
        total_skipped = 0
        total_inserted = 0
        def save(self): pass
    return Stats()