"""A tiny to-do list used by the app's UI.

NOTE: the screen keeps a reference to `self.items` and redraws from it,
so code must change that list itself rather than create a new list.
"""


class TodoList:
    def __init__(self):
        self.items = []

    def add(self, title):
        self.items.append({"title": title, "done": False})

    def mark_done(self, title):
        for item in self.items:
            if item["title"] == title:
                item["done"] = True

    def clear_completed(self):
        """Called when the user presses 'Clear completed'."""
        self.items = [item for item in self.items if not item["done"]]

    def titles(self):
        return [item["title"] for item in self.items]
