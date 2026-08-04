"""校园活动与通知聚合 Agent 的入口脚本。

命令行用法：
    python run.py
    python run.py --port 8000
    python run.py --validate
    python run.py --fetch-once
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import AUTO_FETCH_ENABLED, AUTO_FETCH_INTERVAL, AUTO_REMINDER_ENABLED, AUTO_REMINDER_INTERVAL, HOST, PORT
from src.event_store import EventStore
from src.scraper import EventScraper


# 解析命令行参数，方便直接指定端口或运行单次任务。
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校园活动与通知聚合 Agent")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--validate", action="store_true", help="校验数据后退出")
    parser.add_argument("--fetch-once", action="store_true", help="执行一次抓取后退出")
    parser.add_argument("--auto-fetch", action="store_true", help="启动后台定时抓取")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # 活动仓库是后续查询、校验、抓取和人工审核共用的数据源。
    store = EventStore()

    # 校验模式：检查数据条数、必填字段、ISO 时间和类别数量后退出。
    if args.validate:
        errors = store.validate()
        if errors:
            print("数据校验失败：")
            for error in errors:
                print("-", error)
            return 1
        print(f"数据校验通过：{len(store.events)} 条活动，{len(store.categories())} 个类别")
        return 0

    if args.fetch_once:
        # 单次抓取模式：执行一次校网抓取并输出统计结果后退出。
        scraper = EventScraper(store=store)
        result = scraper.run()
        print(f"抓取完成：读取 {result.fetched}，新增 {result.added}，跳过 {result.skipped}，待确认 {result.pending}")
        for error in result.errors:
            print("错误:", error)
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from src.server import create_server

    # 服务模式：启动 HTTP 服务，并按配置开启定时抓取或待办提醒后台线程。
    server = create_server(host=args.host, port=args.port, auto_fetch=args.auto_fetch or AUTO_FETCH_ENABLED)
    print(f"校园活动聚合 Agent 已启动: http://{args.host}:{server.server_port}")
    print("按 Ctrl+C 停止服务。")
    if AUTO_REMINDER_ENABLED:
        print(f"待办提醒已开启，检查间隔 {AUTO_REMINDER_INTERVAL} 秒")
    if args.auto_fetch or AUTO_FETCH_ENABLED:
        print(f"定时抓取已开启，间隔 {AUTO_FETCH_INTERVAL} 秒")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

