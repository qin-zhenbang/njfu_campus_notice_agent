"""基于标准库实现的轻量 HTTP 服务和 JSON API。"""

from __future__ import annotations

import json
import mimetypes
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .agent import LangChainAgent
from .config import AUTO_FETCH_ENABLED, AUTO_FETCH_INTERVAL, AUTO_REMINDER_ENABLED, AUTO_REMINDER_INTERVAL, HOST, PORT, STATIC_DIR
from .event_store import EventStore
from .interest_matcher import InterestAgent, InterestMatcher
from .middleware import Middleware
from .reminder_store import ReminderStore
from .scheduler import FeedScheduler, ReminderScheduler
from .scraper import EventScraper


# 集中创建活动、提醒、偏好、抓取、Agent 和调度器等应用依赖。
class AppContext:
    def __init__(self) -> None:
        self.store = EventStore()
        self.reminders = ReminderStore()
        self.matcher = InterestMatcher()
        self.middleware = Middleware()
        self.interest_agent = InterestAgent(self.matcher, self.middleware)
        self.scraper = EventScraper(store=self.store)
        self.agent = LangChainAgent(
            store=self.store,
            reminders=self.reminders,
            matcher=self.matcher,
            scraper=self.scraper,
            middleware=self.middleware,
        )
        self.reminder_scheduler = ReminderScheduler(self.reminders, AUTO_REMINDER_INTERVAL)
        self.feed_scheduler = FeedScheduler(self.scraper, self.store, self.matcher, AUTO_FETCH_INTERVAL)


