from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    state_dir: Path
    reports_dir: Path
    inbox_dir: Path
    traces_dir: Path
    model_primary: str
    model_fallback: str
    max_steps: int
    char_budget: int

    @classmethod
    def load(cls) -> "Settings":
        base = Path(os.environ.get("OPEN_TAM_BASE_DIR", "."))
        return cls(
            state_dir=Path(os.environ.get("OPEN_TAM_STATE_DIR", base / "var")),
            reports_dir=Path(os.environ.get("OPEN_TAM_REPORTS_DIR", base / "reports")),
            inbox_dir=Path(os.environ.get("OPEN_TAM_INBOX_DIR", base / "var" / "inbox")),
            traces_dir=Path(os.environ.get("OPEN_TAM_TRACES_DIR", base / "traces")),
            model_primary=os.environ.get("OPEN_TAM_MODEL_PRIMARY", "qwen-plus"),
            model_fallback=os.environ.get("OPEN_TAM_MODEL_FALLBACK", "qwen-turbo"),
            max_steps=int(os.environ.get("OPEN_TAM_MAX_STEPS", "15")),
            char_budget=int(os.environ.get("OPEN_TAM_CHAR_BUDGET", "60000")),
        )
