"""基于 LangChain 工具调用的校园活动 Agent。

Agent 对外暴露确定性的校园工具，并通过 ToolCallLimitMiddleware
限制每次对话最多调用 10 次工具。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .agent_tools import build_campus_tools
from .config import (
    CONVERSATION_DIR,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_ENABLED,
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

AGENT_SYSTEM_PROMPT = (
    "\u4f60\u662f\u6821\u56ed\u6d3b\u52a8\u4e0e\u901a\u77e5\u805a\u5408 Agent\u3002"
    "\u4f60\u53ef\u4ee5\u4f7f\u7528\u5de5\u5177\u67e5\u8be2\u6d3b\u52a8\u3001\u521b\u5efa\u63d0\u9192\u3001"
    "\u8bbe\u7f6e\u5174\u8da3\u6807\u7b7e\u3001\u6293\u53d6\u66f4\u65b0\u3001\u67e5\u770b\u5f85\u5ba1\u6838"
    "\u8bb0\u5f55\u548c\u83b7\u53d6\u7edf\u8ba1\u3002"
    "\u5fc5\u987b\u4f9d\u636e\u5de5\u5177\u8fd4\u56de\u7684\u771f\u5b9e\u6570\u636e\u56de\u7b54\uff0c"
    "\u4e0d\u8981\u7f16\u9020\u6d3b\u52a8\u3001\u65f6\u95f4\u3001\u5730\u70b9\u6216\u6765\u6e90\u3002"
    "\u5982\u679c\u5de5\u5177\u6ca1\u6709\u8fd4\u56de\u7ed3\u679c\uff0c\u8bf7\u660e\u786e\u8bf4\u660e\u3002"
    "\u6bcf\u4e2a\u7528\u6237\u8bf7\u6c42\u6700\u591a\u8c03\u7528 10 \u6b21\u5de5\u5177\uff0c"
    "\u5c3d\u91cf\u5728\u5c11\u6570\u6b21\u8c03\u7528\u5185\u5b8c\u6210\u4efb\u52a1\u3002"
)


# 校园 Agent 主类：组装工具、LLM 和中间件，处理对话与降级回复。
class LangChainAgent:
    """Campus agent built with create_agent and a 10-call run limit."""

    # 初始化时构建工具；LLM 禁用时只保留本地回复能力。
    def __init__(
        self,
        store: EventStore,
        reminders: ReminderStore,
        matcher: InterestMatcher,
        scraper: EventScraper,
        middleware: Middleware,
        *,
        enabled: bool | None = None,
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
        self.enabled = LLM_ENABLED if enabled is None else enabled

        self.tools = build_campus_tools(
            store=store,
            reminders=reminders,
            matcher=matcher,
            scraper=scraper,
            middleware=middleware,
        )
        if self.enabled:
            self.model = ChatOpenAI(
                base_url=self.base_url,
                api_key=self.api_key or "not-needed",
                model=self.model_name,
                temperature=0.1,
                timeout=timeout,
                max_retries=0,
            )
            self.agent = create_agent(
                model=self.model,
                tools=self.tools,
                system_prompt=f"{AGENT_SYSTEM_PROMPT}\n\u5f53\u524d\u65e5\u671f\uff1a{datetime.now():%Y-%m-%d}\u3002",
                middleware=[
                    ToolCallLimitMiddleware(
                        run_limit=self.max_tool_calls,
                        exit_behavior="continue",
                    )
                ],
            )
        else:
            self.model = None
            self.agent = None

    # 对话入口：记录历史、调用 Agent 或本地回复，并附带提醒/推送。
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
                "\u8bf7\u8f93\u5165\u6d88\u606f\u540e\u53d1\u9001\u3002",
                history=history,
                session_id=session_id,
                llm_used=False,
                tool_calls=0,
            )

        self._append_history(session_id, "user", message)
        reply, llm_used, tool_calls = self._invoke(message, history)
        self._append_history(session_id, "assistant", reply)

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})
        return self._response(
            reply,
            history=history,
            session_id=session_id,
            llm_used=llm_used,
            tool_calls=tool_calls,
        )

    # 返回当前 Agent 的模型、开关和工具限制状态。
    def to_status(self) -> dict[str, Any]:
        return {
            "enabled": self.agent is not None,
            "framework": "langchain-agent",
            "base_url": self.base_url,
            "model": self.model_name,
            "has_api_key": bool(self.api_key),
            "max_tool_calls": self.max_tool_calls,
        }

    # 调用 LangChain Agent；失败时降级到本地回复，保持聊天可用。
    def _invoke(self, message: str, history: list[dict[str, str]]) -> tuple[str, bool, int]:
        if self.agent is None:
            local_reply = self._local_reminder_reply(message)
            if local_reply is not None:
                return local_reply, False, 1
            return self._fallback_reply(message), False, 0

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
            return reply, True, tool_calls
        except Exception as exc:  # noqa: BLE001 - keep chat usable on agent errors
            duration_ms = (time.perf_counter() - started) * 1000
            logger.warning("LangChain agent failed: %s", exc)
            self.middleware.record("agent.error", str(exc), duration_ms)
            local_reply = self._local_reminder_reply(message)
            if local_reply is not None:
                return local_reply, False, 1
            return self._fallback_reply(message), False, 0

    # 从结果消息中取最后一条非空 AIMessage 作为最终回复。
    @staticmethod
    def _extract_reply(result: Any) -> str:
        messages = result.get("messages", []) if isinstance(result, dict) else []
        for message in reversed(messages):
            if isinstance(message, AIMessage) and message.content:
                return str(message.content).strip()
        if messages:
            return str(getattr(messages[-1], "content", "") or "").strip() or "Agent \u6ca1\u6709\u8fd4\u56de\u5185\u5bb9\u3002"
        return "Agent \u6ca1\u6709\u8fd4\u56de\u5185\u5bb9\u3002"

    # 统计一次 Agent 运行中的工具调用次数。
    @staticmethod
    def _count_tool_calls(result: Any) -> int:
        messages = result.get("messages", []) if isinstance(result, dict) else []
        count = 0
        for message in messages:
            if isinstance(message, AIMessage):
                count += len(getattr(message, "tool_calls", None) or [])
        return count

    # 离线模式也能识别“提醒我参加XX”并直接创建提醒。
    def _local_reminder_reply(self, message: str) -> str | None:
        if "提醒我" not in message:
            return None
        name = re.sub(r"^\s*提醒我\s*(?:参加|报名)?\s*", "", message)
        name = re.sub(r"[\s，。！？,.!?]*(?:可以吗|好吗|吧|谢谢)?\s*$", "", name).strip()
        if not name or name == message:
            return None
        tool = next(
            (item for item in self.tools if getattr(item, "name", "") == "create_reminder"),
            None,
        )
        if tool is None:
            return None
        return tool.invoke({"event_name": name, "note": message})

    # LLM 不可用时的简单本地回复。
    def _fallback_reply(self, message: str) -> str:
        if any(token in message for token in ("\u4f60\u597d", "\u60a8\u597d", "hi", "hello")):
            return "\u4f60\u597d\uff01\u5f53\u524d Agent \u6a21\u578b\u4e0d\u53ef\u7528\uff0c\u6682\u65f6\u8fd4\u56de\u672c\u5730\u56de\u590d\u3002"
        if any(token in message for token in ("\u6d3b\u52a8", "\u8bb2\u5ea7", "\u7ade\u8d5b", "\u901a\u77e5")):
            return "\u5f53\u524d\u65e0\u6cd5\u8c03\u7528\u6d3b\u52a8\u5de5\u5177\uff0c\u4f60\u53ef\u4ee5\u5728\u5de6\u4fa7\u6309\u5173\u952e\u8bcd\u3001\u7c7b\u522b\u548c\u65f6\u95f4\u7b5b\u9009\u3002"
        return "\u5df2\u6536\u5230\u6d88\u606f\u3002\u5f53\u524d Agent \u6a21\u578b\u4e0d\u53ef\u7528\uff0c\u8bf7\u68c0\u67e5 LLM \u914d\u7f6e\u3002"

    # 组装统一的 API 响应，包含历史、统计、到期提醒和兴趣推送。
    def _response(
        self,
        reply: str,
        history: list[dict[str, str]],
        session_id: str,
        llm_used: bool,
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
            "llm_used": llm_used,
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
