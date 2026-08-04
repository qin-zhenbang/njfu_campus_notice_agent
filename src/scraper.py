"""校网活动抓取与“人工确认”解析审核。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import EVENT_FEED_PAGES, EVENT_FEED_TIMEOUT, EVENT_FEED_URL, FEED_FILE, PENDING_FILE, SCRAPE_LOG_FILE
from .event_store import EventStore
from .models import Event, minutes_between
from .njfu_feed import SchoolFeedParseError, extract_school_items
from .time_parser import parse_datetime, parse_duration


logger = logging.getLogger(__name__)


# 抓取结果：记录读取、新增、跳过、待人工确认和解析失败明细。
@dataclass
class ScrapeResult:
    run_id: str
    fetched: int = 0
    added: int = 0
    skipped: int = 0
    pending: int = 0
    errors: list[str] = field(default_factory=list)
    parse_failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "fetched": self.fetched,
            "added": self.added,
            "skipped": self.skipped,
            "pending": self.pending,
            "errors": self.errors,
            "parse_failures": self.parse_failures,
            "time": datetime.now().isoformat(timespec="seconds"),
        }


# 负责拉取校网/本地样例、解析活动、写日志并维护待审核队列。
class EventScraper:
    def __init__(
        self,
        store: EventStore,
        feed_url: str = "",
        feed_file: Path | str | None = None,
        pending_file: Path | str | None = None,
        log_file: Path | str | None = None,
    ) -> None:
        self.store = store
        self.feed_url = feed_url or ("" if feed_file else EVENT_FEED_URL)
        self.feed_file = Path(feed_file) if feed_file else FEED_FILE
        self.pending_file = Path(pending_file) if pending_file else PENDING_FILE
        self.log_file = Path(log_file) if log_file else SCRAPE_LOG_FILE

    # 优先抓取 HTTP 页面；页面不是 HTML 时按 JSON 处理，也可读本地样例文件。
    def fetch_feed(self) -> tuple[list[dict[str, Any]], str | None]:
        """从校网 HTML 页面、JSON 地址或本地示例源获取候选记录。"""
        if self.feed_url.startswith(("http://", "https://")):
            try:
                request = urllib.request.Request(
                    self.feed_url,
                    headers={"User-Agent": "Mozilla/5.0 campus-event-agent/1.0"},
                )
                with urllib.request.urlopen(request, timeout=EVENT_FEED_TIMEOUT) as response:
                    raw = response.read()
                text = raw.decode("utf-8", errors="replace")
                if "dataList" in text:
                    try:
                        items = extract_school_items(text, max_pages=EVENT_FEED_PAGES)
                    except SchoolFeedParseError as exc:
                        return [], f"校网页面解析失败: {exc}"
                    return items, "南京林业大学活动预告"
                lowered = text.lower()
                if "<html" in lowered or "<body" in lowered or "<div" in lowered:
                    return [], "校网页面解析失败: 页面中未找到 dataList 数据"
                data = json.loads(text)
                items = data if isinstance(data, list) else data.get("events", data.get("data", []))
                return items, self.feed_url
            except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as exc:
                return [], f"抓取失败: {exc}"
        if self.feed_file.exists():
            text = self.feed_file.read_text(encoding="utf-8")
            if self.feed_file.suffix.lower() in {".html", ".htm"}:
                try:
                    items = extract_school_items(text, max_pages=EVENT_FEED_PAGES)
                except SchoolFeedParseError as exc:
                    return [], f"本地校网样例解析失败: {exc}"
                return items, f"本地校网样例 {self.feed_file.name}"
            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("events", [])
            return items, f"本地示例源 {self.feed_file.name}"
        return [], "未找到本地示例源"

    # 执行一次完整抓取：解析每条候选，重复跳过，解析失败的进入人工确认。
    def run(self) -> ScrapeResult:
        run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        items, source_or_error = self.fetch_feed()
        result = ScrapeResult(run_id=run_id)
        if source_or_error and source_or_error.startswith(("抓取失败", "解析失败")):
            result.errors.append(source_or_error)
            self._log(result, source_or_error)
            return result

        result.fetched = len(items)
        pending = self._load_pending()
        pending_ids = {
            str(item.get("id"))
            for item in pending
            if item.get("status") == "pending" and item.get("id")
        }
        for item in items:
            parsed = self._parse_candidate(item, source_or_error)
            if parsed is None:
                item_id = str(item.get("id", ""))
                reason = self._candidate_issue(item)
                if item_id and item_id in pending_ids:
                    result.skipped += 1
                    continue
                result.pending += 1
                pending.append(
                    {
                        "id": item_id,
                        "raw": item,
                        "reason": reason or "缺少名称/地点，或时间无法解析",
                        "status": "pending",
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                pending_ids.add(item_id)
                result.parse_failures.append(
                    {
                        "id": item_id,
                        "reason": reason or "缺少名称/地点，或时间无法解析",
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                continue
            event, message = parsed
            if message == "duplicate":
                result.skipped += 1
                continue
            if message != "ok":
                result.errors.append(message)
                continue
            self.store.add_event(event)
            result.added += 1
        self._save_pending(pending)
        self._log(result, source_or_error)
        return result

    # 返回待人工确认的抓取记录。
    def pending(self) -> list[dict[str, Any]]:
        return self._load_pending()

    # 人工批准后重新解析并入库，拒绝则直接标记 rejected。
    def review(self, pending_id: str, approved: bool) -> dict[str, Any] | None:
        pending = self._load_pending()
        for item in pending:
            if item.get("id") == pending_id and item.get("status") == "pending":
                if approved:
                    raw = item.get("raw", {})
                    parsed = self._parse_candidate(raw, "人工确认")
                    if parsed is None:
                        item["status"] = "rejected"
                        item["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
                        self._save_pending(pending)
                        self._log_review(pending_id, "rejected", "人工确认后仍无法解析")
                        return item
                    event, message = parsed
                    if message == "ok":
                        self.store.add_event(event)
                        item["status"] = "approved"
                    else:
                        item["status"] = "skipped"
                else:
                    item["status"] = "rejected"
                item["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_pending(pending)
                self._log_review(pending_id, item["status"], item.get("reason", ""))
                return item
        return None

    # 生成可读的失败原因，供人工确认界面展示。
    def _candidate_issue(self, item: dict[str, Any]) -> str:
        name = str(item.get("name", "")).strip()
        raw_time = str(item.get("raw_time", "")).strip()
        time_value = str(item.get("time", "")).strip()
        location = str(item.get("location", "")).strip()
        missing = []
        if not name:
            missing.append("名称")
        if not location:
            missing.append("地点")
        if not time_value and not raw_time:
            missing.append("时间")
        if missing:
            return "缺少" + "、".join(missing)
        if not time_value:
            parsed = parse_datetime(raw_time)
            if parsed is None:
                return f"时间无法解析: {raw_time[:100]}"
        return "缺少名称/地点，或时间无法解析"

    # 校验名称/地点/时间并把候选转换为 Event；重复返回 duplicate。
    def _parse_candidate(self, item: dict[str, Any], source: str) -> tuple[Event, str] | None:
        name = str(item.get("name", "")).strip()
        category = str(item.get("category", "")).strip()
        raw_time = str(item.get("raw_time", "")).strip()
        location = str(item.get("location", "")).strip()
        time_value = str(item.get("time", "")).strip()
        if not name or not location:
            return None
        if not time_value:
            parsed = parse_datetime(raw_time)
            if parsed is None:
                return None
            time_value = parsed.start.isoformat(timespec="seconds")
        event = Event(
            id=str(item.get("id", f"FEED-{datetime.now().timestamp():.0f}")),
            name=name,
            category=category or "其他",
            raw_time=raw_time,
            time=time_value,
            location=location,
            description=str(item.get("description", "")),
            source=str(item.get("source", source or "校园网")),
            source_url=str(item.get("source_url", "")),
            tags=[str(tag) for tag in item.get("tags", [])],
            duration_minutes=self._candidate_duration(item, time_value),
            contact=str(item.get("contact", "")),
        )
        if self.store.get(event.id):
            return event, "duplicate"
        return event, "ok"

    # 从候选记录解析持续时长：优先 duration 文本，其次 duration_minutes，最后按 end_time 换算。
    def _candidate_duration(self, item: dict[str, Any], start_time: str) -> int:
        raw = item.get("duration")
        if raw not in (None, ""):
            parsed = parse_duration(str(raw))
            if parsed is not None:
                return parsed
        raw_minutes = item.get("duration_minutes")
        if raw_minutes not in (None, ""):
            try:
                return max(0, int(raw_minutes))
            except (TypeError, ValueError):
                pass
        if item.get("end_time"):
            return minutes_between(start_time, str(item.get("end_time")))
        return 0

    # 加载待审核队列。
    def _load_pending(self) -> list[dict[str, Any]]:
        if not self.pending_file.exists():
            return []
        return json.loads(self.pending_file.read_text(encoding="utf-8"))

    # 持久化待审核队列。
    def _save_pending(self, pending: list[dict[str, Any]]) -> None:
        self.pending_file.parent.mkdir(parents=True, exist_ok=True)
        self.pending_file.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 以 JSONL 形式追加抓取日志，便于复盘和排查。
    def _log(self, result: ScrapeResult, detail: str) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        entry = result.to_dict()
        entry["detail"] = detail
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # 记录人工审核动作，形成数据清洗/审核轨迹。
    def _log_review(self, pending_id: str, status: str, reason: str = "") -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "type": "review",
            "pending_id": pending_id,
            "status": status,
            "reason": reason,
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
