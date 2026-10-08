"""Selection, filtering and sorting for immutable application snapshots."""


class Table:
    def __init__(self, identity, searchable, sorts, sort_key):
        self.identity = identity
        self.searchable = searchable
        self.sorts = sorts
        self.sort_key = sort_key
        self.query = ''
        self.records = []
        self.entries = []
        self.selected = 0

    @property
    def selected_entry(self):
        return self.entries[self.selected] if self.entries else None

    def update(self, records):
        identity = self.identity(self.selected_entry) if self.selected_entry else None
        self.records = list(records)
        query = self.query.casefold()
        key, reverse = self.sorts[self.sort_key]
        self.entries = sorted((entry for entry in self.records
                               if query in self.searchable(entry).casefold()), key=key, reverse=reverse)
        self.selected = min(self.selected, max(0, len(self.entries) - 1))
        for i, entry in enumerate(self.entries):
            if self.identity(entry) == identity:
                self.selected = i
                break

    def move(self, delta):
        self.selected = max(0, min(len(self.entries) - 1, self.selected + delta))

    def set_query(self, query):
        self.query = query
        self.update(self.records)

    def cycle_sort(self):
        keys = list(self.sorts)
        self.sort_key = keys[(keys.index(self.sort_key) + 1) % len(keys)]
        self.update(self.records)
