"""LangChain Agent、工具构建和离线降级测试。"""

import tempfile
import unittest
from pathlib import Path

from langchain.agents.middleware import ToolCallLimitMiddleware

from src.agent import LangChainAgent
from src.agent_tools import build_campus_tools
from src.config import DATA_DIR
from src.event_store import EventStore
from src.interest_matcher import InterestMatcher
from src.middleware import Middleware
from src.reminder_store import ReminderStore
from src.scraper import EventScraper


# 在临时目录中运行 Agent，避免污染真实提醒和会话数据。
class LangChainAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = EventStore(DATA_DIR / "events.json")
        self.reminders = ReminderStore(root / "reminders.json")
        self.matcher = InterestMatcher(root / "preferences.json", root / "notifications.json")
        self.middleware = Middleware(root / "usage.json")
        self.scraper = EventScraper(
            store=self.store,
            feed_file=DATA_DIR / "feed_candidates.json",
            pending_file=root / "pending.json",
            log_file=root / "scrape_log.jsonl",
        )
        self.tools = build_campus_tools(
            store=self.store,
            reminders=self.reminders,
            matcher=self.matcher,
            scraper=self.scraper,
            middleware=self.middleware,
        )
        self.agent = LangChainAgent(
            store=self.store,
            reminders=self.reminders,
            matcher=self.matcher,
            scraper=self.scraper,
            middleware=self.middleware,
            enabled=False,
            conversation_dir=root / "conversations",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_input(self):
        result = self.agent.chat("", session_id="test-empty")
        self.assertIn("\u8bf7\u8f93\u5165", result["reply"])

    def test_offline_fallback(self):
        result = self.agent.chat("hello", session_id="test-offline")
        self.assertFalse(result["llm_used"])
        self.assertIn("\u6a21\u578b\u4e0d\u53ef\u7528", result["reply"])

    def test_history_and_persistence(self):
        first = self.agent.chat("hi", session_id="test-history")
        second = self.agent.chat("again", session_id="test-history", history=first["history"])
        self.assertEqual(len(second["history"]), 4)
        self.assertTrue((Path(self.tmp.name) / "conversations" / "test-history.json").exists())

    def test_builds_campus_tools(self):
        names = [tool.name for tool in self.tools]
        self.assertEqual(
            names,
            [
                "search_events",
                "create_reminder",
                "set_preferences",
                "refresh_events",
                "list_pending_reviews",
                "review_pending",
                "get_stats",
                "add_event",
                "update_event",
            ],
        )

    def test_search_tool(self):
        result = self.tools[0].invoke({"query": "11.15 \u7684\u6d3b\u52a8"})
        self.assertIn("\u6821\u56ed\u5fd7\u613f\u670d\u52a1\u5f00\u653e\u65e5", result)

    def test_create_reminder_tool(self):
        result = self.tools[1].invoke({"event_name": "ACM \u7a0b\u5e8f\u8bbe\u8ba1\u7ade\u8d5b\u5ba3\u8bb2\u4f1a"})
        self.assertIn("\u5df2\u521b\u5efa\u63d0\u9192", result)
        self.assertEqual(len(self.reminders.reminders), 1)

    def test_offline_reminder_phrase(self):
        result = self.agent.chat(
            "\u63d0\u9192\u6211\u53c2\u52a0 ACM \u7a0b\u5e8f\u8bbe\u8ba1\u7ade\u8d5b\u5ba3\u8bb2\u4f1a",
            session_id="test-offline-reminder",
        )
        self.assertIn("\u5df2\u521b\u5efa\u63d0\u9192", result["reply"])
        self.assertEqual(len(self.reminders.reminders), 1)

    def test_default_tool_limit_is_ten(self):
        online = LangChainAgent(
            store=self.store,
            reminders=self.reminders,
            matcher=self.matcher,
            scraper=self.scraper,
            middleware=self.middleware,
            enabled=True,
            max_tool_calls=10,
        )
        limiter = ToolCallLimitMiddleware(run_limit=10, exit_behavior="continue")
        self.assertEqual(limiter.run_limit, 10)
        self.assertEqual(online.max_tool_calls, 10)
        self.assertEqual(online.to_status()["max_tool_calls"], 10)
        self.assertEqual(online.to_status()["framework"], "langchain-agent")


if __name__ == "__main__":
    unittest.main()
