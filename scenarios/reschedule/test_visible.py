import unittest
from datetime import date
from todo import TodoList


class TestWeekly(unittest.TestCase):
    def test_next_week(self):
        t = TodoList()
        a = t.add("team call", date(2027, 3, 3), "weekly")
        b = t.complete(a)
        self.assertEqual(t.get(b)["due"], date(2027, 3, 10))
