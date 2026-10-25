"""A tiny to-do list used by the app's UI."""


class TodoList:
    def __init__(self):
        self.items = []
        self._next_id = 1

    def add(self, title):
        item = {"id": self._next_id, "title": title, "done": False}
        self.items.append(item)
        self._next_id += 1
        return item["id"]

    def delete(self, item_id):
        """Called when the user clicks the delete button on a task."""
        self.items = [item for item in self.items if item["id"] != item_id]

    def toggle(self, item_id):
        for item in self.items:
            if item["id"] == item_id:
                item["done"] = not item["done"]
                return

    def titles(self):
        return [item["title"] for item in self.items]
