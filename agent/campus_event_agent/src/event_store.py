"""活动数据存储、校验与确定性检索。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import EVENT_FILE, MAX_RESULTS
from .models import Event


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


# 负责从 JSON 加载活动，提供校验、查询和新增能力。
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

    # 先精确匹配标准类别，再通过别名和子串做宽松匹配。
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

    # 关键词命中名称/类别/地点/描述/来源/标签时打分，用于结果排序。
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
        for token in re.split(r"[\s,，、]+", query):
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

    def to_display_list(self, events: Iterable[Event]) -> list[dict[str, Any]]:
        return [event.display_dict() for event in events]

