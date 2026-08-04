"""校网抓取、去重和人工审核流程的单元测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from src.config import DATA_DIR
from src.event_store import EventStore
from src.scraper import EventScraper


# 使用临时目录隔离事件库、待审核文件和抓取日志。
class ScraperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = EventStore(root / "events.json")
        self.store.events = list(EventStore(DATA_DIR / "events.json").events)
        self.store.save()
        feed_data = json.loads((DATA_DIR / "feed_candidates.json").read_text(encoding="utf-8"))
        for item in feed_data.get("events", []):
            item["id"] = item.get("id", "").replace("FEED-", "TEST-FEED-")
        feed_file = root / "feed_candidates.json"
        feed_file.write_text(json.dumps(feed_data, ensure_ascii=False), encoding="utf-8")
        self.scraper = EventScraper(
            store=self.store,
            feed_file=feed_file,
            pending_file=root / "pending.json",
            log_file=root / "scrape_log.jsonl",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_adds_and_rejects_bad_record(self):
        result = self.scraper.run()
        self.assertEqual(result.added, 2)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.pending, 1)
        self.assertEqual(len(self.scraper.pending()), 1)

    def test_manual_review(self):
        self.scraper.run()
        item = self.scraper.review("TEST-FEED-103", approved=False)
        self.assertIsNotNone(item)
        self.assertEqual(item["status"], "rejected")

    def test_deduplication(self):
        self.scraper.run()
        self.assertEqual(len(self.scraper.pending()), 1)
        second = self.scraper.run()
        self.assertEqual(second.added, 0)
        self.assertEqual(second.pending, 0)
        self.assertEqual(len(self.scraper.pending()), 1)


if __name__ == "__main__":
    unittest.main()
