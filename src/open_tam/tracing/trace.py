from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable


class TraceRecorder:
    """排查过程逐条追加 JSONL：每行 {ts, alert_id, kind, ...fields}，可回放。

    sink：可选旁路回调（如 Web 流式广播），record 时在 JSONL 落盘后同步调用。
    trace 文件仍是唯一事实源。
    """

    def __init__(
        self,
        alert_id: str,
        traces_dir: Path | str | None = None,
        agent: str | None = None,
        sink: Callable[[dict], None] | None = None,
    ) -> None:
        base = (
            Path(traces_dir)
            if traces_dir
            else Path(os.environ.get("OPEN_TAM_TRACES_DIR", "traces"))
        )
        base.mkdir(parents=True, exist_ok=True)
        self.alert_id = alert_id
        self.agent = agent
        self.sink = sink
        self.path = base / f"{alert_id}.jsonl"

    def record(self, kind: str, **fields: object) -> None:
        entry: dict = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "alert_id": self.alert_id,
            "kind": kind,
        }
        if self.agent:
            entry["agent"] = self.agent
        entry.update(fields)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if self.sink:
            self.sink(entry)


def load_trace(path: Path | str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]
