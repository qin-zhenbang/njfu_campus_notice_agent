"""基于标签的兴趣匹配与主动推送。

匹配使用“任一命中”规则：用户选择任意标签后，新活动只要包含其中
至少一个标签，就会生成一条推送通知。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import NOTIFICATIONS_FILE, PREFERENCES_FILE
from .models import Event, UserPreferences


# 偏好和通知各自持久化到 JSON，匹配成功后避免重复推送。
class InterestMatcher:
    def __init__(
        self,
        preferences_path: Path | str | None = None,
        notifications_path: Path | str | None = None,
    ) -> None:
        self.preferences_path = Path(preferences_path) if preferences_path else PREFERENCES_FILE
        self.notifications_path = Path(notifications_path) if notifications_path else NOTIFICATIONS_FILE
        self._lock = threading.RLock()
        self.preferences = self._load_preferences()
        self.notifications = self._load_notifications()

    # 从磁盘重新读取偏好和通知，供多线程/多请求场景使用。
    def reload(self) -> None:
        with self._lock:
            self.preferences = self._load_preferences()
            self.notifications = self._load_notifications()

    # 偏好文件不存在时返回空标签，而不是抛异常。
    def _load_preferences(self) -> UserPreferences:
        if self.preferences_path.exists():
            raw = json.loads(self.preferences_path.read_text(encoding="utf-8"))
            return UserPreferences.from_dict(raw)
        return UserPreferences(user="default", tags=[])

    # 保存用户兴趣标签。
    def save_preferences(self) -> None:
        with self._lock:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            self.preferences_path.write_text(
                json.dumps(self.preferences.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # 通知文件不存在时按空列表处理。
    def _load_notifications(self) -> list[dict[str, Any]]:
        if not self.notifications_path.exists():
            return []
        return json.loads(self.notifications_path.read_text(encoding="utf-8"))

    # 保存推送通知列表。
    def save_notifications(self) -> None:
        with self._lock:
            self.notifications_path.parent.mkdir(parents=True, exist_ok=True)
            self.notifications_path.write_text(
                json.dumps(self.notifications, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # 去重并保存兴趣标签。
    def set_preferences(self, tags: list[str], user: str = "default") -> UserPreferences:
        cleaned = list(dict.fromkeys(str(tag).strip() for tag in tags if str(tag).strip()))
        with self._lock:
            self.preferences = UserPreferences(user=user, tags=cleaned)
            self.save_preferences()
            return self.preferences

    # 在活动名称/类别/地点/描述/来源/标签中查找命中的用户标签。
    def _match_details(self, event: Event) -> list[str]:
        if not self.preferences.tags:
            return []
        searchable = " ".join(
            [
                event.name,
                event.category,
                event.location,
                event.description,
                event.source,
                *event.tags,
            ]
        ).lower()
        matched_tags: list[str] = []
        for tag in self.preferences.tags:
            normalized = tag.strip().lower()
            if normalized and normalized in searchable:
                matched_tags.append(tag)
        return matched_tags

    # 已推送过的活动不再重复推送。
    def evaluate_event(self, event: Event) -> dict | None:
        matched_tags = self._match_details(event)
        with self._lock:
            notified = any(item.get("event_id") == event.id for item in self.notifications)
            if not matched_tags or notified:
                return None
            item = {
                "event_id": event.id,
                "event_name": event.name,
                "time": event.time,
                "location": event.location,
                "category": event.category,
                "user": self.preferences.user,
                "matched_tags": matched_tags,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "read": False,
            }
            self.notifications.append(item)
            self.save_notifications()
            return item

    # 按用户返回通知，返回前重新加载文件。
    def notifications_for(self, user: str = "default") -> list[dict]:
        with self._lock:
            self.reload()
            return [
                item
                for item in self.notifications
                if item.get("user", "default") == user
            ]

    # 把某条活动推送标记为已读。
    def mark_read(self, event_id: str) -> None:
        with self._lock:
            for item in self.notifications:
                if item.get("event_id") == event_id:
                    item["read"] = True
            self.save_notifications()

    # 移除某个活动的全部推送通知，避免悬空引用，返回移除数量。
    def remove_by_event(self, event_id: str) -> int:
        with self._lock:
            before = len(self.notifications)
            self.notifications = [item for item in self.notifications if item.get("event_id") != event_id]
            removed = before - len(self.notifications)
            if removed:
                self.save_notifications()
            return removed


# 兴趣子 Agent：把新入库活动转换成用户可看到的推送。
class InterestAgent:
    """Sub-agent that turns newly stored events into user pushes."""

    def __init__(self, matcher: InterestMatcher, middleware=None) -> None:
        self.matcher = matcher
        self.middleware = middleware

    # 评估单个活动并记录中间件耗时。
    def evaluate_event(self, event: Event, source: str = "new-event") -> dict | None:
        started = time.perf_counter()
        notification = self.matcher.evaluate_event(event)
        if self.middleware:
            self.middleware.record(
                "interest_agent.evaluate",
                f"source={source}, event={event.id}",
                (time.perf_counter() - started) * 1000,
            )
        return notification

    # 批量评估新活动，返回实际推送列表。
    def evaluate_new_events(self, events: list[Event], source: str = "scraper") -> list[dict]:
        started = time.perf_counter()
        pushed: list[dict] = []
        for event in events:
            notification = self.evaluate_event(event, source=source)
            if notification:
                pushed.append(notification)
        if self.middleware and events:
            self.middleware.record(
                "interest_agent.batch",
                f"source={source}, events={len(events)}, pushed={len(pushed)}",
                (time.perf_counter() - started) * 1000,
            )
        return pushed

    # 返回兴趣匹配子 Agent 的开关、标签和未读推送统计。
    def status(self) -> dict[str, Any]:
        self.matcher.reload()
        preferences = self.matcher.preferences
        unread = sum(1 for item in self.matcher.notifications_for() if not item.get("read"))
        return {
            "enabled": bool(preferences.tags),
            "tags": preferences.tags,
            "rule": "any",
            "unread": unread,
        }
