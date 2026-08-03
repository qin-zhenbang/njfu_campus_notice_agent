"""后台定时任务：周期抓取校网活动、周期检查到期提醒。"""

from __future__ import annotations

import logging
import threading
import time

from .event_store import EventStore
from .interest_matcher import InterestAgent, InterestMatcher
from .reminder_store import ReminderStore
from .scraper import EventScraper


logger = logging.getLogger(__name__)


# 定时抓取调度器：周期运行 EventScraper 并对新活动做兴趣推送。
class FeedScheduler:
    def __init__(
        self,
        scraper: EventScraper,
        store: EventStore,
        matcher: InterestMatcher,
        interval_seconds: int = 3600,
    ) -> None:
        self.scraper = scraper
        self.store = store
        self.matcher = matcher
        self.interest_agent = InterestAgent(matcher)
        self.interval = max(30, interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="feed-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.scraper.run()
                added = self.store.events[-result.added:] if result.added else []
                self.interest_agent.evaluate_new_events(added, source="scheduler")
                logger.info("scheduled scrape: %s", result.to_dict())
            except Exception as exc:  # pragma: no cover - defensive scheduler loop
                logger.exception("scheduled scrape failed: %s", exc)
            self._stop.wait(self.interval)


# 待办提醒调度器：周期检查并标记到期提醒。
class ReminderScheduler:
    def __init__(
        self,
        reminders: ReminderStore,
        interval_seconds: int = 30,
    ) -> None:
        self.reminders = reminders
        self.interval = max(1, interval_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="reminder-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # 供测试或手动触发时直接检查一次到期提醒。
    def check_now(self) -> list:
        return self.reminders.check_due()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                due = self.check_now()
                if due:
                    logger.info(
                        "due reminders: %s",
                        ", ".join(item.event_name for item in due),
                    )
            except Exception as exc:  # pragma: no cover - defensive scheduler loop
                logger.exception("reminder check failed: %s", exc)
            self._stop.wait(self.interval)
