"""待办提醒的持久化存储，对应项目中的长期记忆。"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import REMINDERS_FILE
from .models import Reminder


# 负责提醒的新增、到期检查、完成和取消，并持久化到 JSON。
class ReminderStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else REMINDERS_FILE
        self.reminders: list[Reminder] = []
        # 可重入锁保护 HTTP 线程和后台提醒线程对同一文件的并发访问。
        self._lock = threading.RLock()
        self.load()

    # 从 JSON 文件恢复提醒列表。
    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self.reminders = []
                return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.reminders = [Reminder.from_dict(item) for item in raw]

    # 把全部提醒写回 JSON，保证重启后长期记忆仍在。
    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps([reminder.to_dict() for reminder in self.reminders], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # 生成唯一提醒 ID 并保存到文件。
    def create(self, user: str, event_id: str, event_name: str, due_at: str, note: str = "") -> Reminder:
        with self._lock:
            reminder = Reminder(
                id=f"REM-{uuid.uuid4().hex[:8].upper()}",
                user=user,
                event_id=event_id,
                event_name=event_name,
                due_at=due_at,
                status="pending",
                created_at=datetime.now().isoformat(timespec="seconds"),
                note=note,
            )
            self.reminders.append(reminder)
            self.save()
            return reminder

    # 返回未通知且到期时间不晚于当前时间的提醒。
    def due(self, now: datetime | None = None) -> list[Reminder]:
        now = now or datetime.now()
        with self._lock:
            return [
                reminder
                for reminder in self.reminders
                if reminder.status == "pending" and self._parse(reminder.due_at) <= now
            ]

    # 把到期提醒标记为已通知并返回，避免同一提醒重复弹出。
    def check_due(self, now: datetime | None = None) -> list[Reminder]:
        """Mark due pending reminders as notified and return them."""
        now = now or datetime.now()
        due = self.due(now)
        if not due:
            return []
        with self._lock:
            for reminder in due:
                reminder.status = "notified"
                reminder.notified_at = now.isoformat(timespec="seconds")
            self.save()
            return due

    # 按到期时间排序返回全部提醒。
    def all(self) -> list[Reminder]:
        with self._lock:
            return sorted(self.reminders, key=lambda item: item.due_at)

    # 用户手动完成提醒后改为 done 状态。
    def complete(self, reminder_id: str) -> bool:
        with self._lock:
            for reminder in self.reminders:
                if reminder.id == reminder_id:
                    reminder.status = "done"
                    self.save()
                    return True
            return False

    # 用户取消提醒后改为 cancelled 状态。
    def cancel(self, reminder_id: str) -> bool:
        with self._lock:
            for reminder in self.reminders:
                if reminder.id == reminder_id:
                    reminder.status = "cancelled"
                    self.save()
                    return True
            return False

    # 按活动 ID 把未完成提醒统一置为 cancelled，返回处理数量。
    def cancel_by_event(self, event_id: str) -> int:
        with self._lock:
            count = 0
            for reminder in self.reminders:
                if reminder.event_id == event_id and reminder.status in {"pending", "notified"}:
                    reminder.status = "cancelled"
                    count += 1
            if count:
                self.save()
            return count

    # 非法时间按最大时间处理，确保不会误判为到期。
    @staticmethod
    def _parse(value: str) -> datetime:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.max
