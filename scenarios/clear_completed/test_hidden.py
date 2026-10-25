import unittest
from todo import TodoList


class TestClearHidden(unittest.TestCase):
    def test_two_done_in_a_row(self):
        t = TodoList()
        for x in ["a", "b", "c"]:
            t.add(x)
        t.mark_done("a")
        t.mark_done("b")
        t.clear_completed()
        self.assertEqual(t.titles(), ["c"])

    def test_screen_sees_the_change(self):
        t = TodoList()
        for x in ["a", "b", "c", "d"]:
            t.add(x)
        screen = t.items  # the UI holds on to this list
        t.mark_done("b")
        t.mark_done("c")
        t.clear_completed()
        self.assertEqual([i["title"] for i in screen], ["a", "d"])

    def test_nothing_done(self):
        t = TodoList()
        t.add("a")
        t.clear_completed()
        self.assertEqual(t.titles(), ["a"])
