"""Deterministic LangChain tools backed by the campus event services."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from langchain_core.tools import tool

from .config import MAX_RESULTS
from .event_store import EventStore
from .interest_matcher import InterestMatcher
from .middleware import Middleware
from .reminder_store import ReminderStore
from .scraper import EventScraper
from .time_parser import parse_time_range


def build_campus_tools(
    store: EventStore,
    reminders: ReminderStore,
    matcher: InterestMatcher,
    scraper: EventScraper,
    middleware: Middleware,
) -> list[Any]:
    """Build the fixed campus tool list used by LangChainAgent."""

    def track(kind: str, detail: str) -> None:
        if middleware is not None:
            middleware.record(kind, detail, 0.0)

    @tool("search_events")
    def search_events(
        query: str = "",
        category: str = "",
        start: str = "",
        end: str = "",
        limit: int = MAX_RESULTS,
    ) -> str:
        """Search campus events by text, category and ISO time range.

        Use this for questions about lectures, competitions, clubs, academic
        notices, cultural activities or volunteer services. Include the original
        wording as query, including time expressions such as "11.15 的活动".
        """
        query = (query or "").strip()
        category = (category or "").strip()
        start = (start or "").strip()
        end = (end or "").strip()
        parsed = parse_time_range(query) if query else None
        if parsed is not None:
            if not start:
                start = parsed.start.isoformat(timespec="seconds")
            if not end:
                end = parsed.end.isoformat(timespec="seconds")
        clean_query = _clean_search_query(query, parsed is not None)
        events = store.search(
            query=clean_query,
            category=category,
            start=start,
            end=end,
            limit=max(1, int(limit or MAX_RESULTS)),
        )
        track("tool.search_events", f"query={query}")
        if not events:
            return "没有找到符合条件的活动。"
        lines = [
            f"{event.name} | {event.time} | {event.location} | {event.category}"
            for event in events
        ]
        return f"找到 {len(events)} 个活动\n" + "\n".join(lines)

    @tool("create_reminder")
    def create_reminder(
        event_name: str,
        event_id: str = "",
        user: str = "default",
        note: str = "",
    ) -> str:
        """Create a due reminder for a campus event by name or event id."""
        event = store.get((event_id or "").strip()) if event_id else None
        if event is None:
            matches = [
                item
                for item in store.events
                if item.name == (event_name or "").strip()
            ]
            if not matches and event_name:
                matches = [
                    item
                    for item in store.events
                    if event_name.strip() in item.name
                ]
            if matches:
                event = matches[0]
        if event is None:
            return f"未找到活动：{event_name}"
        reminder = reminders.create(
            user=user or "default",
            event_id=event.id,
            event_name=event.name,
            due_at=event.time,
            note=note,
        )
        track("tool.create_reminder", f"event_name={event_name}")
        return f"已创建提醒：{reminder.event_name}，时间 {reminder.due_at}。"

    @tool("set_preferences")
    def set_preferences(tags: list[str], user: str = "default") -> str:
        """Set interest tags. Any matching tag triggers a notification."""
        cleaned = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
        prefs = matcher.set_preferences(cleaned, user=user or "default")
        track("tool.set_preferences", ",".join(prefs.tags))
        label = "、".join(prefs.tags) if prefs.tags else "未选择标签"
        return f"偏好已更新：{label}"

    @tool("refresh_events")
    def refresh_events(source: str = "manual") -> str:
        """Fetch the campus feed, add new events and queue unparsable ones."""
        result = scraper.run()
        track("tool.refresh_events", source)
        summary = (
            f"抓取完成：读取 {result.fetched} 条，新增 {result.added} 条，"
            f"跳过 {result.skipped} 条，待人工确认 {result.pending} 条。"
        )
        if result.errors:
            summary += " 错误：" + "；".join(result.errors)
        return summary

    @tool("list_pending_reviews")
    def list_pending_reviews() -> str:
        """List records waiting for human review."""
        pending = scraper.pending()
        track("tool.list_pending_reviews", f"pending={len(pending)}")
        if not pending:
            return "当前没有待审核记录。"
        lines = [
            f"{item.get('id', '')} | {item.get('reason', '')} | {item.get('created_at', '')}"
            for item in pending
            if item.get("status") == "pending"
        ]
        if not lines:
            return "当前没有待审核记录。"
        return "待审核记录：\n" + "\n".join(lines)

    @tool("review_pending")
    def review_pending(id: str, approved: bool = True) -> str:
        """Approve or reject one pending scrape record."""
        ok = str(approved).strip().lower() not in {"0", "false", "no", "否"}
        item = scraper.review(id, ok)
        track("tool.review_pending", f"id={id}, approved={ok}")
        if item is None:
            return f"未找到待审核记录：{id}"
        return f"审核完成：{id} 状态 {item.get('status')}"

    @tool("get_stats")
    def get_stats() -> str:
        """Return event, category and middleware usage statistics."""
        stats = middleware.stats()
        categories = store.categories()
        track("tool.get_stats", "all")
        return (
            f"活动总数：{len(store.events)}；分类数量：{len(categories)}；"
            f"调用次数：{stats.get('total_calls', 0)}；"
            f"总耗时：{stats.get('total_duration_ms', 0)}ms"
        )

    @tool("add_event")
    def add_event(
        name: str,
        time: str,
        location: str,
        category: str = "其他",
        description: str = "",
        tags: str = "",
        duration: str = "",
        contact: str = "",
    ) -> str:
        """Manually add a campus event record (name, time, location required).

        Use this to record an activity the user knows about that is missing
        from the library. The event id is generated automatically. The optional
        duration accepts values like "90 分钟", "1.5 小时" or "2小时30分钟".
        """
        ok, result = store.create_event(
            {
                "name": name,
                "time": time,
                "location": location,
                "category": category or "其他",
                "description": description,
                "tags": tags,
                "duration": duration,
                "contact": contact,
                "source": "Agent 手动录入",
            }
        )
        track("tool.add_event", f"name={name}")
        if not ok:
            return f"新增失败：{result}"
        return f"已新增活动：{result.name}（ID {result.id}，时间 {result.time}）"

    @tool("update_event")
    def update_event(id: str, fields: dict[str, Any]) -> str:
        """Correct an existing event's fields by id (e.g. fix a wrong time or location).

        Pass the event id and a dict of the fields to change, such as
        {"time": "2026-09-20T14:00:00", "location": "教五楼"} or
        {"duration": "90 分钟"}.
        """
        ok, message = store.update_event(id, fields)
        track("tool.update_event", f"id={id}")
        if not ok:
            return f"更新失败：{message}"
        return f"已更新活动 {id}"

    return [
        search_events,
        create_reminder,
        set_preferences,
        refresh_events,
        list_pending_reviews,
        review_pending,
        get_stats,
        add_event,
        update_event,
    ]


def _clean_search_query(text: str, has_time_range: bool) -> str:
    cleaned = _strip_time_expr(text)
    if has_time_range:
        cleaned = re.sub(r"\s*(?:有什么|有哪些|请|帮|我|看|下|的|有)\s*", " ", cleaned)
        tokens = []
        for token in re.split(r"[\s,，。、；]+", cleaned):
            token = re.sub(r"(?:活动|信息)$", "", token.strip())
            if token and token not in {"活动", "信息", "有什么", "有哪些"}:
                tokens.append(token)
        return " ".join(tokens)
    return " ".join(cleaned.split())


def _strip_time_expr(text: str) -> str:
    patterns = [
        r"20\d{2}年\d{1,2}月\d{1,2}日",
        r"\d{1,2}月\d{1,2}日",
        r"\d{1,2}\.\d{1,2}",
        r"\d{4}-\d{2}-\d{2}",
        r"第\s*\d{1,2}\s*周(?:\s*周[一二三四五六日天])?",
        r"(?:本周|这周|下周|本月|这个月|下个月|今天|明天|后天)(?:周[一二三四五六日天])?",
        r"(?:周[一二三四五六日天]|星期[一二三四五六日天])(?:上午|中午|下午|晚上)?",
        r"\d{1,2}[:：]\d{2}",
    ]
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return cleaned
