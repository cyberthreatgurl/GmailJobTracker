class FakeMessageRecord:
    def __init__(self, data):
        self.__dict__.update(data)
        # Provide defaults expected by parser logic
        if not hasattr(self, "reviewed"):
            self.reviewed = False
        if not hasattr(self, "company"):
            self.company = None
        if not hasattr(self, "company_source"):
            self.company_source = ""

    def save(self):
        pass


class FakeQuerySet:
    def __init__(self):
        self._first = None

    def first(self):
        return self._first

    def set_first(self, obj):
        self._first = obj

    # New helper to match Django QuerySet API used in parser.py
    def exists(self):
        return self._first is not None


class FakeManager:
    def __init__(self):
        self.created = []
        self.queryset = FakeQuerySet()
        self._objects = {}  # msg_id -> FakeMessageRecord cache for get()

    def filter(self, **kwargs):
        return self.queryset

    def create(self, **kwargs):
        record = FakeMessageRecord(kwargs)
        self.created.append(kwargs)
        # Cache by msg_id for future get() calls
        if "msg_id" in kwargs:
            self._objects[kwargs["msg_id"]] = record
        return record

    def get(self, **kwargs):
        """
        Minimal get() support for tests. Looks up by msg_id if available.
        If not found in cache, returns created record with matching msg_id if exists.
        """
        msg_id = kwargs.get("msg_id")
        if msg_id and msg_id in self._objects:
            return self._objects[msg_id]
        # If not cached, search created list for a matching msg_id
        for rec_data in self.created:
            if rec_data.get("msg_id") == msg_id:
                return FakeMessageRecord(rec_data)
        # If still not found, raise DoesNotExist to mimic Django behavior
        from tracker.models import Message

        raise Message.DoesNotExist(f"Message with msg_id={msg_id} not found")
