"""To-do list with repeating tasks."""
import calendar
from datetime import date, timedelta


class TodoList:
    def __init__(self):
        self.items = []
        self._next_id = 1

    def add(self, title, due, repeat=None, anchor_day=None):
        """repeat is None, "weekly" or "monthly". due is a datetime.date."""
        item = {"id": self._next_id, "title": title, "due": due, "repeat": repeat, "done": False,
                "anchor_day": anchor_day or due.day}
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
            next_due = item["due"] + timedelta(days=7)
        elif item["repeat"] == "monthly":
            year, month = item["due"].year, item["due"].month + 1
            if month == 13:
                year, month = year + 1, 1
            day = min(item["anchor_day"], calendar.monthrange(year, month)[1])
            next_due = date(year, month, day)
        else:
            return None
        return self.add(item["title"], next_due, item["repeat"], item["anchor_day"])
