"""中文自然语言时间解析器的单元测试。"""

import unittest
from datetime import date

from src.time_parser import parse_datetime, parse_time_range


BASE = date(2026, 9, 7)


# 覆盖学期周、绝对日期、相对日期、时段和范围解析。
class TimeParserTests(unittest.TestCase):
    def test_semester_week(self):
        parsed = parse_datetime("第3周周三 14:30", base=BASE, semester_start="2026-08-31")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.start.isoformat(), "2026-09-16T14:30:00")

    def test_dotted_date(self):
        parsed = parse_datetime("11.15 09:00", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-11-15T09:00:00")

    def test_weekday_afternoon(self):
        parsed = parse_datetime("周三下午", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-09-09T15:00:00")

    def test_next_week_weekday(self):
        parsed = parse_datetime("下周三", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-09-16T09:00:00")

    def test_tomorrow(self):
        parsed = parse_datetime("明天 10:20", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-09-08T10:20:00")

    def test_this_month_day(self):
        parsed = parse_datetime("本月15日", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-09-15T09:00:00")

    def test_next_month_day(self):
        parsed = parse_datetime("下个月5日", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-10-05T09:00:00")

    def test_this_week_friday(self):
        parsed = parse_datetime("本周五", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-09-11T09:00:00")

    def test_chinese_month_day(self):
        parsed = parse_datetime("9月20日 10:00", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-09-20T10:00:00")

    def test_evening_time(self):
        parsed = parse_datetime("晚上8点", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-09-07T20:00:00")

    def test_iso_datetime(self):
        parsed = parse_datetime("2026-10-20 14:00", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-10-20T14:00:00")

    def test_range_this_week(self):
        parsed = parse_time_range("本周", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-09-07T00:00:00")
        self.assertEqual(parsed.end.isoformat(), "2026-09-13T23:59:59.999999")

    def test_range_next_month(self):
        parsed = parse_time_range("下个月", base=BASE)
        self.assertEqual(parsed.start.isoformat(), "2026-10-01T00:00:00")
        self.assertEqual(parsed.end.isoformat(), "2026-10-31T23:59:59.999999")


if __name__ == "__main__":
    unittest.main()

