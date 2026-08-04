# 部署文档

## 1. 环境准备

- Windows / Linux / macOS
- Python 3.10+

## 2. 从零启动

```bash
git clone <项目地址>
cd campus_event_agent
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt

python run.py --validate
python run.py
```

Agent 层使用 LangChain 依赖，请先完成上面的 `pip install -r requirements.txt`。浏览器访问：

```text
http://127.0.0.1:8000
```

## 3. 配置说明

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

关键变量：

| 变量 | 用途 |
|---|---|
| `HOST` / `PORT` | 服务监听地址和端口 |
| `SEMESTER_START` | 学期第一周周一的日期 |
| `LLM_ENABLED` | 是否启用 LLM |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 |
| `LLM_API_KEY` | 云端 API Key，LM Studio 可留空 |
| `LLM_MODEL` | 模型名 |
| `LLM_TIMEOUT` | LangChain 调用超时秒数 |
| `EVENT_FEED_URL` | 校网活动页地址，默认南京林业大学活动预告页；可配置 JSON feed |
| `EVENT_FEED_TIMEOUT` | 抓取校网页面或 JSON feed 的超时秒数 |
| `EVENT_FEED_PAGES` | 校网内嵌列表抓取页数，默认只抓最新 1 页 |
| `EVENT_FILE` / `FEED_FILE` | 活动数据文件和抓取候选文件 |
| `PREFERENCES_FILE` / `REMINDERS_FILE` | 兴趣偏好和提醒的长期记忆文件 |
| `PENDING_FILE` / `SCRAPE_LOG_FILE` | 待人工确认记录与抓取日志文件 |
| `NOTIFICATIONS_FILE` / `USAGE_FILE` | 兴趣推送记录与调用统计文件 |
| `MAX_RESULTS` | 单次检索最多返回活动数 |
| `MAX_TOOL_CALLS` | Agent 每次请求最多调用工具次数，默认 10 |
| `AUTO_FETCH_ENABLED` | 是否启动后台定时抓取 |
| `AUTO_FETCH_INTERVAL` | 抓取间隔秒数 |
| `AUTO_REMINDER_ENABLED` | 是否启动后台到点提醒检查，默认 true |
| `AUTO_REMINDER_INTERVAL` | 提醒检查间隔秒数，默认 30 |

## 4. 常见坑

- 端口被占用：改用 `python run.py --port 8001`。
- 中文路径：Windows 上建议保持项目目录可写；本项目已按 UTF-8 处理数据文件。
- LLM 连接失败：确认 `LLM_BASE_URL` 指向 OpenAI 兼容接口，LangChain ChatOpenAI 会调用 `/v1/chat/completions`；DeepSeek 可用 `https://api.deepseek.com/v1`。
- 抓取无数据：默认抓取南京林业大学活动预告页；若校网改版或离线，可配置本地 JSON/HTML 样例。解析失败会写入 `data/scraping_log.jsonl` 并进入待审核。
- 时间不准确：检查 `SEMESTER_START` 是否为本学期第一个周一。

## 5. 打包注意事项

提交前清理：

```text
.env
__pycache__/
.venv/
node_modules/
data/conversations/
data/scraping_log.jsonl
data/usage_stats.json
data/notifications.json
data/pending_review.json
data/reminders.json
data/user_preferences.json
```

## 6. 测试与证据

```bash
# 直接运行全部测试
python -m unittest discover -s tests -p 'test_*.py'

# 重新生成 tests/test_results.md
python tests/run_all.py
```

测试用例和测试结果位于 `tests/`，README 运行效果截图位于 `docs/screenshot.png`。
