import unittest
from todo import TodoList


class TestDeleteHidden(unittest.TestCase):
    def test_delete_first_task(self):
        t = TodoList()
        a = t.add("buy milk")
        t.add("walk dog")
        t.add("call mom")
        t.delete(a)
        self.assertEqual(t.titles(), ["walk dog", "call mom"])

    def test_delete_after_earlier_delete(self):
        t = TodoList()
        a = t.add("buy milk")
        t.add("walk dog")
        c = t.add("call mom")
        t.delete(a)
        t.delete(c)
        self.assertEqual(t.titles(), ["walk dog"])

    def test_delete_last_task(self):
        t = TodoList()
        t.add("buy milk")
        b = t.add("walk dog")
        t.delete(b)
        self.assertEqual(t.titles(), ["buy milk"])

    def test_delete_middle_after_toggle(self):
        t = TodoList()
        t.add("buy milk")
        b = t.add("walk dog")
        t.add("call mom")
        t.toggle(b)
        t.delete(b)
        self.assertEqual(t.titles(), ["buy milk", "call mom"])
