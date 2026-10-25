"""To-do list with undo."""


class TodoList:
    def __init__(self):
        self.items = []
        self._next_id = 1
        self._undo = []

    def add(self, title):
        item = {"id": self._next_id, "title": title, "done": False}
        self.items.append(item)
        self._next_id += 1
        return item["id"]

    def get(self, item_id):
        for item in self.items:
            if item["id"] == item_id:
                return item
        return None

    def titles(self):
        return [item["title"] for item in self.items]

    def delete(self, item_id):
        item = self.get(item_id)
        self.items.remove(item)
        self._undo.append(("delete", item["title"]))

    def rename(self, item_id, title):
        self.get(item_id)["title"] = title

    def toggle(self, item_id):
        item = self.get(item_id)
        item["done"] = not item["done"]

    def undo(self):
        if not self._undo:
            return
        kind, title = self._undo.pop()
        if kind == "delete":
            self.add(title)

    def redo(self):
        pass  # not implemented yet
