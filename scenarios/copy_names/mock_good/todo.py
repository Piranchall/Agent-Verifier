"""To-do list with a Duplicate button."""
import re

COPY_SUFFIX = re.compile(r" \(copy(?: \d+)?\)$")


class TodoList:
    def __init__(self):
        self.items = []
        self._next_id = 1
        self._copy_counts = {}

    def add(self, title):
        item = {"id": self._next_id, "title": title}
        self.items.append(item)
        self._next_id += 1
        return item["id"]

    def get(self, item_id):
        for item in self.items:
            if item["id"] == item_id:
                return item
        return None

    def delete(self, item_id):
        self.items.remove(self.get(item_id))

    def titles(self):
        return [item["title"] for item in self.items]

    def duplicate(self, item_id):
        """Called by the Duplicate button."""
        base = COPY_SUFFIX.sub("", self.get(item_id)["title"])
        n = self._copy_counts.get(base, 0) + 1
        self._copy_counts[base] = n
        return self.add(f"{base} (copy)" if n == 1 else f"{base} (copy {n})")
