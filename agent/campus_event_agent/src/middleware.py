"""轻量级中间件：记录工具和 LLM 调用统计。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .config import USAGE_FILE


# 负责记录调用次数、耗时和最近调用明细，并持久化到 usage_stats.json。
class Middleware:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else USAGE_FILE
        self.calls: list[dict] = []
        self.counts: Counter[str] = Counter()
        self.load()

    # 读取历史统计；文件损坏时清空重来。
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.calls = data.get("calls", [])
            self.counts = Counter(data.get("counts", {}))
        except (json.JSONDecodeError, OSError):
            self.calls = []
            self.counts = Counter()

    # 只保留最近 200 条调用记录，避免统计文件无限增长。
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "counts": dict(self.counts),
            "calls": self.calls[-200:],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 记录一次工具或 Agent 调用，并立即落盘。
    def record(self, kind: str, detail: str, duration_ms: float, tokens: int = 0) -> None:
        self.counts[kind] += 1
        self.calls.append(
            {
                "kind": kind,
                "detail": detail[:300],
                "duration_ms": round(duration_ms, 2),
                "tokens": tokens,
            }
        )
        self.save()

    # 汇总调用次数、总耗时、总 token 和最近调用。
    def stats(self) -> dict:
        total_duration = sum(item.get("duration_ms", 0) for item in self.calls)
        total_tokens = sum(item.get("tokens", 0) for item in self.calls)
        return {
            "counts": dict(self.counts),
            "total_calls": len(self.calls),
            "total_duration_ms": round(total_duration, 2),
            "total_tokens": total_tokens,
            "recent_calls": self.calls[-10:],
        }

