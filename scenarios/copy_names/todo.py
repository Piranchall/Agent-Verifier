"""To-do list with a Duplicate button."""


def copy_title(title):
    """Name for a duplicated task."""
    return f"{title} (copy)"


class TodoList:
    def __init__(self):
        self.items = []
        self._next_id = 1

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
        return self.add(copy_title(self.get(item_id)["title"]))
