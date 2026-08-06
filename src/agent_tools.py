"""基于校园活动服务封装的一批确定性 LangChain 工具。"""

from __future__ import annotations

import contextvars
import re
from datetime import datetime
from typing import Any, Callable

from langchain_core.tools import tool

from .config import MAX_RESULTS
from .event_store import EventStore
from .interest_matcher import InterestMatcher
from .middleware import Middleware
from .reminder_store import ReminderStore
from .scraper import EventScraper
from .time_parser import parse_time_range


# 写操作确认层：Chat 入口调用前设置当前会话，工具闭包据此判断是否需要确认。
_current_session: contextvars.ContextVar[str] = contextvars.ContextVar(
    "campus_agent_session", default=""
)
# 待确认操作：key 为 "session_id:action_key"，value 存 {description, execute}。
_pending_actions: dict[str, dict] = {}


def _confirmable(
    action_key: str,
    execute_fn: Callable[[], str],
    description: str,
) -> str:
    """给写操作工具加确认：首次调用只记录待确认，用户确认后重入直接执行。

    action_key 唯一标识某次操作，description 是展示给用户的确认文案。
    """
    session_id = _current_session.get()
    if not session_id:
        # 无会话上下文（如测试直调）时不阻塞，直接执行。
        return execute_fn()

    full_key = f"{session_id}:{action_key}"
    for key in _pending_actions:
        if key.startswith(f"{session_id}:"):
            if key == full_key:
                # 确认后重入：执行并清理。
                return _pending_actions.pop(full_key)["execute"]()
            return (
                "【已有待确认操作】请先确认或取消上一操作："
                f"{_pending_actions[key]['description']}"
            )

    _pending_actions[full_key] = {
        "description": description,
        "execute": execute_fn,
    }
    return f"【待确认】{description}。回复「确认」执行，回复「取消」放弃。"


