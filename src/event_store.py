"""活动数据存储、校验与确定性检索。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import EVENT_FILE, MAX_RESULTS
from .models import Event
from .time_parser import parse_duration


# 类别别名：让“比赛”“分享”等口语词也能命中标准类别。
CATEGORY_ALIASES = {
    "讲座": ["讲座", "分享", "宣讲", "培训"],
    "竞赛": ["竞赛", "比赛", "大赛", "选拔"],
    "社团招新": ["社团", "招新"],
    "教务通知": ["教务", "通知", "报名", "申报", "选课"],
    "文体活动": ["文体", "文化", "体育", "演出", "展览", "马拉松", "市集"],
    "志愿服务": ["志愿", "公益", "服务"],
    "就业指导": ["就业", "职业", "招聘"],
}

# 手动新增活动使用的默认来源标识。
MANUAL_SOURCE = "手动添加"


# 负责从 JSON 加载活动，提供校验、查询、新增、编辑和删除能力。
class EventStore:
    # 默认使用配置中的 events.json，测试时可传入临时路径。
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else EVENT_FILE
        self.events: list[Event] = []
        self.load()

    # 从 JSON 文件读取活动列表；文件不存在时按空数据处理。
    def load(self) -> None:
        if not self.path.exists():
            self.events = []
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.events = [Event.from_dict(item) for item in raw]

    # 以 UTF-8 写回 JSON，保留中文可读性。
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([event.to_dict() for event in self.events], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 校验项目数据质量：至少 20 条、无重复 ID、必填字段完整、时间为 ISO 格式。
    def validate(self) -> list[str]:
        errors: list[str] = []
        if len(self.events) < 20:
            errors.append(f"活动数据少于 20 条，当前 {len(self.events)} 条")
        seen: set[str] = set()
        categories = set()
        for event in self.events:
            if event.id in seen:
                errors.append(f"重复活动 ID: {event.id}")
            seen.add(event.id)
            for field in ("id", "name", "category", "raw_time", "time", "location", "source"):
                if not getattr(event, field):
                    errors.append(f"{event.id or '<无 ID>'} 缺少字段 {field}")
            try:
                datetime.fromisoformat(event.time)
            except ValueError:
                errors.append(f"{event.id} 的 time 不是 ISO 格式: {event.time}")
            categories.add(event.category)
        if len(categories) < 3:
            errors.append("活动类别少于 3 类")
        return errors

    # 返回去重排序后的类别列表，供前端下拉框和统计使用。
    def categories(self) -> list[str]:
        return sorted({event.category for event in self.events})

    # 按 ID 精确查找活动。
    def get(self, event_id: str) -> Event | None:
        for event in self.events:
            if event.id == event_id:
                return event
        return None

    # 三类查询可组合使用：全文检索、类别筛选、时间范围筛选。
    def search(
        self,
        query: str = "",
        category: str = "",
        start: str = "",
        end: str = "",
        limit: int = MAX_RESULTS,
    ) -> list[Event]:
        normalized_query = (query or "").strip().lower()
        start_dt = self._parse_iso(start) if start else None
        end_dt = self._parse_iso(end) if end else None
        results: list[tuple[Event, int]] = []

        for event in self.events:
            if category and not self._category_matches(event, category):
                continue
            if start_dt and self._parse_iso(event.time) < start_dt:
                continue
            if end_dt and self._parse_iso(event.time) > end_dt:
                continue
            score = self._match_score(event, normalized_query)
            if normalized_query and score <= 0:
                continue
            results.append((event, score))

        results.sort(key=lambda item: (self._parse_iso(item[0].time), -item[1]))
        return [event for event, _ in results[:limit]]

    # 新增活动前做 ID 去重和必填字段检查，成功后立即落盘。
    def add_event(self, event: Event) -> tuple[bool, str]:
        if self.get(event.id):
            return False, f"已存在相同 ID: {event.id}"
        if not event.name or not event.time or not event.location:
            return False, "缺少名称、时间或地点"
        self.events.append(event)
        self.save()
        return True, "ok"

    # 便捷新增：不传 ID 时自动生成 EVT-编号，再转成 Event 调用 add_event。
    def create_event(self, data: dict[str, Any]) -> tuple[bool, Event | str]:
        name = str(data.get("name", "")).strip()
        time_value = self._normalize_iso(str(data.get("time", "")).strip())
        location = str(data.get("location", "")).strip()
        if not name or not time_value or not location:
            return False, "缺少名称、时间或地点"

        event_id = str(data.get("id", "")).strip()
        if not event_id:
            event_id = self._next_event_id()
        duration_minutes = self._parse_duration_value(data)
        if duration_minutes is None:
            return False, "持续时间无法解析，示例：90 分钟 / 1.5 小时"
        event = Event(
            id=event_id,
            name=name,
            category=str(data.get("category", "")).strip() or "其他",
            raw_time=str(data.get("raw_time", "")).strip() or time_value,
            time=time_value,
            location=location,
            description=str(data.get("description", "")).strip(),
            source=str(data.get("source", "")).strip() or MANUAL_SOURCE,
            source_url=str(data.get("source_url", "")).strip(),
            tags=self._parse_tags(data.get("tags")),
            duration_minutes=duration_minutes,
            contact=str(data.get("contact", "")).strip(),
        )
        ok, message = self.add_event(event)
        if not ok:
            return False, message
        return True, event

    # 按 ID 更新可编辑字段，校验必填后保存。
    def update_event(self, event_id: str, fields: dict[str, Any]) -> tuple[bool, str]:
        event = self.get(event_id)
        if event is None:
            return False, "活动不存在"
        editable = {
            "name", "category", "time", "location",
            "description", "tags", "contact", "raw_time", "source", "source_url",
        }
        for key, value in fields.items():
            if key == "duration":
                text = str(value).strip()
                if not text:
                    event.duration_minutes = 0
                else:
                    parsed = parse_duration(text)
                    if parsed is None:
                        return False, "持续时间无法解析，示例：90 分钟 / 1.5 小时"
                    event.duration_minutes = parsed
            elif key == "duration_minutes":
                try:
                    minutes = int(value)
                except (TypeError, ValueError):
                    return False, "duration_minutes 必须是非负整数"
                if minutes < 0:
                    return False, "duration_minutes 不能为负数"
                event.duration_minutes = minutes
            elif key not in editable:
                continue
            elif key == "tags":
                event.tags = self._parse_tags(value)
            elif key == "time":
                text = str(value).strip()
                event.time = self._normalize_iso(text) if text else ""
            else:
                setattr(event, key, str(value).strip())
        if not event.name or not event.time or not event.location:
            return False, "缺少名称、时间或地点"
        self.save()
        return True, "ok"

    # 按 ID 删除活动，成功后落盘。
    def delete_event(self, event_id: str) -> tuple[bool, str]:
        for index, event in enumerate(self.events):
            if event.id == event_id:
                del self.events[index]
                self.save()
                return True, "ok"
        return False, "活动不存在"

    # 从请求中解析持续时间：优先 duration 文本，其次 duration_minutes 数字。
    @staticmethod
    def _parse_duration_value(data: dict[str, Any]) -> int | None:
        raw = data.get("duration")
        if raw not in (None, ""):
            return parse_duration(str(raw))
        raw_minutes = data.get("duration_minutes")
        if raw_minutes in (None, ""):
            return 0
        try:
            minutes = int(raw_minutes)
        except (TypeError, ValueError):
            return None
        return minutes if minutes >= 0 else None

    # 生成下一个 EVT 编号：取现有 EVT 数字后缀最大值 +1，冲突时回退到 uuid。
    def _next_event_id(self) -> str:
        max_number = 0
        for event in self.events:
            match = re.fullmatch(r"EVT-(\d+)", event.id)
            if match:
                max_number = max(max_number, int(match.group(1)))
        candidate = f"EVT-{max_number + 1:03d}"
        if self.get(candidate):
            return f"EVT-{uuid.uuid4().hex[:8].upper()}"
        return candidate

    # 先精确匹配标准类别，再通过别名字串做宽松匹配。
    def _category_matches(self, event: Event, category: str) -> bool:
        target = category.strip()
        if event.category == target:
            return True
        for base, aliases in CATEGORY_ALIASES.items():
            if target in aliases and event.category == base:
                return True
            if event.category == base and target in event.category:
                return True
        return False

    # 关键字命中名称/类别/地点/描述/来源/标签时打分，用于结果排序。
    def _match_score(self, event: Event, query: str) -> int:
        if not query:
            return 1
        haystack = " ".join(
            [
                event.name,
                event.category,
                event.location,
                event.description,
                event.source,
                " ".join(event.tags),
            ]
        ).lower()
        if query in haystack:
            return 100
        score = 0
        for token in re.split(r"[\s,，。、]+", query):
            if token and token in haystack:
                score += 1
        return score

    # 非法时间统一退回到最小时间，避免排序或范围比较抛异常。
    @staticmethod
    def _parse_iso(value: str) -> datetime:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.min

    # 把时间统一成 ISO 秒级格式；无法解析时原样返回。
    @staticmethod
    def _normalize_iso(value: str) -> str:
        text = (value or "").strip().replace(" ", "T")
        if not text:
            return ""
        try:
            return datetime.fromisoformat(text).isoformat(timespec="seconds")
        except ValueError:
            return value.strip()

    # 标签兼容逗号/顿号/空格分隔的字符串或列表。
    @staticmethod
    def _parse_tags(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = [str(tag).strip() for tag in value]
        else:
            items = re.split(r"[,\uFF0C\u3001\s]+", str(value).strip())
        return [tag for tag in items if tag]

    def to_display_list(self, events: Iterable[Event]) -> list[dict[str, Any]]:
        return [event.display_dict() for event in events]