"""项目共享的数据模型。

活动、标准化时间、待办提醒和用户偏好都通过 dataclass 定义，
并统一提供 JSON 字典转换能力，方便存储层和 API 层复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


# 活动模型：raw_time 保留原始表达，time 保存标准化后的 ISO 时间。
@dataclass
class Event:
    id: str
    name: str
    category: str
    raw_time: str
    time: str
    location: str
    description: str = ""
    source: str = ""
    source_url: str = ""
    tags: list[str] = field(default_factory=list)
    end_time: str = ""
    contact: str = ""

    @classmethod
    # 从 JSON 字典恢复活动对象，缺省字段使用空值。
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            category=str(data.get("category", "")),
            raw_time=str(data.get("raw_time", "")),
            time=str(data.get("time", "")),
            location=str(data.get("location", "")),
            description=str(data.get("description", "")),
            source=str(data.get("source", "")),
            source_url=str(data.get("source_url", "")),
            tags=[str(tag) for tag in data.get("tags", [])],
            end_time=str(data.get("end_time", "")),
            contact=str(data.get("contact", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # 对外展示时把内部 time 字段映射为需求要求的 standard_time。
    def display_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "standard_time": self.time,
            "duration": self._format_duration(),
            "raw_time": self.raw_time,
            "location": self.location,
            "category": self.category,
            "source": self.source,
            "description": self.description,
            "tags": self.tags,
        }

    # 根据开始时间和结束时间计算可读时长；缺失或格式错误时返回 "-"。
    def _format_duration(self) -> str:
        if not self.end_time:
            return "-"
        try:
            start = datetime.fromisoformat(self.time)
            end = datetime.fromisoformat(self.end_time)
        except ValueError:
            return "-"
        minutes = int((end - start).total_seconds() // 60)
        if minutes <= 0:
            return "-"
        hours, remainder = divmod(minutes, 60)
        if hours and remainder:
            return f"{hours}小时{remainder}分钟"
        if hours:
            return f"{hours}小时"
        return f"{remainder}分钟"


# 时间解析结果：start/end 用于范围筛选，display 用于直接展示。
@dataclass
class ParsedTime:
    start: datetime
    end: datetime
    kind: str
    display: str


# 待办提醒模型，status 表示 pending/notified/done/cancelled 等状态。
@dataclass
class Reminder:
    id: str
    user: str
    event_id: str
    event_name: str
    due_at: str
    status: str = "pending"
    created_at: str = ""
    note: str = ""
    notified_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Reminder":
        return cls(
            id=str(data.get("id", "")),
            user=str(data.get("user", "")),
            event_id=str(data.get("event_id", "")),
            event_name=str(data.get("event_name", "")),
            due_at=str(data.get("due_at", "")),
            status=str(data.get("status", "pending")),
            created_at=str(data.get("created_at", "")),
            note=str(data.get("note", "")),
            notified_at=str(data.get("notified_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 用户兴趣偏好：tags 中的任一标签命中新活动即可触发推送。
@dataclass
class UserPreferences:
    user: str
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserPreferences":
        return cls(
            user=str(data.get("user", "default")),
            tags=[str(tag) for tag in data.get("tags", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
