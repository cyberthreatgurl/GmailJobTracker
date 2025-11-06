class FakeMessageRecord:
    def __init__(self, data):
        self.__dict__.update(data)

    def save(self):
        pass


class FakeQuerySet:
    def __init__(self):
        self._first = None

    def first(self):
        return self._first

    def set_first(self, obj):
        self._first = obj


class FakeManager:
    def __init__(self):
        self.created = []
        self.queryset = FakeQuerySet()

    def filter(self, **kwargs):
        return self.queryset

    def create(self, **kwargs):
        self.created.append(kwargs)
        return FakeMessageRecord(kwargs)
