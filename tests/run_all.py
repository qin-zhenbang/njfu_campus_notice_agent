"""运行全部测试并生成 tests/test_results.md 测试结果文档。"""

from __future__ import annotations

import io
import sys
import unittest
from datetime import datetime
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
    buffer = io.StringIO()
    runner = unittest.TextTestRunner(stream=buffer, verbosity=2)
    result = runner.run(suite)

    output = buffer.getvalue()
    summary = (
        f"# 测试结果\n\n"
        f"- 运行时间：{datetime.now().isoformat(timespec='seconds')}\n"
        f"- 用例数：{result.testsRun}\n"
        f"- 通过：{result.testsRun - len(result.failures) - len(result.errors)}\n"
        f"- 失败：{len(result.failures)}\n"
        f"- 错误：{len(result.errors)}\n\n"
        "## 输出\n\n```text\n"
        f"{output}\n"
        "```\n"
    )
    (root / "tests" / "test_results.md").write_text(summary, encoding="utf-8")
    print(output)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

