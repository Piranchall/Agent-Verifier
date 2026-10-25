import unittest
from datetime import date
from todo import TodoList


class TestRepeatHidden(unittest.TestCase):
    def test_monthly_mid_month(self):
        t = TodoList()
        a = t.add("pay rent", date(2027, 3, 15), "monthly")
        self.assertEqual(t.get(t.complete(a))["due"], date(2027, 4, 15))

    def test_month_end_clamps(self):
        t = TodoList()
        a = t.add("report", date(2027, 1, 31), "monthly")
        self.assertEqual(t.get(t.complete(a))["due"], date(2027, 2, 28))

    def test_month_end_goes_back_to_original_day(self):
        t = TodoList()
        a = t.add("report", date(2027, 1, 31), "monthly")
        b = t.complete(a)
        c = t.complete(b)
        d = t.complete(c)
        self.assertEqual([t.get(x)["due"] for x in (b, c, d)],
                         [date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)])

    def test_leap_year(self):
        t = TodoList()
        a = t.add("report", date(2028, 1, 31), "monthly")
        self.assertEqual(t.get(t.complete(a))["due"], date(2028, 2, 29))

    def test_year_rollover(self):
        t = TodoList()
        a = t.add("dues", date(2027, 12, 15), "monthly")
        self.assertEqual(t.get(t.complete(a))["due"], date(2028, 1, 15))

    def test_weekly_counts_from_due_date(self):
        t = TodoList()
        a = t.add("gym", date(2027, 1, 4), "weekly")
        self.assertEqual(t.get(t.complete(a))["due"], date(2027, 1, 11))

    def test_new_copy_not_done_and_old_done(self):
        t = TodoList()
        a = t.add("gym", date(2027, 1, 4), "weekly")
        b = t.complete(a)
        self.assertTrue(t.get(a)["done"])
        self.assertFalse(t.get(b)["done"])

    def test_non_repeating_returns_none(self):
        t = TodoList()
        a = t.add("once", date(2027, 1, 4))
        self.assertIsNone(t.complete(a))
