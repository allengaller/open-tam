from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


class TraceRecorder:
    """排查过程逐条追加 JSONL：每行 {ts, alert_id, kind, ...fields}，可回放。"""

    def __init__(self, alert_id: str, traces_dir: Path | str | None = None) -> None:
        base = (
            Path(traces_dir)
            if traces_dir
            else Path(os.environ.get("OPEN_TAM_TRACES_DIR", "traces"))
        )
        base.mkdir(parents=True, exist_ok=True)
        self.alert_id = alert_id
        self.path = base / f"{alert_id}.jsonl"

    def record(self, kind: str, **fields: object) -> None:
        line = json.dumps(
            {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "alert_id": self.alert_id,
                "kind": kind,
                **fields,
            },
            ensure_ascii=False,
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_trace(path: Path | str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]
