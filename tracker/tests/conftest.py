# conftest.py

import pytest

@pytest.fixture
def fake_stats():
    class Stats:
        total_ignored = 0
        total_skipped = 0
        total_inserted = 0
        def save(self): pass
    return Stats()

@pytest.fixture
def fake_message_model(monkeypatch):
    class FakeQuerySet:
        def __init__(self, exists=False): self._exists = exists
        def exists(self): return self._exists

    class FakeManager:
        def __init__(self): self.created = []
        def filter(self, **kwargs): return FakeQuerySet(exists=False)
        def create(self, **kwargs): self.created.append(kwargs)

    fake_manager = FakeManager()
    
    class FakeMessage:
        objects = fake_manager

   # Patch parser.Message with our fake class
    monkeypatch.setattr("parser.Message", FakeMessage)

    return fake_manager