def build_campus_tools(
    store: EventStore,
    reminders: ReminderStore,
    matcher: InterestMatcher,
    scraper: EventScraper,
    middleware: Middleware,
) -> list[Any]:
    """构建校园 Agent（主 Agent 与子 Agent 共用）的固定校园工具列表。"""

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
        """按文本、类别和 ISO 时间范围检索校园活动。

        适用于讲座、竞赛、社团、教务通知、文体活动或志愿服务等查询；
        把用户原话（含 “11.15 的活动” 这类时间表达）作为 query 传入。
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
        """按活动名称或 ID 为校园活动创建到点提醒。"""
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

        def execute() -> str:
            reminder = reminders.create(
                user=user or "default",
                event_id=event.id,
                event_name=event.name,
                due_at=event.time,
                note=note,
            )
            track("tool.create_reminder", f"event_name={event_name}")
            return f"已创建提醒：{reminder.event_name}，时间 {reminder.due_at}。"

        return _confirmable(
            f"reminder:{event.id or event_name}",
            execute,
            f"创建提醒：{event.name}（时间：{event.time}）",
        )

    @tool("set_preferences")
    def set_preferences(tags: list[str], user: str = "default") -> str:
        """设置兴趣标签，任一标签命中新活动即触发推送。"""
        cleaned = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]

        def execute() -> str:
            prefs = matcher.set_preferences(cleaned, user=user or "default")
            track("tool.set_preferences", ",".join(prefs.tags))
            label = "、".join(prefs.tags) if prefs.tags else "未选择标签"
            return f"偏好已更新：{label}"

        label = "、".join(cleaned) if cleaned else "未选择标签"
        return _confirmable(
            f"prefs:{','.join(cleaned)}",
            execute,
            f"设置偏好为：{label}",
        )

    @tool("refresh_events")
    def refresh_events(source: str = "manual") -> str:
        """抓取校园活动源，新增活动并把无法解析的记录放入待审核。"""
        def execute() -> str:
            result = scraper.run()
            track("tool.refresh_events", source)
            summary = (
                f"抓取完成：读取 {result.fetched} 条，新增 {result.added} 条，"
                f"跳过 {result.skipped} 条，待人工确认 {result.pending} 条。"
            )
            if result.errors:
                summary += " 错误：" + "；".join(result.errors)
            return summary

        return _confirmable(
            "refresh",
            execute,
            "抓取校园活动更新",
        )

    @tool("list_pending_reviews")
    def list_pending_reviews() -> str:
        """列出等待人工审核的记录。"""
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
        """批准或拒绝某条待人工审核的抓取记录。"""
        ok = str(approved).strip().lower() not in {"0", "false", "no", "否"}

        def execute() -> str:
            item = scraper.review(id, ok)
            track("tool.review_pending", f"id={id}, approved={ok}")
            if item is None:
                return f"未找到待审核记录：{id}"
            return f"审核完成：{id} 状态 {item.get('status')}"

        action = "通过" if ok else "拒绝"
        return _confirmable(
            f"review:{id}",
            execute,
            f"{action}待审核记录 {id}",
        )

    @tool("get_stats")
    def get_stats() -> str:
        """返回活动、类别和中间件调用统计。"""
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
        """手动新增一条校园活动记录（名称、时间、地点为必填）。

        用于把用户知道但库里缺失的活动补充进来。活动 ID 自动生成；
        可选 duration 支持 “90 分钟”“1.5 小时”“2小时30分钟” 等写法。
        """
        payload = {
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

        def execute() -> str:
            ok, result = store.create_event(dict(payload))
            track("tool.add_event", f"name={name}")
            if not ok:
                return f"新增失败：{result}"
            return f"已新增活动：{result.name}（ID {result.id}，时间 {result.time}）"

        return _confirmable(
            f"add:{name}",
            execute,
            f"新增活动：{name}（时间：{time}，地点：{location}）",
        )

    @tool("update_event")
    def update_event(id: str, fields: dict[str, Any]) -> str:
        """按 ID 修正已有活动字段（例如改正时间或地点）。

        传入活动 ID 和要修改的字段字典，例如
        {"time": "2026-09-20T14:00:00", "location": "教五楼"} 或
        {"duration": "90 分钟"}。
        """
        field_summary = (
            "、".join(f"{key}={value}" for key, value in (fields or {}).items())
            or "（无字段）"
        )

        def execute() -> str:
            ok, message = store.update_event(id, fields)
            track("tool.update_event", f"id={id}")
            if not ok:
                return f"更新失败：{message}"
            return f"已更新活动 {id}"

        return _confirmable(
            f"update:{id}",
            execute,
            f"修改活动 {id}：{field_summary}",
        )

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
            if token and not re.fullmatch(r"\d{1,2}(?:日|号)", token) and token not in {"活动", "信息", "有什么", "有哪些", "上午", "中午", "下午", "晚上", "今晚", "凌晨", "到", "至", "~", "～", "-"}:
                tokens.append(token)
        return " ".join(tokens)
    return " ".join(cleaned.split())


def _strip_time_expr(text: str) -> str:
    patterns = [
        r"20\d{2}年\d{1,2}月\d{1,2}(?:日|号)",
        r"\d{1,2}月\d{1,2}(?:日|号)",
        r"\d{1,2}\.\d{1,2}",
        r"\d{4}-\d{2}-\d{2}",
        r"第\s*\d{1,2}\s*周(?:\s*周[一二三四五六日天])?",
        r"(?:本周|这周|下周|本月|这个月|下个月|今天|明天|后天)(?:(?:周|星期|礼拜)?[一二三四五六日天])?",
        r"(?:周[一二三四五六日天]|星期[一二三四五六日天])(?:上午|中午|下午|晚上)?",
        r"(?:上午|中午|下午|晚上|今晚|凌晨)",
        r"\d{1,2}[:\uff1a]\d{2}",
    ]
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return cleaned
