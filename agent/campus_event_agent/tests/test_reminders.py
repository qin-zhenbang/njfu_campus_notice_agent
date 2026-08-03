"""Reminder store and scheduler tests."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from src.reminder_store import ReminderStore
from src.scheduler import ReminderScheduler


class ReminderStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ReminderStore(Path(self.tmp.name) / "reminders.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_due_marks_notified_once(self):
        now = datetime(2026, 8, 3, 12, 0, 0)
        self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="Test Event",
            due_at=(now - timedelta(seconds=1)).isoformat(),
        )
        self.store.create(
            user="default",
            event_id="EVT-002",
            event_name="Future Event",
            due_at=(now + timedelta(days=1)).isoformat(),
        )

        due = self.store.check_due(now)

        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].event_name, "Test Event")
        self.assertEqual(due[0].status, "notified")
        self.assertTrue(due[0].notified_at)
        self.assertEqual(self.store.due(now), [])
        self.assertEqual(self.store.check_due(now), [])

    def test_scheduler_check_now_uses_store(self):
        self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="Scheduled Event",
            due_at=(datetime.now() - timedelta(seconds=1)).isoformat(),
        )
        scheduler = ReminderScheduler(self.store, interval_seconds=60)

        due = scheduler.check_now()

        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].status, "notified")

    def test_complete_after_notified(self):
        now = datetime(2026, 8, 3, 12, 0, 0)
        reminder = self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="Complete Event",
            due_at=now.isoformat(),
        )
        self.store.check_due(now)

        self.assertTrue(self.store.complete(reminder.id))
        self.assertEqual(self.store.all()[0].status, "done")


if __name__ == "__main__":
    unittest.main()
