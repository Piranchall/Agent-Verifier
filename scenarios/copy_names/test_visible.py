import unittest
from todo import TodoList


class TestCopyNames(unittest.TestCase):
    def test_two_copies(self):
        t = TodoList()
        a = t.add("Report")
        t.duplicate(a)
        t.duplicate(a)
        self.assertEqual(t.titles(), ["Report", "Report (copy)", "Report (copy 2)"])
