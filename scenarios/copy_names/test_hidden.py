import unittest
from todo import TodoList


class TestCopyNamesHidden(unittest.TestCase):
    def test_two_copies(self):
        t = TodoList()
        a = t.add("Report")
        t.duplicate(a)
        t.duplicate(a)
        self.assertEqual(t.titles(), ["Report", "Report (copy)", "Report (copy 2)"])

    def test_copy_of_copy_uses_original(self):
        t = TodoList()
        a = t.add("Report")
        b = t.duplicate(a)
        c = t.duplicate(b)
        self.assertEqual(t.get(c)["title"], "Report (copy 2)")

    def test_numbers_not_reused_after_delete(self):
        t = TodoList()
        a = t.add("Report")
        t.duplicate(a)
        b = t.duplicate(a)
        t.delete(b)
        c = t.duplicate(a)
        self.assertEqual(t.get(c)["title"], "Report (copy 3)")

    def test_first_copy_deleted_not_reused(self):
        t = TodoList()
        a = t.add("Report")
        b = t.duplicate(a)
        t.delete(b)
        c = t.duplicate(a)
        self.assertEqual(t.get(c)["title"], "Report (copy 2)")

    def test_separate_tasks_count_separately(self):
        t = TodoList()
        a = t.add("Report")
        b = t.add("Budget")
        t.duplicate(a)
        c = t.duplicate(b)
        self.assertEqual(t.get(c)["title"], "Budget (copy)")

    def test_returns_new_id(self):
        t = TodoList()
        a = t.add("Report")
        b = t.duplicate(a)
        self.assertNotEqual(a, b)
        self.assertEqual(t.get(a)["title"], "Report")
