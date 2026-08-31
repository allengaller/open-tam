from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class ActionSpec:
    """白名单内一个可执行动作的定义：签名 + 敏感级 + 执行器。"""

    name: str
    description: str
    params: dict[str, str]  # 参数名 -> 描述，全部必填
    sensitivity: str  # "safe" | "sensitive"
    runner: Callable[[dict], str]


class AuditLogger:
    """运维动作审计：每个决策（拒绝/预览/执行）逐条追加 JSONL。"""

    def __init__(self, state_dir: Path | str | None = None) -> None:
        # 构造时读取环境变量，保证测试可在运行期隔离（与 FaultState 一致）
        base = Path(state_dir) if state_dir else Path(os.environ.get("OPEN_TAM_STATE_DIR", "var"))
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "audit.log"

    def log(self, actor: str, action: str, arguments: dict, decision: str,
            reason: str = "", result: str | None = None) -> None:
        entry = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "actor": actor,
            "action": action,
            "arguments": arguments,
            "decision": decision,  # denied | dry_run | executed
            "reason": reason,
        }
        if result is not None:
            entry["result"] = result
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class Confirmer(Protocol):
    def confirm(self, action: str, arguments: dict) -> bool: ...


class AutoApprove:
    def confirm(self, action: str, arguments: dict) -> bool:
        return True


class AutoDeny:
    def confirm(self, action: str, arguments: dict) -> bool:
        return False


class InteractiveConfirmer:
    def confirm(self, action: str, arguments: dict) -> bool:
        import typer

        return typer.confirm(f"敏感操作 {action} {arguments}，确认执行？")


class Guardrails:
    """命令白名单 + dry-run 预览 + 敏感操作人工确认 + 审计日志。"""

    def __init__(self, registry: dict[str, ActionSpec], audit: AuditLogger,
                 confirmer: Confirmer | None = None) -> None:
        self.registry = registry
        self.audit = audit
        self.confirmer = confirmer or AutoDeny()

    def run(self, action: str, arguments: dict, actor: str = "cli",
            dry_run: bool = False, confirmed: bool = False) -> str:
        spec = self.registry.get(action)
        if spec is None:
            reason = f"白名单外动作: {action}"
            self.audit.log(actor, action, arguments, "denied", reason=reason)
            return json.dumps({"denied": True, "reason": reason}, ensure_ascii=False)

        missing = sorted(set(spec.params) - set(arguments))
        extra = sorted(set(arguments) - set(spec.params))
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"缺少参数: {', '.join(missing)}")
            if extra:
                parts.append(f"多余参数: {', '.join(extra)}")
            reason = "；".join(parts)
            self.audit.log(actor, action, arguments, "denied", reason=reason)
            return json.dumps({"denied": True, "reason": reason}, ensure_ascii=False)

        if dry_run:
            self.audit.log(actor, action, arguments, "dry_run", reason="预览模式")
            return f"[dry-run] 将执行 {action}（{spec.sensitivity}）参数 {arguments}；未实际执行"

        if spec.sensitivity == "sensitive" and not confirmed:
            if not self.confirmer.confirm(action, arguments):
                reason = "敏感操作未获人工确认，已拒绝执行"
                self.audit.log(actor, action, arguments, "denied", reason=reason)
                return json.dumps({"denied": True, "reason": reason}, ensure_ascii=False)

        result = spec.runner(arguments)
        self.audit.log(actor, action, arguments, "executed", result=result)
        return result
