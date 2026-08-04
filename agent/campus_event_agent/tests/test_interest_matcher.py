"""兴趣标签匹配与推送通知的单元测试。"""

import tempfile
import unittest
from pathlib import Path

from src.interest_matcher import InterestAgent, InterestMatcher
from src.models import Event


# 验证任一标签命中、去重、用户过滤和重载。
class InterestMatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.matcher = InterestMatcher(root / "preferences.json", root / "notifications.json")
        self.event = Event(
            id="EVT-TEST",
            name="AI 前沿讲座",
            category="讲座",
            raw_time="第3周周三 14:30",
            time="2026-09-16T14:30:00",
            location="图书馆报告厅",
            source="测试源",
            tags=["AI", "讲座"],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_match_and_push(self):
        self.matcher.set_preferences(["讲座"])
        notification = self.matcher.evaluate_event(self.event)
        self.assertIsNotNone(notification)
        self.assertEqual(notification["event_id"], "EVT-TEST")

    def test_no_duplicate_push(self):
        self.matcher.set_preferences(["讲座"])
        self.matcher.evaluate_event(self.event)
        self.assertIsNone(self.matcher.evaluate_event(self.event))

    def test_any_one_match_is_enough(self):
        self.matcher.set_preferences(["\u7ade\u8d5b", "\u8bb2\u5ea7"])
        notification = self.matcher.evaluate_event(self.event)
        self.assertIsNotNone(notification)
        self.assertEqual(notification["matched_tags"], ["\u8bb2\u5ea7"])

    def test_no_match_no_push(self):
        self.matcher.set_preferences(["\u7ade\u8d5b"])
        self.assertIsNone(self.matcher.evaluate_event(self.event))


    def test_category_match_records_matched_tag(self):
        category_event = Event(
            id="EVT-CATEGORY",
            name="AI Meetup",
            category="\u8bb2\u5ea7",
            raw_time="2026-09-16 14:30",
            time="2026-09-16T14:30:00",
            location="Test Hall",
            source="Test",
            tags=[],
        )
        self.matcher.set_preferences(["\u8bb2\u5ea7"])
        notification = self.matcher.evaluate_event(category_event)
        self.assertIsNotNone(notification)
        self.assertEqual(notification["matched_tags"], ["\u8bb2\u5ea7"])

    def test_notifications_for_filters_user(self):
        self.matcher.set_preferences(["\u8bb2\u5ea7"], user="alice")
        self.matcher.evaluate_event(self.event)
        self.assertEqual(len(self.matcher.notifications_for("alice")), 1)
        self.assertEqual(self.matcher.notifications_for("default"), [])

    def test_reload_reads_external_preferences(self):
        other = InterestMatcher(self.matcher.preferences_path, self.matcher.notifications_path)
        other.set_preferences(["\u7ade\u8d5b"])
        self.matcher.reload()
        self.assertEqual(self.matcher.preferences.tags, ["\u7ade\u8d5b"])

    def test_interest_agent_batch_push(self):
        self.matcher.set_preferences(["\u8bb2\u5ea7"])
        agent = InterestAgent(self.matcher)
        pushed = agent.evaluate_new_events([self.event])
        self.assertEqual(len(pushed), 1)
        self.assertEqual(pushed[0]["event_name"], self.event.name)

    def test_status_reports_any_tag_rule(self):
        self.matcher.set_preferences(["\u8bb2\u5ea7"])
        status = InterestAgent(self.matcher).status()
        self.assertEqual(status["rule"], "any")
        self.assertNotIn("threshold", status)


    def test_remove_by_event(self):
        self.matcher.set_preferences(["讲座"])
        self.matcher.evaluate_event(self.event)
        self.assertEqual(len(self.matcher.notifications_for()), 1)

        removed = self.matcher.remove_by_event("EVT-TEST")

        self.assertEqual(removed, 1)
        self.assertEqual(self.matcher.notifications_for(), [])
        self.assertEqual(self.matcher.remove_by_event("EVT-TEST"), 0)


if __name__ == "__main__":
    unittest.main()