# HTTP 处理器：把 /api 请求路由到 JSON API，其他路径返回静态资源。
class AgentHandler(BaseHTTPRequestHandler):
    app: AppContext | None = None

    # 处理 GET：API 走 JSON，其余走静态文件。
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/"):
                self._handle_api_get(path, parse_qs(parsed.query))
            else:
                self._serve_static(path)
        except Exception as exc:  # noqa: BLE001 - keep UI from seeing tracebacks
            self._send_json({"error": f"服务内部错误: {exc}"}, status=500)

    # 处理 POST：聊天、抓取、偏好、提醒和审核等写操作。
    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            self._handle_api_post(path)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": f"服务内部错误: {exc}"}, status=500)

    def log_message(self, fmt: str, *args) -> None:
        return

    # 查询类接口：活动、类别、统计、提醒、待审核、通知和状态。
    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/events":
            q = self._first(query, "q", "")
            category = self._first(query, "category", "")
            start = self._first(query, "from", "")
            end = self._first(query, "to", "")
            events = self.app.store.search(query=q, category=category, start=start, end=end)
            self._send_json({"events": self.app.store.to_display_list(events)})
            return
        if path == "/api/categories":
            self._send_json({"categories": self.app.store.categories()})
            return
        if path == "/api/stats":
            categories = self.app.store.categories()
            self._send_json(
                {
                    "total": len(self.app.store.events),
                    "categories": categories,
                    "by_category": {
                        category: sum(1 for event in self.app.store.events if event.category == category)
                        for category in categories
                    },
                    "usage": self.app.middleware.stats(),
                    "llm": self.app.agent.to_status(),
                }
            )
            return
        if path == "/api/reminders":
            self.app.reminders.check_due()
            self._send_json({"reminders": [item.to_dict() for item in self.app.reminders.all()]})
            return
        if path == "/api/pending":
            self._send_json({"pending": self.app.scraper.pending()})
            return
        if path == "/api/notifications":
            self.app.matcher.reload()
            self._send_json({"notifications": self.app.matcher.notifications_for()})
            return
        if path == "/api/preferences":
            self.app.matcher.reload()
            self._send_json({"preferences": self.app.matcher.preferences.to_dict()})
            return
        if path == "/api/status":
            self._send_json(
                {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "event_count": len(self.app.store.events),
                    "llm": self.app.agent.to_status(),
                    "usage": self.app.middleware.stats(),
                    "auto_reminder": {
                        "enabled": self.app.reminder_scheduler.is_running(),
                        "interval": AUTO_REMINDER_INTERVAL,
                    },
                    "auto_fetch": {
                        "enabled": self.app.feed_scheduler.is_running(),
                        "interval": AUTO_FETCH_INTERVAL,
                    },
                    "interest_agent": self.app.interest_agent.status(),
                }
            )
            return
        self._send_json({"error": "接口不存在"}, status=404)

    # 写操作接口：统一读取 JSON body 后分发到具体业务。
    def _handle_api_post(self, path: str) -> None:
        body = self._read_json()
        if path == "/api/chat":
            message = str(body.get("message", ""))
            session_id = str(body.get("session_id", "default"))
            history = body.get("history") or []
            if not message:
                self._send_json({"error": "消息不能为空"}, status=400)
                return
            result = self.app.agent.chat(message, session_id=session_id, history=history)
            self._send_json(result)
            return
        if path == "/api/fetch":
            scrape_result = self.app.scraper.run()
            added = self.app.store.events[-scrape_result.added:] if scrape_result.added else []
            pushed = self.app.interest_agent.evaluate_new_events(added, source="fetch")
            self._send_json({"result": scrape_result.to_dict(), "pushed": pushed})
            return
        if path == "/api/preferences":
            tags = [str(tag) for tag in body.get("tags", [])]
            prefs = self.app.matcher.set_preferences(tags)
            self._send_json({"preferences": prefs.to_dict()})
            return
        if path == "/api/reminders":
            event_id = str(body.get("event_id", ""))
            event = self.app.store.get(event_id)
            if not event:
                self._send_json({"error": "活动不存在"}, status=404)
                return
            reminder = self.app.reminders.create(
                user=str(body.get("user", "default")),
                event_id=event.id,
                event_name=event.name,
                due_at=event.time,
                note=str(body.get("note", "")),
            )
            self._send_json({"reminder": reminder.to_dict()}, status=201)
            return
        if path == "/api/reminders/complete":
            reminder_id = str(body.get("id", ""))
            ok = self.app.reminders.complete(reminder_id)
            self._send_json({"ok": ok})
            return
        if path == "/api/reminders/cancel":
            reminder_id = str(body.get("id", ""))
            ok = self.app.reminders.cancel(reminder_id)
            self._send_json({"ok": ok})
            return
        if path == "/api/pending/review":
            pending_id = str(body.get("id", ""))
            approved = bool(body.get("approved", True))
            item = self.app.scraper.review(pending_id, approved)
            pushed = []
            if item is not None and item.get("status") == "approved":
                event = self.app.store.get(pending_id)
                if event is not None:
                    notification = self.app.interest_agent.evaluate_event(event, source="human-review")
                    if notification:
                        pushed.append(notification)
            self._send_json({"item": item, "ok": item is not None, "pushed": pushed})
            return
        if path == "/api/notifications/read":
            event_id = str(body.get("event_id", ""))
            self.app.matcher.mark_read(event_id)
            self._send_json({"ok": True})
            return
        # 手动新增活动：ID 可省略，成功后返回 201 并触发兴趣推送。
        if path == "/api/events":
            ok, result = self.app.store.create_event(body)
            if not ok:
                self._send_json({"error": result}, status=400)
                return
            event = result
            pushed = self.app.interest_agent.evaluate_event(event, source="manual-add")
            self._send_json({"event": event.to_dict(), "pushed": pushed}, status=201)
            return
        # 修改活动：按 ID 更新字段，找不到返回 404。
        if path == "/api/events/update":
            event_id = str(body.get("id", "")).strip()
            if not event_id:
                self._send_json({"error": "缺少活动 ID"}, status=400)
                return
            fields = {key: value for key, value in body.items() if key != "id"}
            ok, message = self.app.store.update_event(event_id, fields)
            if not ok:
                self._send_json({"error": message}, status=404 if message == "活动不存在" else 400)
                return
            self._send_json({"ok": True})
            return
        # 删除活动：级联取消相关提醒并移除兴趣通知，找不到返回 404。
        if path == "/api/events/delete":
            event_id = str(body.get("id", "")).strip()
            if not event_id:
                self._send_json({"error": "缺少活动 ID"}, status=400)
                return
            if self.app.store.get(event_id) is None:
                self._send_json({"error": "活动不存在"}, status=404)
                return
            cancelled = self.app.reminders.cancel_by_event(event_id)
            removed = self.app.matcher.remove_by_event(event_id)
            ok, _ = self.app.store.delete_event(event_id)
            self._send_json({"ok": ok, "cancelled_reminders": cancelled, "removed_notifications": removed})
            return
        self._send_json({"error": "接口不存在"}, status=404)

    # 服务前端静态文件，并防止路径穿越。
    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            path = "/index.html"
        relative = path.lstrip("/")
        file_path = (STATIC_DIR / relative).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())):
            self._send_json({"error": "禁止访问"}, status=403)
            return
        if not file_path.exists() or not file_path.is_file():
            self._send_json({"error": "页面不存在"}, status=404)
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # 按 Content-Length 读取并解析请求体。
    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)

    # 统一以 UTF-8 JSON 返回响应。
    def _send_json(self, payload: dict | list, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # 从查询参数中取第一个值，缺省返回默认值。
    @staticmethod
    def _first(query: dict[str, list[str]], key: str, default: str = "") -> str:
        values = query.get(key)
        return values[0] if values else default


# 创建服务上下文并启动 HTTP 服务器，按配置开启后台任务。
def create_server(host: str = HOST, port: int = PORT, auto_fetch: bool | None = None) -> ThreadingHTTPServer:
    context = AppContext()
    AgentHandler.app = context
    server = ThreadingHTTPServer((host, port), AgentHandler)
    server.app = context
    if AUTO_REMINDER_ENABLED:
        context.reminder_scheduler.start()
    enable_fetch = AUTO_FETCH_ENABLED if auto_fetch is None else auto_fetch
    if enable_fetch:
        context.feed_scheduler.start()
    return server

