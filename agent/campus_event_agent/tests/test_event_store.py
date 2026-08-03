"""活动数据仓库校验与三类查询的单元测试。"""

import unittest

from src.config import DATA_DIR
from src.event_store import EventStore


# 使用项目真实数据验证校验、关键词/类别/时间范围检索和展示字段。
class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = EventStore(DATA_DIR / "events.json")

    def test_data_validation(self):
        errors = EventStore(DATA_DIR / "events.json").validate()
        self.assertEqual(errors, [])

    def test_search_by_keyword(self):
        events = EventStore(DATA_DIR / "events.json").search(query="马拉松")
        self.assertTrue(events)
        self.assertTrue(all("马拉松" in event.name or "马拉松" in event.description for event in events))

    def test_filter_by_category(self):
        events = EventStore(DATA_DIR / "events.json").search(category="竞赛")
        self.assertTrue(events)
        self.assertTrue(all(event.category == "竞赛" for event in events))

    def test_filter_by_time_range(self):
        events = EventStore(DATA_DIR / "events.json").search(
            start="2026-10-01T00:00:00",
            end="2026-10-31T23:59:59",
        )
        self.assertTrue(events)
        self.assertTrue(all("2026-10-" in event.time for event in events))

    def test_display_fields(self):
        events = EventStore(DATA_DIR / "events.json").search(limit=1)
        display = events[0].display_dict()
        self.assertIn("standard_time", display)
        self.assertIn("duration", display)
        self.assertIn("location", display)
        self.assertIn("category", display)
        self.assertIn("source", display)

    def test_mixed_time_formats(self):
        events = EventStore(DATA_DIR / "events.json").events
        raw_times = " ".join(event.raw_time for event in events)
        self.assertIn("第", raw_times)
        self.assertIn("11.", raw_times)
        self.assertIn("下午", raw_times)


if __name__ == "__main__":
    unittest.main()
