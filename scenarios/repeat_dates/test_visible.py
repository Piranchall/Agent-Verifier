import unittest
from datetime import date
from todo import TodoList


class TestRepeat(unittest.TestCase):
    def test_monthly_mid_month(self):
        t = TodoList()
        a = t.add("pay rent", date(2027, 3, 15), "monthly")
        b = t.complete(a)
        self.assertEqual(t.get(b)["due"], date(2027, 4, 15))
