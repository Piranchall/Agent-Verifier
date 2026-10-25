"""To-do list with undo."""


class TodoList:
    def __init__(self):
        self.items = []
        self._next_id = 1
        self._undo = []
        self._redo = []

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

    def _record(self, action):
        self._undo.append(action)
        self._redo.clear()

    def delete(self, item_id):
        item = self.get(item_id)
        index = self.items.index(item)
        self.items.remove(item)
        self._record(("delete", index, item))

    def rename(self, item_id, title):
        item = self.get(item_id)
        self._record(("rename", item_id, item["title"], title))
        item["title"] = title

    def toggle(self, item_id):
        item = self.get(item_id)
        item["done"] = not item["done"]
        self._record(("toggle", item_id))

    def _apply(self, action, reverse):
        kind = action[0]
        if kind == "delete":
            _, index, item = action
            if reverse:
                self.items.insert(index, item)
            else:
                self.items.remove(item)
        elif kind == "rename":
            _, item_id, old, new = action
            self.get(item_id)["title"] = old if reverse else new
        elif kind == "toggle":
            item = self.get(action[1])
            item["done"] = not item["done"]

    def undo(self):
        if not self._undo:
            return
        action = self._undo.pop()
        self._apply(action, reverse=True)
        self._redo.append(action)

    def redo(self):
        if not self._redo:
            return
        action = self._redo.pop()
        self._apply(action, reverse=False)
        self._undo.append(action)
