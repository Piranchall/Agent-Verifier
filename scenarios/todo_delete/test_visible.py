import unittest
from todo import TodoList


class TestDelete(unittest.TestCase):
    def test_delete_first_task(self):
        t = TodoList()
        a = t.add("buy milk")
        t.add("walk dog")
        t.add("call mom")
        t.delete(a)
        self.assertEqual(t.titles(), ["walk dog", "call mom"])
