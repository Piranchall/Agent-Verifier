import unittest
from todo import TodoList


class TestClear(unittest.TestCase):
    def test_two_done_in_a_row(self):
        t = TodoList()
        for x in ["a", "b", "c"]:
            t.add(x)
        t.mark_done("a")
        t.mark_done("b")
        t.clear_completed()
        self.assertEqual(t.titles(), ["c"])
