"""To-do list with repeating tasks."""
from datetime import date, timedelta


class TodoList:
    def __init__(self):
        self.items = []
        self._next_id = 1

    def add(self, title, due, repeat=None):
        """repeat is None, "weekly" or "monthly". due is a datetime.date."""
        item = {"id": self._next_id, "title": title, "due": due, "repeat": repeat, "done": False}
        self.items.append(item)
        self._next_id += 1
        return item["id"]

    def get(self, item_id):
        for item in self.items:
            if item["id"] == item_id:
                return item
        return None

    def complete(self, item_id):
        """Mark a task done. Repeating tasks get a new copy with the next due date."""
        item = self.get(item_id)
        item["done"] = True
        if item["repeat"] == "weekly":
            next_due = date.today() + timedelta(days=7)
        elif item["repeat"] == "monthly":
            next_due = item["due"] + timedelta(days=30)
        else:
            return None
        return self.add(item["title"], next_due, item["repeat"])
