import unittest
from datetime import date
from todo import TodoList


def d(day, month=3):
    return date(2027, month, day)


class TestWeeklyHidden(unittest.TestCase):
    def test_next_week(self):
        t = TodoList()
        a = t.add("team call", d(3), "weekly")
        self.assertEqual(t.get(t.complete(a))["due"], d(10))

    def test_rescheduled_later_keeps_series_day(self):
        t = TodoList()
        a = t.add("team call", d(3), "weekly")
        t.set_due(a, d(4))
        self.assertEqual(t.get(t.complete(a))["due"], d(10))

    def test_rescheduled_earlier_keeps_series_day(self):
        t = TodoList()
        a = t.add("team call", d(3), "weekly")
        t.set_due(a, d(1))
        self.assertEqual(t.get(t.complete(a))["due"], d(10))

    def test_rescheduled_twice(self):
        t = TodoList()
        a = t.add("team call", d(3), "weekly")
        t.set_due(a, d(4))
        t.set_due(a, d(5))
        self.assertEqual(t.get(t.complete(a))["due"], d(10))

    def test_series_continues_after_reschedule(self):
        t = TodoList()
        a = t.add("team call", d(3), "weekly")
        t.set_due(a, d(4))
        b = t.complete(a)
        c = t.complete(b)
        self.assertEqual((t.get(b)["due"], t.get(c)["due"]), (d(10), d(17)))

    def test_reschedule_a_later_copy(self):
        t = TodoList()
        a = t.add("team call", d(3), "weekly")
        b = t.complete(a)
        t.set_due(b, d(12))
        c = t.complete(b)
        self.assertEqual(t.get(c)["due"], d(17))

    def test_across_month(self):
        t = TodoList()
        a = t.add("team call", d(31), "weekly")
        self.assertEqual(t.get(t.complete(a))["due"], d(7, 4))

    def test_non_weekly(self):
        t = TodoList()
        a = t.add("once", d(3))
        self.assertIsNone(t.complete(a))
        self.assertTrue(t.get(a)["done"])
