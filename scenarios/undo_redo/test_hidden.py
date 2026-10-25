import unittest
from todo import TodoList


def make(*titles):
    t = TodoList()
    ids = [t.add(x) for x in titles]
    return t, ids


class TestUndoHidden(unittest.TestCase):
    def test_undo_rename(self):
        t, (a,) = make("buy milk")
        t.rename(a, "buy oat milk")
        t.undo()
        self.assertEqual(t.titles(), ["buy milk"])

    def test_undo_delete_same_place_same_id(self):
        t, (a, b, c) = make("a", "b", "c")
        t.delete(b)
        t.undo()
        self.assertEqual(t.titles(), ["a", "b", "c"])
        self.assertEqual(t.get(b)["title"], "b")

    def test_undo_toggle(self):
        t, (a,) = make("a")
        t.toggle(a)
        t.undo()
        self.assertFalse(t.get(a)["done"])

    def test_newest_first(self):
        t, (a, b) = make("a", "b")
        t.rename(a, "x")
        t.delete(b)
        t.undo()
        self.assertEqual(t.titles(), ["x", "b"])
        t.undo()
        self.assertEqual(t.titles(), ["a", "b"])

    def test_two_deletes_restore_positions(self):
        t, (a, b, c, d) = make("a", "b", "c", "d")
        t.delete(b)
        t.delete(d)
        t.undo()
        t.undo()
        self.assertEqual(t.titles(), ["a", "b", "c", "d"])

    def test_redo(self):
        t, (a,) = make("a")
        t.rename(a, "x")
        t.undo()
        t.redo()
        self.assertEqual(t.titles(), ["x"])

    def test_redo_then_undo_again(self):
        t, (a, b) = make("a", "b")
        t.delete(a)
        t.undo()
        t.redo()
        self.assertEqual(t.titles(), ["b"])
        t.undo()
        self.assertEqual(t.titles(), ["a", "b"])

    def test_new_action_clears_redo(self):
        t, (a, b) = make("a", "b")
        t.rename(a, "x")
        t.undo()
        t.toggle(b)
        t.redo()
        self.assertEqual(t.titles(), ["a", "b"])

    def test_empty_undo_redo_do_nothing(self):
        t, _ = make("a")
        t.undo()
        t.redo()
        self.assertEqual(t.titles(), ["a"])
