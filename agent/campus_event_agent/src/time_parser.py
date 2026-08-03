"""确定性的中文自然语言时间解析。

该模块刻意不依赖 LLM，作为查询、活动数据校验和待办提醒共用的
时间标准化层，保证“第3周周三”“11.15”“周三下午”等表达能稳定转成日期。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .config import SEMESTER_START
from .models import ParsedTime


# 中文数字和阿拉伯数字到 Python weekday 的映射，周一是 0。
WEEKDAY_MAP = {
    "一": 0,
    "1": 0,
    "二": 1,
    "2": 1,
    "三": 2,
    "3": 2,
    "四": 3,
    "4": 3,
    "五": 4,
    "5": 4,
    "六": 5,
    "6": 5,
    "日": 6,
    "天": 6,
    "7": 6,
}


# 统一把 datetime 转成 date，方便按天计算。
def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


# 统一把 date 转成当天 00:00 的 datetime。
def _as_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime.min.time())


# 读取学期开始日期，解析失败时回退到默认日期。
def _parse_semester_start(value: str | None) -> date:
    if not value:
        value = SEMESTER_START
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return date(2026, 8, 31)


# 从文本中提取时段，返回 (小时, 分钟)；没有钟点表达时返回 None。
def _extract_time(text: str) -> tuple[int, int] | None:
    """Return (hour, minute) from text if a clock expression exists."""
    match = re.search(
        r"(上午|中午|下午|晚上|凌晨)?\s*(\d{1,2})\s*[点时:：]\s*(\d{2})?(?:\s*分)?",
        text,
    )
    if match:
        period = match.group(1) or ""
        hour = int(match.group(2))
        minute = int(match.group(3) or 0)
        if hour == 12:
            if period == "凌晨":
                hour = 0
            elif period == "下午" or period == "晚上":
                hour = 12
        elif period in {"下午", "晚上"} and hour < 12:
            hour += 12
        return hour, minute

    if "下午" in text:
        return 15, 0
    if "晚上" in text or "今晚" in text:
        return 19, 0
    if "中午" in text:
        return 12, 0
    if "上午" in text:
        return 9, 0
    return None


# 计算距离 base 最近的指定星期。
def _nearest_weekday(base: date, weekday: int) -> date:
    return base + timedelta(days=(weekday - base.weekday()) % 7)


# 把日期和文本中的时段合并成完整 datetime，缺省时间使用 default_hour。
def _combine_with_time(day: date, text: str, default_hour: int = 0) -> datetime:
    parsed_time = _extract_time(text)
    if parsed_time:
        return datetime.combine(day, datetime.min.time().replace(hour=parsed_time[0], minute=parsed_time[1]))
    return datetime.combine(day, datetime.min.time().replace(hour=default_hour))


# 识别“周三”“星期3”“礼拜五”等星期表达。
def _parse_weekday(text: str) -> int | None:
    match = re.search(r"(?:周|星期|礼拜)\s*([1-7一二三四五六日天])", text)
    if match:
        return WEEKDAY_MAP.get(match.group(1))
    if text.strip() in WEEKDAY_MAP:
        return WEEKDAY_MAP[text.strip()]
    return None


# 按学期起始日计算“第X周”，再结合可选周几和钟点生成日期时间。
def _parse_semester_week(text: str, base: date, semester_start: date) -> datetime | None:
    match = re.search(r"第\s*(\d{1,2})\s*周", text)
    if not match:
        return None
    week = int(match.group(1))
    monday = semester_start + timedelta(weeks=week - 1)
    weekday = _parse_weekday(text)
    if weekday is None:
        return _combine_with_time(monday, text, 9)
    day = monday + timedelta(days=weekday)
    return _combine_with_time(day, text, 9)


# 解析 ISO 日期、中文月日和“11.15”等绝对日期形式。
def _parse_absolute_date(text: str, base: date) -> tuple[date, date] | None:
    """Parse ISO/Chinese dotted date forms and return the matched text range."""
    patterns = [
        r"(?P<year>20\d{2})[年./-](?P<month>\d{1,2})[月./-](?P<day>\d{1,2})日?",
        r"(?P<month>\d{1,2})[月./-](?P<day>\d{1,2})日?",
        r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日",
        r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        year = int(match.group("year")) if "year" in match.groupdict() and match.group("year") else base.year
        month = int(match.group("month"))
        day = int(match.group("day"))
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None
        return parsed, parsed
    return None


# 解析今天/明天/后天/下个月/本月/下周/本周等相对日期表达。
def _parse_relative_date(text: str, base: date) -> date | None:
    normalized = re.sub(r"\s+", "", text)
    if "今天" in normalized:
        return base
    if "明天" in normalized:
        return base + timedelta(days=1)
    if "后天" in normalized:
        return base + timedelta(days=2)

    if "下个月" in normalized:
        month_day = re.search(r"下个月\s*(\d{1,2})日?", normalized)
        if month_day:
            day = int(month_day.group(1))
            if base.month == 12:
                try:
                    return date(base.year + 1, 1, day)
                except ValueError:
                    return None
            try:
                return date(base.year, base.month + 1, day)
            except ValueError:
                return None
        if base.month == 12:
            return date(base.year + 1, 1, 1)
        return date(base.year, base.month + 1, 1)
    if "本月" in normalized or "这个月" in normalized:
        month_day = re.search(r"(?:本月|这个月)\s*(\d{1,2})日?", normalized)
        if month_day:
            try:
                return date(base.year, base.month, int(month_day.group(1)))
            except ValueError:
                return None
        return date(base.year, base.month, 1)

    if "下周" in normalized:
        monday = base + timedelta(days=(7 - base.weekday()) % 7 or 7)
        weekday_match = re.search(r"下周(?:周|星期|礼拜)?\s*([1-7一二三四五六日天])", normalized)
        weekday = _parse_weekday(weekday_match.group(1)) if weekday_match else None
        if weekday is None:
            return monday
        return monday + timedelta(days=weekday)

    if "本周" in normalized or "这周" in normalized:
        monday = base - timedelta(days=base.weekday())
        weekday_match = re.search(r"(?:本周|这周)(?:周|星期|礼拜)?\s*([1-7一二三四五六日天])", normalized)
        weekday = _parse_weekday(weekday_match.group(1)) if weekday_match else None
        if weekday is None:
            return monday
        return monday + timedelta(days=weekday)

    match = re.search(r"周(?:末)?([一二三四五六日天1-7])", normalized)
    if match:
        return _nearest_weekday(base, _parse_weekday(match.group(1)) or 0)

    return None


# 把单个时间表达解析为具体的 datetime 范围。
def parse_datetime(
    text: str,
    base: date | datetime | None = None,
    semester_start: str | None = None,
) -> ParsedTime | None:
    """Parse one time expression into a concrete datetime range."""
    if not text or not text.strip():
        return None
    base_date = _as_date(base or date.today())
    sem_start = _parse_semester_start(semester_start)
    normalized = " ".join(text.strip().split())
    # 统一中文标点，避免全角冒号、括号影响正则匹配。
    normalized = normalized.replace("：", ":").replace("，", ",").replace("（", "(").replace("）", ")")

    # 解析优先级：学期周 > 绝对日期 > 相对日期 > 仅时段。
    semester_time = _parse_semester_week(normalized, base_date, sem_start)
    if semester_time is not None:
        return ParsedTime(
            start=semester_time,
            end=semester_time,
            kind="week",
            display=semester_time.strftime("%Y-%m-%d %H:%M"),
        )

    absolute = _parse_absolute_date(normalized, base_date)
    if absolute is not None:
        day, _ = absolute
        parsed = _combine_with_time(day, normalized, 9)
        return ParsedTime(
            start=parsed,
            end=parsed,
            kind="absolute",
            display=parsed.strftime("%Y-%m-%d %H:%M"),
        )

    relative = _parse_relative_date(normalized, base_date)
    if relative is not None:
        parsed = _combine_with_time(relative, normalized, 9)
        return ParsedTime(
            start=parsed,
            end=parsed,
            kind="relative",
            display=parsed.strftime("%Y-%m-%d %H:%M"),
        )

    time_part = _extract_time(normalized)
    if time_part is not None:
        parsed = datetime.combine(base_date, datetime.min.time().replace(hour=time_part[0], minute=time_part[1]))
        return ParsedTime(
            start=parsed,
            end=parsed,
            kind="time",
            display=parsed.strftime("%Y-%m-%d %H:%M"),
        )
    return None


# 把查询范围解析为起止时间，例如“本周”“下个月”“11.15”或“A到B”。
def parse_time_range(
    text: str,
    base: date | datetime | None = None,
    semester_start: str | None = None,
) -> ParsedTime | None:
    """Parse a query range such as 本周, 下个月, 11.15 or A到B."""
    if not text or not text.strip():
        return None
    base_date = _as_date(base or date.today())
    normalized = " ".join(text.strip().split())

    # 范围查询优先处理整段语义：本周/下周/本月/下个月/今天/明天。
    if "本周" in normalized or "这周" in normalized:
        weekday_match = re.search(r"(?:本周|这周)(?:周|星期|礼拜)?\s*([1-7一二三四五六日天])", normalized)
        if weekday_match:
            single = parse_datetime(normalized, base_date, semester_start)
            if single:
                if single.start.time() == datetime.min.time().replace(hour=9):
                    single.end = datetime.combine(single.start.date(), datetime.max.time())
                return ParsedTime(
                    start=single.start,
                    end=single.end,
                    kind="range",
                    display=single.display,
                )
        monday = base_date - timedelta(days=base_date.weekday())
        return ParsedTime(
            start=datetime.combine(monday, datetime.min.time()),
            end=datetime.combine(monday + timedelta(days=6), datetime.max.time()),
            kind="range",
            display=f"{monday:%Y-%m-%d} 至 {monday + timedelta(days=6):%Y-%m-%d}",
        )
    if "下周" in normalized:
        weekday_match = re.search(r"下周(?:周|星期|礼拜)?\s*([1-7一二三四五六日天])", normalized)
        if weekday_match:
            single = parse_datetime(normalized, base_date, semester_start)
            if single:
                if single.start.time() == datetime.min.time().replace(hour=9):
                    single.end = datetime.combine(single.start.date(), datetime.max.time())
                return ParsedTime(
                    start=single.start,
                    end=single.end,
                    kind="range",
                    display=single.display,
                )
        monday = base_date + timedelta(days=(7 - base_date.weekday()) % 7 or 7)
        return ParsedTime(
            start=datetime.combine(monday, datetime.min.time()),
            end=datetime.combine(monday + timedelta(days=6), datetime.max.time()),
            kind="range",
            display=f"{monday:%Y-%m-%d} 至 {monday + timedelta(days=6):%Y-%m-%d}",
        )
    if "本月" in normalized or "这个月" in normalized:
        first = date(base_date.year, base_date.month, 1)
        if base_date.month == 12:
            last = date(base_date.year, 12, 31)
        else:
            last = date(base_date.year, base_date.month + 1, 1) - timedelta(days=1)
        return ParsedTime(
            start=datetime.combine(first, datetime.min.time()),
            end=datetime.combine(last, datetime.max.time()),
            kind="range",
            display=f"{first:%Y-%m-%d} 至 {last:%Y-%m-%d}",
        )
    if "下个月" in normalized:
        if base_date.month == 12:
            first = date(base_date.year + 1, 1, 1)
        else:
            first = date(base_date.year, base_date.month + 1, 1)
        if first.month == 12:
            last = date(first.year, 12, 31)
        else:
            last = date(first.year, first.month + 1, 1) - timedelta(days=1)
        return ParsedTime(
            start=datetime.combine(first, datetime.min.time()),
            end=datetime.combine(last, datetime.max.time()),
            kind="range",
            display=f"{first:%Y-%m-%d} 至 {last:%Y-%m-%d}",
        )
    if "今天" in normalized:
        return ParsedTime(
            start=datetime.combine(base_date, datetime.min.time()),
            end=datetime.combine(base_date, datetime.max.time()),
            kind="range",
            display=base_date.isoformat(),
        )
    if "明天" in normalized:
        day = base_date + timedelta(days=1)
        return ParsedTime(
            start=datetime.combine(day, datetime.min.time()),
            end=datetime.combine(day, datetime.max.time()),
            kind="range",
            display=day.isoformat(),
        )

    # 支持“A到B”形式的起止范围。
    for separator in ["到", "至", "~", "～", "-"]:
        if separator in normalized:
            left, right = normalized.split(separator, 1)
            start = parse_datetime(left, base_date, semester_start)
            end = parse_datetime(right, base_date, semester_start)
            if start and end:
                return ParsedTime(
                    start=start.start,
                    end=end.end,
                    kind="range",
                    display=f"{start.display} 至 {end.display}",
                )

    # 兜底：没有明确范围时按单日范围处理。
    single = parse_datetime(normalized, base_date, semester_start)
    if single is not None:
        if single.kind in {"absolute", "week", "relative"} and (
            single.start.time() == datetime.min.time() or single.start.time() == datetime.min.time().replace(hour=9)
        ):
            single.end = datetime.combine(single.start.date(), datetime.max.time())
        return ParsedTime(
            start=single.start,
            end=single.end,
            kind="range",
            display=single.display,
        )
    return None
