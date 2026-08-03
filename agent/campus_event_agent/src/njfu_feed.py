"""Parser for the Nanjing Forestry University activity preview page."""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any


SCHOOL_FEED_URL = "https://www.njfu.edu.cn/xsdt/index.html"
SOURCE_NAME = "南京林业大学校网"


class SchoolFeedParseError(ValueError):
    """Raised when the school page no longer contains a parseable list."""


def extract_school_items(page_html: str, max_pages: int = 1) -> list[dict[str, Any]]:
    """Return normalized candidates from the embedded dataList payload.

    The page usually embeds one or more page objects. By default only the first
    page is imported so a scheduled run focuses on the latest activity list.
    """
    if not page_html or "dataList" not in page_html:
        raise SchoolFeedParseError("页面中未找到 dataList 数据")

    marker = "var dataList="
    start = page_html.find(marker)
    if start < 0:
        raise SchoolFeedParseError("页面中未找到 var dataList= 标记")
    start += len(marker)
    while start < len(page_html) and page_html[start].isspace():
        start += 1

    try:
        payload, _ = json.JSONDecoder().raw_decode(page_html, start)
    except json.JSONDecodeError as exc:
        raise SchoolFeedParseError(f"dataList JSON 解析失败: {exc}") from exc

    if isinstance(payload, dict):
        payload = payload.get("infolist", payload.get("data", []))
    if not isinstance(payload, list):
        raise SchoolFeedParseError("dataList 结构异常")

    raw_items: list[dict[str, Any]] = []
    if payload and isinstance(payload[0], dict) and "infolist" in payload[0]:
        for page in payload[: max(1, max_pages)]:
            raw_items.extend(page.get("infolist") or [])
    else:
        raw_items.extend(payload)

    return [to_candidate(item) for item in raw_items if isinstance(item, dict)]


def parse_summary_fields(summary: str) -> dict[str, str]:
    """Extract labeled fields such as 报告人, 报告时间 and 报告地点."""
    if not summary:
        return {}
    cleaned = html.unescape(summary)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)

    fields: dict[str, str] = {}
    section_pattern = re.compile(r"【([^】]+)】\s*[:：]?\s*(.*?)(?=【|\Z)", re.DOTALL)
    for match in section_pattern.finditer(cleaned):
        value = " ".join(match.group(2).split())
        if value:
            fields[match.group(1).strip()] = value
    return fields


def classify_njfu_category(title: str, summary: str = "") -> str:
    """Choose a stable project category from title and summary keywords."""
    text = f"{title} {summary}"
    if any(keyword in text for keyword in ("讲座", "分享", "宣讲", "培训")):
        return "讲座"
    if any(keyword in text for keyword in ("竞赛", "比赛", "大赛", "选拔")):
        return "竞赛"
    if any(keyword in text for keyword in ("社团", "招新")):
        return "社团招新"
    if any(keyword in text for keyword in ("教务", "通知", "报名", "申报", "选课", "招聘", "就业")):
        return "教务通知"
    if any(keyword in text for keyword in ("文体", "文化", "体育", "演出", "展览", "艺术", "设计", "论坛")):
        return "文体活动"
    if any(keyword in text for keyword in ("志愿", "公益", "服务")):
        return "志愿服务"
    return "讲座"


def to_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """Convert one school-page item into the scraper candidate schema."""
    title = _clean_text(item.get("title") or item.get("infotitle") or "")
    fields = parse_summary_fields(str(item.get("summary", "")))
    summary = _clean_text(str(item.get("summary", "")))
    category = classify_njfu_category(title, summary)

    return {
        "id": _stable_id(item, title),
        "name": title,
        "category": category,
        "raw_time": fields.get("报告时间", ""),
        "location": fields.get("报告地点", ""),
        "description": summary,
        "source": SOURCE_NAME,
        "source_url": str(item.get("url", "")),
        "speaker": fields.get("报告人", ""),
        "tags": ["校网", category],
    }


def _clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _stable_id(item: dict[str, Any], title: str) -> str:
    iid = item.get("iid")
    if iid:
        return f"NJFU-{iid}"
    url = str(item.get("url", "")).strip()
    if url:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12].upper()
        return f"NJFU-{digest}"
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:12].upper()
    return f"NJFU-{digest}"
