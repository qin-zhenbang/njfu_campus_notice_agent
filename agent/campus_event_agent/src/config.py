"""集中读取项目配置。

为避免引入第三方运行时依赖，这里使用一个小型 .env 读取器把密钥和
端点配置保留在源码之外，并统一转换成项目需要的类型。
"""

from __future__ import annotations

import os
from pathlib import Path


# 项目根目录：src 的上一级；数据、静态资源和对话记录统一放在根目录下。
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
CONVERSATION_DIR = DATA_DIR / "conversations"


# 读取根目录 .env；只设置尚未存在的环境变量，方便命令行临时覆盖。
def _load_dotenv() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


_load_dotenv()


# 读取字符串配置并去掉首尾空白。
def _get_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


# 把常见布尔值写法统一转换为 True/False。
def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


# 非法整数回退到默认值，避免配置错误导致启动失败。
def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# 服务与数据文件配置
HOST = _get_str("HOST", "127.0.0.1")
PORT = _get_int("PORT", 8000)
EVENT_FILE = DATA_DIR / _get_str("EVENT_FILE", "events.json")
FEED_FILE = DATA_DIR / _get_str("FEED_FILE", "feed_candidates.json")
PREFERENCES_FILE = DATA_DIR / _get_str("PREFERENCES_FILE", "user_preferences.json")
REMINDERS_FILE = DATA_DIR / _get_str("REMINDERS_FILE", "reminders.json")
PENDING_FILE = DATA_DIR / _get_str("PENDING_FILE", "pending_review.json")
SCRAPE_LOG_FILE = DATA_DIR / _get_str("SCRAPE_LOG_FILE", "scraping_log.jsonl")
NOTIFICATIONS_FILE = DATA_DIR / _get_str("NOTIFICATIONS_FILE", "notifications.json")
USAGE_FILE = DATA_DIR / _get_str("USAGE_FILE", "usage_stats.json")
# 校网抓取配置
SEMESTER_START = _get_str("SEMESTER_START", "2026-08-31")
EVENT_FEED_URL = _get_str("EVENT_FEED_URL", "https://www.njfu.edu.cn/xsdt/index.html")
EVENT_FEED_TIMEOUT = _get_int("EVENT_FEED_TIMEOUT", 8)
EVENT_FEED_PAGES = _get_int("EVENT_FEED_PAGES", 1)

# LLM 配置：默认连接本地 OpenAI 兼容接口
LLM_ENABLED = _get_bool("LLM_ENABLED", True)
LLM_BASE_URL = _get_str("LLM_BASE_URL", "http://127.0.0.1:1234/v1")
LLM_API_KEY = _get_str("LLM_API_KEY", "")
LLM_MODEL = _get_str("LLM_MODEL", "local-model")
LLM_TIMEOUT = _get_int("LLM_TIMEOUT", 30)

# 后台任务与运行限制
AUTO_FETCH_ENABLED = _get_bool("AUTO_FETCH_ENABLED", False)
AUTO_FETCH_INTERVAL = _get_int("AUTO_FETCH_INTERVAL", 3600)
AUTO_REMINDER_ENABLED = _get_bool("AUTO_REMINDER_ENABLED", True)
AUTO_REMINDER_INTERVAL = _get_int("AUTO_REMINDER_INTERVAL", 30)
MAX_RESULTS = _get_int("MAX_RESULTS", 50)
MAX_TOOL_CALLS = _get_int("MAX_TOOL_CALLS", 10)

