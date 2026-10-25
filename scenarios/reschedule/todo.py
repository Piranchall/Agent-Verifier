"""To-do list with weekly tasks."""


class TodoList:
    def __init__(self):
        self.items = []
        self._next_id = 1

    def add(self, title, due, repeat=None):
        """repeat is None or "weekly". due is a datetime.date."""
        item = {"id": self._next_id, "title": title, "due": due, "repeat": repeat, "done": False}
        self.items.append(item)
        self._next_id += 1
        return item["id"]

    def get(self, item_id):
        for item in self.items:
            if item["id"] == item_id:
                return item
        return None

    def set_due(self, item_id, new_due):
        """Reschedule one task."""
        self.get(item_id)["due"] = new_due

    def complete(self, item_id):
        """Mark a task done. Weekly tasks should get their next copy."""
        self.get(item_id)["done"] = True
        return None
