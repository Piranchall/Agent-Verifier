import unittest
from todo import TodoList


class TestUndo(unittest.TestCase):
    def test_undo_rename(self):
        t = TodoList()
        a = t.add("buy milk")
        t.rename(a, "buy oat milk")
        t.undo()
        self.assertEqual(t.titles(), ["buy milk"])
