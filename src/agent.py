"""基于 deepagents 多智能体（主 Agent + 子 Agent）的校园活动 Agent。

主 Agent 通过 task 工具把任务分派给活动查询、提醒、兴趣偏好、抓取与审核、
活动管理 5 个子 Agent；每个子 Agent 只持有自己的确定性工具。
通过 ToolCallLimitMiddleware 限制每次对话最多调用 10 次工具。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from deepagents import SubAgent, create_deep_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .agent_tools import _current_session, _pending_actions, build_campus_tools
from .config import (
    CONVERSATION_DIR,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_TIMEOUT,
    MAX_TOOL_CALLS,
)
from .event_store import EventStore
from .interest_matcher import InterestMatcher
from .middleware import Middleware
from .reminder_store import ReminderStore
from .scraper import EventScraper

logger = logging.getLogger(__name__)

# 主 Agent 系统提示：负责按用户意图把任务分派给子 Agent。
MAIN_SYSTEM_PROMPT = (
    "你是校园活动与通知聚合主 Agent。"
    "你可以使用 task 工具把任务分派给下面的子 Agent：活动查询、提醒、兴趣偏好、抓取与审核、活动管理。"
    "根据用户意图选择合适的子 Agent，由子 Agent 调用工具获取真实数据后再汇总回答；"
    "不要编造活动、时间、地点或来源，工具没有返回结果就明确说明。"
    "不要使用文件系统工具（ls/read_file/write_file/edit_file/glob/grep）和 execute 工具。"
    "请直接以纯文本回复，不要使用 Markdown 格式（不用加粗、不用标题、不用列表符号、不用代码块）。"
)

# 子 Agent 的 system_prompt：只需要返回结果即可，不需要额外的内容。
SUBAGENT_PROMPTS = {
    "event_query_agent": (
        "你是一个校园活动查询助手。"
        "通过 search_events 工具检索活动（支持把“11.15 的活动”这类时间表达直接作为 query 传入），"
        "通过 get_stats 工具获取活动总数、分类和调用统计。"
        "必须依据工具返回的真实数据回答，找不到就明确说明，不要编造。"
        "只需要返回结果即可，不需要额外的内容。"
    ),
    "reminder_agent": (
        "你是一个提醒助手。"
        "通过 create_reminder 工具按活动名称或 ID 创建到点提醒；活动不存在时明确告知。"
        "只需要返回结果即可，不需要额外的内容。"
    ),
    "preference_agent": (
        "你是一个兴趣偏好助手。"
        "通过 set_preferences 工具设置兴趣标签，命中任一标签的新活动会自动推送。"
        "只需要返回结果即可，不需要额外的内容。"
    ),
    "scrape_agent": (
        "你是一个抓取与审核助手。"
        "通过 refresh_events 抓取校园活动更新，通过 list_pending_reviews 查看待审核记录，"
        "通过 review_pending 批准或拒绝某条待审核记录。"
        "必须依据工具返回的真实数据回答。只需要返回结果即可，不需要额外的内容。"
    ),
    "event_manage_agent": (
        "你是一个活动管理助手。"
        "通过 add_event 新增活动（名称、时间、地点必填），通过 update_event 按 ID 修正已有活动字段。"
        "必须依据工具返回的真实结果回答。只需要返回结果即可，不需要额外的内容。"
    ),
}


# Markdown 清洗器：去掉常见 Markdown 语法，保留纯文本。
_MD_CODE_FENCE = re.compile(r"```+.*?\n(.*?)\n?```+", re.DOTALL)
_MD_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_REF = re.compile(r"\[\^?\d+\]")
_MD_HEADER = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_BLOCKQUOTE = re.compile(r"^>\s?", re.MULTILINE)
_MD_HR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", re.MULTILINE)
_MD_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_MD_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$", re.MULTILINE)
_MD_EMPH = re.compile(r"(\*\*|__|~~)(.+?)\1|(\*|_)(.+?)\3")
_MD_TAG = re.compile(r"<[^>]+>")


def md_to_text(text: str) -> str:
    """去掉常见 Markdown 语法，返回纯文本。"""
    if not text:
        return text
    t = _MD_CODE_FENCE.sub(lambda m: m.group(1).strip(), text)
    t = _MD_INLINE_CODE.sub(r"\1", t)
    t = _MD_IMAGE.sub(r"\1", t)
    t = _MD_LINK.sub(r"\1", t)
    t = _MD_REF.sub("", t)
    t = _MD_HEADER.sub("", t)
    t = _MD_BLOCKQUOTE.sub("", t)
    t = _MD_HR.sub("", t)
    t = _MD_TABLE_SEP.sub("", t)
    t = _MD_LIST.sub("", t)
    for _ in range(4):
        new = _MD_EMPH.sub(lambda m: m.group(2) or m.group(4), t)
        if new == t:
            break
        t = new
    t = _MD_TAG.sub("", t)
    lines = []
    for line in t.splitlines():
        if "|" in line:
            cells = [c.strip() for c in line.split("|")]
            line = " ".join(c for c in cells if c)
        lines.append(line.rstrip())
    t = "\n".join(lines)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# 待确认写操作下，用户答复的确认/取消判定。
_CONFIRM_EXACT = {
    "确认", "确定", "是", "好", "行", "可以", "执行", "ok", "yes", "y",
    "对", "好的", "嗯", "嗯嗯", "要", "要的",
}
_CANCEL_EXACT = {
    "取消", "否", "不", "算了", "不要", "不用", "no", "cancel", "n",
    "不要了", "不用了",
}


def _pending_decision(text: str) -> str | None:
    """判断用户在待确认状态下给出的答复：返回 'confirm'/'cancel'/None。

    只有明确匹配确认或取消时才作数，避免把普通问题误判成确认。
    """
    t = (text or "").strip().lower()
    if t in _CONFIRM_EXACT:
        return "confirm"
    if t in _CANCEL_EXACT:
        return "cancel"
    if any(word in t for word in ("确认", "确定", "执行")):
        return "confirm"
    if any(word in t for word in ("取消", "算了")):
        return "cancel"
    return None


# 校园多智能体主类：组装工具、子 Agent 和中间件，处理对话与任务分派。
class CampusAgent:
    """基于 create_deep_agent（主 Agent + 5 个子 Agent）构建、带 10 次工具调用上限的校园 Agent。"""

    # 初始化时构建工具，并把工具按职责分派给子 Agent（LLM 为必选项）。
    def __init__(
        self,
        store: EventStore,
        reminders: ReminderStore,
        matcher: InterestMatcher,
        scraper: EventScraper,
        middleware: Middleware,
        *,
        max_tool_calls: int = MAX_TOOL_CALLS,
        conversation_dir: Path | None = None,
        base_url: str = LLM_BASE_URL,
        api_key: str = LLM_API_KEY,
        model_name: str = LLM_MODEL,
        timeout: int = LLM_TIMEOUT,
    ) -> None:
        self.store = store
        self.reminders = reminders
        self.matcher = matcher
        self.scraper = scraper
        self.middleware = middleware
        self.max_tool_calls = max(1, int(max_tool_calls))
        self.conversation_dir = conversation_dir or CONVERSATION_DIR
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1"):
            self.base_url = f"{self.base_url}/v1"
        self.api_key = api_key or ""
        self.model_name = model_name

        self.model = ChatOpenAI(
            base_url=self.base_url,
            api_key=self.api_key or "not-needed",
            model=self.model_name,
            temperature=0.1,
            timeout=timeout,
            max_retries=3,
        )
        self.tools = build_campus_tools(
            store=store,
            reminders=reminders,
            matcher=matcher,
            scraper=scraper,
            middleware=middleware,
        )
        self.subagents = self._build_subagents()
        self.agent = create_deep_agent(
            model=self.model,
            system_prompt=f"{MAIN_SYSTEM_PROMPT}\n当前日期：{datetime.now():%Y-%m-%d}。",
            subagents=self.subagents,
            middleware=[
                ToolCallLimitMiddleware(
                    run_limit=self.max_tool_calls,
                    exit_behavior="continue",
                )
            ],
        )

    # 按职责把全部 9 个工具分派给 5 个子 Agent，保证功能一个不少。
    def _build_subagents(self) -> list[SubAgent]:
        tools = {tool.name: tool for tool in self.tools}
        specs = [
            {
                "name": "event_query_agent",
                "description": (
                    "用于检索校园活动、查看活动统计。"
                    "当用户查询讲座、竞赛、社团、教务通知、文体活动、志愿服务等校园活动，"
                    "或询问活动总数、分类、调用统计时，调用该子 Agent。"
                ),
                "tool_names": ["search_events", "get_stats"],
            },
            {
                "name": "reminder_agent",
                "description": (
                    "用于为校园活动创建到点提醒。"
                    "当用户说“提醒我参加 XX”或要求为某个活动设置提醒时，调用该子 Agent。"
                ),
                "tool_names": ["create_reminder"],
            },
            {
                "name": "preference_agent",
                "description": (
                    "用于设置用户兴趣标签。"
                    "当用户说“我关注讲座和竞赛”“帮我设置偏好”等要求更新兴趣标签时，调用该子 Agent。"
                ),
                "tool_names": ["set_preferences"],
            },
            {
                "name": "scrape_agent",
                "description": (
                    "用于抓取校园活动更新、查看待人工审核记录、批准或拒绝审核。"
                    "当用户要求刷新/抓取活动，或查看/处理待审核记录时，调用该子 Agent。"
                ),
                "tool_names": ["refresh_events", "list_pending_reviews", "review_pending"],
            },
            {
                "name": "event_manage_agent",
                "description": (
                    "用于手动新增或修改校园活动记录。"
                    "当用户要求添加一个新活动，或修正已有活动的时间、地点等字段时，调用该子 Agent。"
                ),
                "tool_names": ["add_event", "update_event"],
            },
        ]
        subagents: list[SubAgent] = []
        for spec in specs:
            tool_names = spec["tool_names"]
            missing = [name for name in tool_names if name not in tools]
            if missing:
                raise ValueError(f"子 Agent {spec['name']} 缺少工具: {missing}")
            subagents.append(
                SubAgent(
                    name=spec["name"],
                    description=spec["description"],
                    system_prompt=SUBAGENT_PROMPTS[spec["name"]],
                    model=self.model,
                    tools=[tools[name] for name in tool_names],
                )
            )
        return subagents

    # 对话入口：记录历史、调用主 Agent（内部再分派子 Agent），并附带提醒/推送。
    def chat(
        self,
        message: str,
        session_id: str = "default",
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        message = (message or "").strip()
        history = [dict(item) for item in (history or [])][-20:]

        if not message:
            return self._response(
                "请输入查询内容后发送。",
                history=history,
                session_id=session_id,
                tool_calls=0,
            )

        # 处理上一条待确认的写操作：确认/取消走快捷通道，其余视为放弃。
        pending_key = next(
            (key for key in _pending_actions if key.startswith(f"{session_id}:")),
            None,
        )
        if pending_key is not None:
            decision = _pending_decision(message)
            if decision is not None:
                action = _pending_actions.pop(pending_key)
                reply = action["execute"]() if decision == "confirm" else "已取消。"
                self._append_history(session_id, "user", message)
                self._append_history(session_id, "assistant", reply)
                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": reply})
                return self._response(
                    reply,
                    history=history,
                    session_id=session_id,
                    tool_calls=0,
                )
            # 用户发了别的内容：放弃待确认操作，继续正常对话。
            _pending_actions.pop(pending_key, None)

        self._append_history(session_id, "user", message)
        # 会话上下文只覆盖本次调用，结束后恢复，避免污染同线程后续直调工具。
        token = _current_session.set(session_id)
        try:
            reply, tool_calls = self._invoke(message, history)
        finally:
            _current_session.reset(token)
        self._append_history(session_id, "assistant", reply)

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        return self._response(
            reply,
            history=history,
            session_id=session_id,
            tool_calls=tool_calls,
        )

    # 返回当前 Agent 的模型、子 Agent 列表和工具限制状态。
    def to_status(self) -> dict[str, Any]:
        return {
            "framework": "deep-agent",
            "base_url": self.base_url,
            "model": self.model_name,
            "has_api_key": bool(self.api_key),
            "max_tool_calls": self.max_tool_calls,
            "subagents": [subagent["name"] for subagent in self.subagents],
        }

    # 调用 Deep Agent（主 Agent 通过 task 分派子 Agent）；失败时返回错误提示。
    def _invoke(self, message: str, history: list[dict[str, str]]) -> tuple[str, int]:
        started = time.perf_counter()
        try:
            history_messages = self._to_langchain_messages(history)
            result = self.agent.invoke(
                {"messages": [*history_messages, HumanMessage(content=message)]}
            )
            duration_ms = (time.perf_counter() - started) * 1000
            reply = self._extract_reply(result)
            tool_calls = self._count_tool_calls(result)
            self.middleware.record(
                "agent.run",
                message,
                duration_ms,
                tool_calls,
            )
            return reply, tool_calls
        except Exception as exc:  # noqa: BLE001 - LLM 不可用时返回可读错误
            duration_ms = (time.perf_counter() - started) * 1000
            logger.warning("Deep Agent 调用失败: %s", exc)
            self.middleware.record("agent.error", str(exc), duration_ms)
            return f"LLM 调用失败：{exc}。请检查 LLM 配置后重试。", 0

    # 从结果消息中取最后一条非空 AIMessage 作为最终回复。
    @staticmethod
    def _extract_reply(result: Any) -> str:
        messages = result.get("messages", []) if isinstance(result, dict) else []
        for message in reversed(messages):
            if isinstance(message, AIMessage) and message.content:
                return md_to_text(str(message.content)).strip()
        if messages:
            content = str(getattr(messages[-1], "content", "") or "").strip()
            return md_to_text(content) or "Agent 没有返回内容。"
        return "Agent 没有返回内容。"

    # 统计一次 Agent 运行中的工具调用次数。
    @staticmethod
    def _count_tool_calls(result: Any) -> int:
        messages = result.get("messages", []) if isinstance(result, dict) else []
        count = 0
        for message in messages:
            if isinstance(message, AIMessage):
                count += len(getattr(message, "tool_calls", None) or [])
        return count

    # 组装统一的 API 响应，包含历史、统计、到期提醒和兴趣推送。
    def _response(
        self,
        reply: str,
        history: list[dict[str, str]],
        session_id: str,
        tool_calls: int,
    ) -> dict[str, Any]:
        due_reminders = []
        if self.reminders:
            due_reminders = [item.to_dict() for item in self.reminders.check_due()]
        notifications = self.matcher.notifications_for() if self.matcher else []
        return {
            "reply": reply,
            "intent": "agent",
            "data": [],
            "actions": [],
            "tool_calls": tool_calls,
            "max_tool_calls": self.max_tool_calls,
            "history": history,
            "stats": self.middleware.stats(),
            "due_reminders": due_reminders,
            "notifications": notifications,
            "llm_status": self.to_status(),
        }

    # 把前端历史字典转换成 LangChain 消息对象。
    @staticmethod
    def _to_langchain_messages(history: list[dict[str, str]]) -> list:
        messages = []
        for item in history:
            role = str(item.get("role", "user"))
            content = str(item.get("content", ""))
            if role == "system":
                messages.append(SystemMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            else:
                messages.append(HumanMessage(content=content))
        return messages

    # 根据会话 ID 生成安全文件名，避免路径注入。
    def _conversation_path(self, session_id: str) -> Path:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80] or "default"
        return self.conversation_dir / f"{safe_name}.json"

    # 读取会话历史；文件损坏时返回空历史。
    def _load_conversation(self, session_id: str) -> list[dict[str, str]]:
        path = self._conversation_path(session_id)
        if not path.exists():
            return []
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
            return [dict(item) for item in items if isinstance(item, dict)]
        except (json.JSONDecodeError, OSError):
            return []

    # 追加一条历史并只保留最近 100 条，控制文件体积。
    def _append_history(self, session_id: str, role: str, content: str) -> None:
        self.conversation_dir.mkdir(parents=True, exist_ok=True)
        items = self._load_conversation(session_id)
        items.append(
            {
                "role": role,
                "content": content,
                "time": datetime.now().isoformat(timespec="seconds"),
            }
        )
        self._conversation_path(session_id).write_text(
            json.dumps(items[-100:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
