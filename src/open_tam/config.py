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
    model_timeout: float
    max_steps: int
    char_budget: int
    metrics_backend: str
    logs_backend: str
    aliyun_region: str
    aliyun_access_key_id: str
    aliyun_access_key_secret: str
    aliyun_sls_project: str
    aliyun_sls_logstore: str
    dedup_window_seconds: int
    webhook_secret: str
    skills_dir: Path

    @classmethod
    def load(cls) -> Settings:
        base = Path(os.environ.get("OPEN_TAM_BASE_DIR", "."))
        return cls(
            state_dir=Path(os.environ.get("OPEN_TAM_STATE_DIR", base / "var")),
            reports_dir=Path(os.environ.get("OPEN_TAM_REPORTS_DIR", base / "reports")),
            inbox_dir=Path(os.environ.get("OPEN_TAM_INBOX_DIR", base / "var" / "inbox")),
            traces_dir=Path(os.environ.get("OPEN_TAM_TRACES_DIR", base / "traces")),
            model_primary=os.environ.get("OPEN_TAM_MODEL_PRIMARY", "qwen-plus"),
            model_fallback=os.environ.get("OPEN_TAM_MODEL_FALLBACK", "qwen-turbo"),
            model_timeout=float(os.environ.get("OPEN_TAM_MODEL_TIMEOUT", "120")),
            max_steps=int(os.environ.get("OPEN_TAM_MAX_STEPS", "15")),
            char_budget=int(os.environ.get("OPEN_TAM_CHAR_BUDGET", "60000")),
            metrics_backend=os.environ.get("OPEN_TAM_METRICS_BACKEND", "mock"),
            logs_backend=os.environ.get("OPEN_TAM_LOGS_BACKEND", "mock"),
            aliyun_region=os.environ.get("OPEN_TAM_ALIYUN_REGION", "cn-hangzhou"),
            aliyun_access_key_id=os.environ.get("OPEN_TAM_ALIYUN_ACCESS_KEY_ID", os.environ.get("ALIYUN_ACCESS_KEY_ID", "")),
            aliyun_access_key_secret=os.environ.get("OPEN_TAM_ALIYUN_ACCESS_KEY_SECRET", os.environ.get("ALIYUN_ACCESS_KEY_SECRET", "")),
            aliyun_sls_project=os.environ.get("OPEN_TAM_ALIYUN_SLS_PROJECT", ""),
            aliyun_sls_logstore=os.environ.get("OPEN_TAM_ALIYUN_SLS_LOGSTORE", ""),
            dedup_window_seconds=int(os.environ.get("OPEN_TAM_DEDUP_WINDOW_SECONDS", "300")),
            webhook_secret=os.environ.get("OPEN_TAM_WEBHOOK_SECRET", ""),
            skills_dir=Path(os.environ.get("OPEN_TAM_SKILLS_DIR", base / "skills")),
        )
