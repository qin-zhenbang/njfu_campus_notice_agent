"""活动数据仓库校验、三类查询与新增/编辑/删除的单元测试。"""

import tempfile
import unittest
from pathlib import Path

from src.config import DATA_DIR
from src.event_store import EventStore
from src.models import Event


# 使用项目真实数据验证校验、关键词/类别/时间范围检索和展示字段。
class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = EventStore(DATA_DIR / "events.json")

    # 创建独立的临时 EventStore，新增/编辑/删除测试不碰 data/events.json。
    def _temp_store(self):
        tmp = tempfile.TemporaryDirectory()
        return EventStore(Path(tmp.name) / "events.json"), tmp

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
        self.assertIn("duration_minutes", display)
        self.assertNotIn("end_time", display)
        self.assertIn("contact", display)

    def test_mixed_time_formats(self):
        events = EventStore(DATA_DIR / "events.json").events
        raw_times = " ".join(event.raw_time for event in events)
        self.assertIn("第", raw_times)
        self.assertIn("11.", raw_times)
        self.assertIn("下午", raw_times)

    # 不传 ID 时自动生成 EVT-001、EVT-002 且不重复，落盘后可重新加载。
    def test_create_event_auto_id(self):
        store, tmp = self._temp_store()
        try:
            ok, result = store.create_event(
                {
                    "name": "测试新增活动",
                    "time": "2026-09-01 10:00",
                    "location": "教五楼",
                    "category": "讲座",
                    "tags": "AI, 讲座",
                }
            )
            self.assertTrue(ok)
            self.assertIsInstance(result, Event)
            self.assertEqual(result.id, "EVT-001")
            self.assertEqual(result.time, "2026-09-01T10:00:00")
            self.assertEqual(result.tags, ["AI", "讲座"])

            ok2, result2 = store.create_event(
                {"name": "测试新增活动二", "time": "2026-09-02T14:30", "location": "图书馆"}
            )
            self.assertTrue(ok2)
            self.assertEqual(result2.id, "EVT-002")

            reloaded = EventStore(store.path).get("EVT-001")
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.name, "测试新增活动")
        finally:
            tmp.cleanup()

    # 新增缺少必填字段时返回错误，不写入文件。
    def test_create_event_requires_fields(self):
        store, tmp = self._temp_store()
        try:
            ok, message = store.create_event({"name": "缺时间"})
            self.assertFalse(ok)
            self.assertIn("时间", message)
            self.assertEqual(len(store.events), 0)
        finally:
            tmp.cleanup()

    # 修改字段后落盘生效；清空必填字段或 ID 不存在时返回错误。
    def test_update_event(self):
        store, tmp = self._temp_store()
        try:
            ok, result = store.create_event(
                {"name": "原名", "time": "2026-09-01T10:00:00", "location": "A楼"}
            )
            self.assertTrue(ok)
            updated, message = store.update_event(
                result.id, {"name": "新名", "location": "B楼", "tags": "讲座, AI"}
            )
            self.assertTrue(updated)
            self.assertEqual(message, "ok")

            reloaded = EventStore(store.path).get(result.id)
            self.assertEqual(reloaded.name, "新名")
            self.assertEqual(reloaded.location, "B楼")
            self.assertEqual(reloaded.tags, ["讲座", "AI"])

            bad, msg = store.update_event(result.id, {"name": ""})
            self.assertFalse(bad)
            self.assertIn("名称", msg)

            missing, missing_msg = store.update_event("EVT-NOPE", {"name": "x"})
            self.assertFalse(missing)
            self.assertIn("不存在", missing_msg)
        finally:
            tmp.cleanup()

    # 删除后 get() 返回 None，且落盘生效；重复删除返回失败。
    def test_delete_event(self):
        store, tmp = self._temp_store()
        try:
            ok, result = store.create_event(
                {"name": "待删除", "time": "2026-09-01T10:00:00", "location": "C楼"}
            )
            self.assertTrue(ok)
            deleted, message = store.delete_event(result.id)
            self.assertTrue(deleted)
            self.assertEqual(message, "ok")
            self.assertIsNone(EventStore(store.path).get(result.id))

            missing, _ = store.delete_event(result.id)
            self.assertFalse(missing)
        finally:
            tmp.cleanup()


    # 新增时传入持续时间，换算成 duration_minutes 存储并落盘。
    def test_create_event_with_duration(self):
        store, tmp = self._temp_store()
        try:
            ok, result = store.create_event(
                {
                    "name": "带时长活动",
                    "time": "2026-09-01T10:00:00",
                    "location": "A楼",
                    "duration": "2小时30分钟",
                }
            )
            self.assertTrue(ok)
            self.assertEqual(result.duration_minutes, 150)
            self.assertEqual(result.display_dict()["duration"], "2小时30分钟")
            self.assertNotIn("end_time", result.to_dict())

            ok2, result2 = store.create_event(
                {
                    "name": "带时长活动二",
                    "time": "2026-09-01T10:00:00",
                    "location": "B楼",
                    "duration": "1.5小时",
                }
            )
            self.assertTrue(ok2)
            self.assertEqual(result2.duration_minutes, 90)

            reloaded = EventStore(store.path).get(result.id)
            self.assertEqual(reloaded.duration_minutes, 150)
        finally:
            tmp.cleanup()

    # 修改持续时间：改动重算，传空串则清空。
    def test_update_event_duration(self):
        store, tmp = self._temp_store()
        try:
            ok, result = store.create_event(
                {
                    "name": "改时长",
                    "time": "2026-09-01T10:00:00",
                    "location": "A楼",
                    "duration": "90分钟",
                }
            )
            self.assertTrue(ok)
            self.assertEqual(result.duration_minutes, 90)

            updated, message = store.update_event(result.id, {"duration": "2小时"})
            self.assertTrue(updated)
            self.assertEqual(EventStore(store.path).get(result.id).duration_minutes, 120)

            cleared, _ = store.update_event(result.id, {"duration": ""})
            self.assertTrue(cleared)
            self.assertEqual(EventStore(store.path).get(result.id).duration_minutes, 0)
        finally:
            tmp.cleanup()

    # 非法持续时间返回失败且不写入文件。
    def test_create_event_invalid_duration(self):
        store, tmp = self._temp_store()
        try:
            ok, message = store.create_event(
                {
                    "name": "坏时长",
                    "time": "2026-09-01T10:00:00",
                    "location": "A楼",
                    "duration": "乱写的",
                }
            )
            self.assertFalse(ok)
            self.assertIn("持续时间", message)
            self.assertEqual(len(store.events), 0)
        finally:
            tmp.cleanup()

    # 旧数据带 end_time 时，加载后换算成 duration_minutes 且不再保留 end_time。
    def test_legacy_end_time_migration(self):
        store, tmp = self._temp_store()
        try:
            import json
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text(
                json.dumps(
                    [
                        {
                            "id": "EVT-LEGACY",
                            "name": "旧活动",
                            "category": "讲座",
                            "raw_time": "2026-09-01 10:00",
                            "time": "2026-09-01T10:00:00",
                            "location": "A楼",
                            "source": "旧源",
                            "end_time": "2026-09-01T12:30:00",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            reloaded = EventStore(store.path).get("EVT-LEGACY")
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.duration_minutes, 150)
            self.assertNotIn("end_time", reloaded.to_dict())
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()