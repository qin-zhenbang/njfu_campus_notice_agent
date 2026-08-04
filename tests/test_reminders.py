"""待办提醒存储与调度器的测试。"""

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

    def test_cancel_deletes_reminder(self):
        now = datetime(2026, 8, 3, 12, 0, 0)
        reminder = self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="Cancel Event",
            due_at=now.isoformat(),
        )

        self.assertTrue(self.store.cancel(reminder.id))
        self.assertEqual(self.store.all(), [])
        # 重复取消返回 False，因为提醒已被物理删除。
        self.assertFalse(self.store.cancel(reminder.id))

    def test_complete_deletes_reminder(self):
        now = datetime(2026, 8, 3, 12, 0, 0)
        reminder = self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="Complete Event",
            due_at=now.isoformat(),
        )
        self.store.check_due(now)

        self.assertTrue(self.store.complete(reminder.id))
        self.assertEqual(self.store.all(), [])

    def test_cancel_by_event_deletes(self):
        now = datetime(2026, 8, 3, 12, 0, 0)
        first = self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="First Event",
            due_at=now.isoformat(),
        )
        second = self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="Second Event",
            due_at=(now + timedelta(days=1)).isoformat(),
        )
        other = self.store.create(
            user="default",
            event_id="EVT-002",
            event_name="Other Event",
            due_at=(now + timedelta(days=2)).isoformat(),
        )
        self.store.check_due(now)

        count = self.store.cancel_by_event("EVT-001")

        self.assertEqual(count, 2)
        ids = [item.id for item in self.store.all()]
        self.assertNotIn(first.id, ids)
        self.assertNotIn(second.id, ids)
        self.assertIn(other.id, ids)

    def test_prune_keeps_recent_notified(self):
        now = datetime(2026, 8, 3, 12, 0, 0)
        self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="Recent Event",
            due_at=(now - timedelta(minutes=1)).isoformat(),
        )
        self.store.check_due(now)

        self.assertEqual(self.store.prune(now), 0)
        self.assertEqual(len(self.store.all()), 1)

    def test_prune_removes_stale_notified(self):
        now = datetime(2026, 8, 3, 12, 0, 0)
        self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="Stale Event",
            due_at=(now - timedelta(minutes=1)).isoformat(),
        )
        self.store.check_due(now)

        # 超过默认 24 小时保留期后自动删除。
        removed = self.store.prune(now + timedelta(hours=25))

        self.assertEqual(removed, 1)
        self.assertEqual(self.store.all(), [])

    def test_prune_removes_stale_done_and_cancelled(self):
        now = datetime(2026, 8, 3, 12, 0, 0)
        done = self.store.create(
            user="default",
            event_id="EVT-001",
            event_name="Done Event",
            due_at=(now - timedelta(minutes=2)).isoformat(),
        )
        cancelled = self.store.create(
            user="default",
            event_id="EVT-002",
            event_name="Cancelled Event",
            due_at=(now - timedelta(minutes=1)).isoformat(),
        )
        done.status = "done"
        done.notified_at = (now - timedelta(minutes=2)).isoformat()
        cancelled.status = "cancelled"
        cancelled.notified_at = (now - timedelta(minutes=1)).isoformat()
        self.store.save()

        removed = self.store.prune(now + timedelta(hours=25))

        self.assertEqual(removed, 2)
        self.assertEqual(self.store.all(), [])

    def test_retention_disabled_keeps_everything(self):
        path = Path(self.tmp.name) / "reminders_no_cleanup.json"
        store = ReminderStore(path, retention_hours=-1)
        now = datetime(2026, 8, 3, 12, 0, 0)
        store.create(
            user="default",
            event_id="EVT-001",
            event_name="Kept Event",
            due_at=(now - timedelta(minutes=1)).isoformat(),
        )
        store.check_due(now)

        self.assertEqual(store.prune(now + timedelta(days=30)), 0)
        self.assertEqual(len(store.all()), 1)


if __name__ == "__main__":
    unittest.main()