"""南京林业大学校网活动解析器与抓取流程的测试。"""

import tempfile
import unittest
from pathlib import Path

from src.event_store import EventStore
from src.njfu_feed import SchoolFeedParseError, extract_school_items, parse_summary_fields
from src.scraper import EventScraper


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "njfu_xsdt_sample.html"


class NJFUFixtureTests(unittest.TestCase):
    def test_extract_first_page(self):
        items = extract_school_items(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["id"], "NJFU-9001")
        self.assertEqual(items[0]["category"], "\u8bb2\u5ea7")
        self.assertEqual(items[0]["raw_time"], "2026\u5e749\u670810\u65e514:00-15:00")
        self.assertEqual(items[0]["location"], "\u6559\u4e5d\u697c9E406")
        self.assertEqual(items[1]["category"], "\u7ade\u8d5b")

    def test_summary_fields(self):
        summary = (
            "\u3010\u62a5\u544a\u4eba\u3011\u5f20\u8001\u5e08<br>\n"
            "\u3010\u62a5\u544a\u65f6\u95f4\u30112026\u5e749\u670810\u65e514:00-15:00<br>\n"
            "\u3010\u62a5\u544a\u5730\u70b9\u3011\u6559\u4e5d\u697c9E406"
        )
        fields = parse_summary_fields(summary)
        self.assertEqual(fields["\u62a5\u544a\u65f6\u95f4"], "2026\u5e749\u670810\u65e514:00-15:00")
        self.assertEqual(fields["\u62a5\u544a\u5730\u70b9"], "\u6559\u4e5d\u697c9E406")

    def test_missing_data_list_raises(self):
        with self.assertRaises(SchoolFeedParseError):
            extract_school_items("<html><body>no list</body></html>")


class SchoolHtmlScraperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = EventStore(root / "events.json")
        self.scraper = EventScraper(
            store=self.store,
            feed_file=FIXTURE,
            pending_file=root / "pending.json",
            log_file=root / "scrape_log.jsonl",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_adds_good_and_queues_bad(self):
        result = self.scraper.run()
        self.assertEqual(result.fetched, 3)
        self.assertEqual(result.added, 2)
        self.assertEqual(result.pending, 1)
        self.assertEqual(len(result.parse_failures), 1)
        self.assertIn("\u5730\u70b9", result.parse_failures[0]["reason"])
        pending = self.scraper.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], "NJFU-9003")
        log_text = self.scraper.log_file.read_text(encoding="utf-8")
        self.assertIn("parse_failures", log_text)
        self.assertIn("NJFU-9003", log_text)

    def test_second_run_keeps_pending_once(self):
        self.scraper.run()
        second = self.scraper.run()
        self.assertEqual(second.pending, 0)
        self.assertEqual(len(self.scraper.pending()), 1)


if __name__ == "__main__":
    unittest.main()
