"""待办提醒的持久化存储，对应项目中的长期记忆。"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import REMINDERS_FILE, REMINDER_RETENTION_HOURS
from .models import Reminder


# 负责提醒的新增、到期检查、完成和取消，并持久化到 JSON。
# 取消/完成会物理删除提醒；到点提醒（notified）超过保留期后会被自动清理。
class ReminderStore:
    def __init__(
        self,
        path: Path | str | None = None,
        retention_hours: float | None = None,
    ) -> None:
        self.path = Path(path) if path else REMINDERS_FILE
        self.reminders: list[Reminder] = []
        # 可重入锁保护 HTTP 线程和后台提醒线程对同一文件的并发访问。
        self._lock = threading.RLock()
        # 保留期（小时）：不传时读配置；传负数表示不自动清理。
        if retention_hours is None:
            self.retention_hours = REMINDER_RETENTION_HOURS
        else:
            self.retention_hours = retention_hours
        self.load()

    # 从 JSON 文件恢复提醒列表，并顺带清理过期的终态提醒。
    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self.reminders = []
                return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.reminders = [Reminder.from_dict(item) for item in raw]
            self.prune()

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
    # 标记前先清理超过保留期的旧提醒，标记后新触发的提醒继续展示。
    def check_due(self, now: datetime | None = None) -> list[Reminder]:
        """把到期的 pending 提醒标记为已通知并返回，避免重复弹出；同时清理过期终态提醒。"""
        now = now or datetime.now()
        self.prune(now)
        due = self.due(now)
        if not due:
            return []
        with self._lock:
            for reminder in due:
                reminder.status = "notified"
                reminder.notified_at = now.isoformat(timespec="seconds")
            self.save()
            return due

    # 按到期时间排序返回全部提醒，顺带清理过期终态提醒。
    def all(self) -> list[Reminder]:
        with self._lock:
            self.prune()
            return sorted(self.reminders, key=lambda item: item.due_at)

    # 用户手动完成提醒后物理删除，视为已处理不再保留。
    def complete(self, reminder_id: str) -> bool:
        return self.delete(reminder_id)

    # 用户取消提醒后物理删除。
    def cancel(self, reminder_id: str) -> bool:
        return self.delete(reminder_id)

    # 按 ID 物理删除提醒并保存，返回是否删除成功。
    def delete(self, reminder_id: str) -> bool:
        with self._lock:
            before = len(self.reminders)
            self.reminders = [reminder for reminder in self.reminders if reminder.id != reminder_id]
            if len(self.reminders) == before:
                return False
            self.save()
            return True

    # 按活动 ID 把未完成提醒统一删除，返回处理数量。
    def cancel_by_event(self, event_id: str) -> int:
        with self._lock:
            before = len(self.reminders)
            self.reminders = [
                reminder
                for reminder in self.reminders
                if not (reminder.event_id == event_id and reminder.status in {"pending", "notified"})
            ]
            removed = before - len(self.reminders)
            if removed:
                self.save()
            return removed

    # 自动清理超过保留期的终态提醒（notified/done/cancelled），返回删除数量。
    def prune(self, now: datetime | None = None) -> int:
        if self.retention_hours is None or self.retention_hours < 0:
            return 0
        now = now or datetime.now()
        with self._lock:
            before = len(self.reminders)
            self.reminders = [
                reminder
                for reminder in self.reminders
                if not self._is_stale_terminal(reminder, now)
            ]
            removed = before - len(self.reminders)
            if removed:
                self.save()
            return removed

    # 终态提醒是否已超过保留期；参照时间优先取 notified_at，其次 created_at、due_at。
    def _is_stale_terminal(self, reminder: Reminder, now: datetime) -> bool:
        if reminder.status not in {"notified", "done", "cancelled"}:
            return False
        reference = self._terminal_reference(reminder)
        if reference is None:
            return False
        return (now - reference).total_seconds() >= self.retention_hours * 3600

    # 取终态时间参照；时间缺失或非法时返回 None，宁可保留也不误删。
    @staticmethod
    def _terminal_reference(reminder: Reminder) -> datetime | None:
        for value in (reminder.notified_at, reminder.created_at, reminder.due_at):
            parsed = ReminderStore._parse_optional(value)
            if parsed is not None:
                return parsed
        return None

    # 非法时间返回 None。
    @staticmethod
    def _parse_optional(value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    # 非法时间按最大时间处理，确保不会误判为到期。
    @staticmethod
    def _parse(value: str) -> datetime:
        parsed = ReminderStore._parse_optional(value)
        return parsed if parsed is not None else datetime.max