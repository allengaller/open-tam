# M3 护栏 + 巡检 实施计划

> **执行说明（给执行代理）：** 使用 superpowers:executing-plans 逐任务实施本计划。步骤用复选框（`- [ ]`）跟踪，每任务一个提交。

**目标：** 落地 guardrails（命令白名单 + dry-run 预览 + 敏感操作人工确认 + 审计日志）与定时巡检（阈值巡检产出 Markdown 巡检报告），orchestrator 获得 `execute_action` 工具形成"排查→处置"闭环。

**架构：** 新增 `guardrails.py`（策略引擎：白名单校验、参数校验、dry-run、确认器、审计）与 `actions.py`（内置动作注册表：clear_fault 真实生效，restart_service/rollback_release 为模拟动作）；`tools.py` 新增 `EXECUTE_ACTION_SPEC` 与 `GuardrailsBackend`（拦截 execute_action 走护栏，其余透传）；`patrol.py` 对故障注册表逐指标做窗口峰值 vs 阈值巡检；CLI 新增 `action`/`audit`/`patrol` 子命令；`investigate` 的 orchestrator 后端包上 GuardrailsBackend（agent 路径敏感动作自动拒绝，safe 动作可执行）。

**技术栈：** Python 3.12 + uv、typer、pytest（pythonpath=[".", "src"]）

## 全局约束

- 测试隔离：涉及状态/报告/trace 的测试必须 `monkeypatch.setenv("OPEN_TAM_STATE_DIR"/"OPEN_TAM_REPORTS_DIR"/"OPEN_TAM_TRACES_DIR", tmp_path)`
- 运行测试：`UV_NO_EDITABLE=1 uv run pytest -q`（提交前必须全绿，**不用管道**以保留退出码）
- 提交：每任务一个提交，feat/fix 前缀，中文描述
- 巡检报告与审计输出**不用 emoji**；报告状态列用「异常」「正常」文本
- 审计日志路径：`<state_dir>/audit.log`（AuditLogger 默认读 `OPEN_TAM_STATE_DIR`，构造时读取，与 FaultState 一致）

---

### Task 1: 护栏核心引擎 guardrails.py

**Files:**
- Create: `src/open_tam/guardrails.py`
- Test: `tests/test_guardrails.py`

**Interfaces:**
- Consumes: 无（仅标准库）
- Produces:
  - `ActionSpec(name: str, description: str, params: dict[str, str], sensitivity: str, runner: Callable[[dict], str])`（frozen dataclass；params 为参数名→描述，全部必填；sensitivity ∈ {"safe","sensitive"}）
  - `AuditLogger(state_dir: Path | str | None = None)`，方法 `log(actor, action, arguments, decision, reason="", result=None)` 与 `entries() -> list[dict]`；文件 `<state_dir>/audit.log` JSONL
  - `Confirmer` Protocol：`confirm(action: str, arguments: dict) -> bool`；实现 `AutoApprove` / `AutoDeny` / `InteractiveConfirmer`
  - `Guardrails(registry, audit, confirmer=None)`，方法 `run(action: str, arguments: dict, actor: str = "cli", dry_run: bool = False, confirmed: bool = False) -> str`
    - 决策顺序：白名单外→denied；参数缺失/多余→denied；dry_run→预览不执行；sensitive 且未 confirmed→问 confirmer，拒绝则 denied，否则执行
    - 所有决策写审计；denied/预览返回 JSON 字符串（`{"denied": true, "reason": ...}`），执行返回 runner 结果字符串

- [ ] **Step 1: 写失败测试**

```python
# tests/test_guardrails.py
import json
from pathlib import Path

from open_tam.guardrails import (
    ActionSpec,
    AuditLogger,
    AutoApprove,
    AutoDeny,
    Guardrails,
)


def make_guard(tmp_path: Path, confirmer=None) -> tuple[Guardrails, Path]:
    state = tmp_path / "var"
    registry = {
        "noop": ActionSpec(
            name="noop", description="测试动作", params={"target": "目标"},
            sensitivity="safe", runner=lambda a: f"noop {a['target']} done",
        ),
        "risky": ActionSpec(
            name="risky", description="测试敏感动作", params={"target": "目标"},
            sensitivity="sensitive", runner=lambda a: f"risky {a['target']} done",
        ),
    }
    audit = AuditLogger(state)
    return Guardrails(registry, audit, confirmer=confirmer), state / "audit.log"


def read_audit(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_unknown_action_denied_and_audited(tmp_path):
    guard, audit_path = make_guard(tmp_path)
    out = json.loads(guard.run("rm_rf", {}, actor="agent"))
    assert out["denied"] is True
    assert "白名单外" in out["reason"]
    entries = read_audit(audit_path)
    assert entries[-1]["decision"] == "denied"
    assert entries[-1]["action"] == "rm_rf"
    assert entries[-1]["actor"] == "agent"


def test_safe_action_executed_and_audited(tmp_path):
    guard, audit_path = make_guard(tmp_path)
    out = guard.run("noop", {"target": "demo-app"})
    assert out == "noop demo-app done"
    entries = read_audit(audit_path)
    assert entries[-1]["decision"] == "executed"
    assert entries[-1]["result"] == "noop demo-app done"


def test_param_mismatch_denied(tmp_path):
    guard, _ = make_guard(tmp_path)
    missing = json.loads(guard.run("noop", {}))
    extra = json.loads(guard.run("noop", {"target": "x", "evil": "1"}))
    assert "缺少参数" in missing["reason"]
    assert "多余参数" in extra["reason"]


def test_dry_run_previews_without_execution(tmp_path):
    guard, audit_path = make_guard(tmp_path)
    out = guard.run("noop", {"target": "demo-app"}, dry_run=True)
    assert "dry-run" in out and "demo-app" in out
    entries = read_audit(audit_path)
    assert entries[-1]["decision"] == "dry_run"


def test_sensitive_denied_without_confirmation(tmp_path):
    guard, audit_path = make_guard(tmp_path, confirmer=AutoDeny())
    out = json.loads(guard.run("risky", {"target": "demo-app"}))
    assert out["denied"] is True
    assert "未获人工确认" in out["reason"]
    assert read_audit(audit_path)[-1]["decision"] == "denied"


def test_sensitive_executes_when_confirmer_approves(tmp_path):
    guard, _ = make_guard(tmp_path, confirmer=AutoApprove())
    out = guard.run("risky", {"target": "demo-app"})
    assert out == "risky demo-app done"


def test_confirmed_flag_skips_confirmer(tmp_path):
    guard, _ = make_guard(tmp_path, confirmer=AutoDeny())
    out = guard.run("risky", {"target": "demo-app"}, confirmed=True)
    assert out == "risky demo-app done"


def test_audit_entries_reader(tmp_path):
    guard, _ = make_guard(tmp_path)
    guard.run("noop", {"target": "a"})
    guard.run("noop", {"target": "b"})
    audit = AuditLogger(tmp_path / "var")
    assert [e["arguments"]["target"] for e in audit.entries()] == ["a", "b"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_guardrails.py -q`
Expected: FAIL（ModuleNotFoundError: open_tam.guardrails）

- [ ] **Step 3: 最小实现**

```python
# src/open_tam/guardrails.py
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_guardrails.py -q`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add src/open_tam/guardrails.py tests/test_guardrails.py
git commit -m "feat: guardrails 白名单决策引擎（dry-run/敏感确认/审计 JSONL）"
```

---

### Task 2: 内置动作注册表 actions.py

**Files:**
- Create: `src/open_tam/actions.py`
- Test: `tests/test_actions.py`

**Interfaces:**
- Consumes: `ActionSpec`（Task 1）、`FaultState`（现有）
- Produces: `ACTION_REGISTRY: dict[str, ActionSpec]`，含三个动作：
  - `clear_fault(name)` — safe — 真实清除注入故障（`FaultState().clear`），返回 `"fault {name} cleared"`
  - `restart_service(service)` — safe — 模拟，返回含 `[simulated]` 与服务名的字符串
  - `rollback_release(service)` — sensitive — 模拟，返回含 `[simulated]` 与服务名的字符串

- [ ] **Step 1: 写失败测试**

```python
# tests/test_actions.py
from open_tam.actions import ACTION_REGISTRY
from open_tam.faults import FaultState


def test_registry_has_three_actions():
    assert set(ACTION_REGISTRY) == {"clear_fault", "restart_service", "rollback_release"}


def test_sensitivity_classification():
    assert ACTION_REGISTRY["clear_fault"].sensitivity == "safe"
    assert ACTION_REGISTRY["restart_service"].sensitivity == "safe"
    assert ACTION_REGISTRY["rollback_release"].sensitivity == "sensitive"


def test_clear_fault_runner_clears_state(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    FaultState().activate("cpu_spike", duration_minutes=30)
    out = ACTION_REGISTRY["clear_fault"].runner({"name": "cpu_spike"})
    assert out == "fault cpu_spike cleared"
    assert FaultState().is_active("cpu_spike") is False


def test_simulated_actions_return_message():
    out = ACTION_REGISTRY["restart_service"].runner({"service": "demo-app"})
    assert "simulated" in out.lower() and "demo-app" in out
    out2 = ACTION_REGISTRY["rollback_release"].runner({"service": "demo-app"})
    assert "simulated" in out2.lower() and "demo-app" in out2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_actions.py -q`
Expected: FAIL（ModuleNotFoundError: open_tam.actions）

- [ ] **Step 3: 最小实现**

```python
# src/open_tam/actions.py
from __future__ import annotations

from open_tam.faults import FaultState
from open_tam.guardrails import ActionSpec


def _clear_fault(args: dict) -> str:
    FaultState().clear(args["name"])
    return f"fault {args['name']} cleared"


def _restart_service(args: dict) -> str:
    return f"[simulated] service {args['service']} restarted（mock 世界无真实进程）"


def _rollback_release(args: dict) -> str:
    return f"[simulated] service {args['service']} rolled back to previous release（mock 世界无真实发布）"


ACTION_REGISTRY: dict[str, ActionSpec] = {
    "clear_fault": ActionSpec(
        name="clear_fault",
        description="清除注入的故障模式（修复动作，mock 世界真实生效）",
        params={"name": "故障模式名，如 cpu_spike"},
        sensitivity="safe",
        runner=_clear_fault,
    ),
    "restart_service": ActionSpec(
        name="restart_service",
        description="重启服务实例（模拟动作）",
        params={"service": "服务名，如 demo-app"},
        sensitivity="safe",
        runner=_restart_service,
    ),
    "rollback_release": ActionSpec(
        name="rollback_release",
        description="回滚服务最近一次发布（模拟动作，敏感操作需人工确认）",
        params={"service": "服务名，如 demo-app"},
        sensitivity="sensitive",
        runner=_rollback_release,
    ),
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_actions.py -q`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/open_tam/actions.py tests/test_actions.py
git commit -m "feat: 内置动作注册表（clear_fault 真实生效 + 两个模拟动作）"
```

---

### Task 3: CLI action/audit 子命令

**Files:**
- Modify: `src/open_tam/cli.py`（在 trace_app 附近新增 `action_app`、`audit_app` 两个子 typer 并注册）
- Test: `tests/test_action_cli.py`

**Interfaces:**
- Consumes: `Guardrails`/`AuditLogger`/`AutoApprove`/`InteractiveConfirmer`（Task 1）、`ACTION_REGISTRY`（Task 2）、`Settings.load()`
- Produces:
  - `open-tam action list` — 打印注册表（名称 [敏感级] 描述 参数）
  - `open-tam action run ACTION [--arg k=v ...] [--dry-run] [--yes]` — `--yes` 用 AutoApprove 并传 confirmed=True；否则 InteractiveConfirmer；actor="cli"
  - `open-tam audit show [--limit N]` — 打印最近 N 条审计 JSONL（默认 20）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_action_cli.py
import json

from typer.testing import CliRunner

from open_tam.cli import app
from open_tam.faults import FaultState

runner = CliRunner()


def read_last_audit(tmp_path) -> dict:
    lines = (tmp_path / "var" / "audit.log").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def test_action_list_lists_registry():
    result = runner.invoke(app, ["action", "list"])
    assert result.exit_code == 0
    for name in ("clear_fault", "restart_service", "rollback_release"):
        assert name in result.output


def test_action_run_unknown_denied_and_audited(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    result = runner.invoke(app, ["action", "run", "deploy_to_prod"])
    assert result.exit_code == 0
    assert "白名单外" in result.output
    assert read_last_audit(tmp_path)["decision"] == "denied"
    assert read_last_audit(tmp_path)["action"] == "deploy_to_prod"


def test_action_run_dry_run_no_effect(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    FaultState().activate("cpu_spike", duration_minutes=30)
    result = runner.invoke(
        app, ["action", "run", "clear_fault", "--arg", "name=cpu_spike", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "dry-run" in result.output
    assert FaultState().is_active("cpu_spike") is True


def test_action_run_safe_executes(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    FaultState().activate("cpu_spike", duration_minutes=30)
    result = runner.invoke(app, ["action", "run", "clear_fault", "--arg", "name=cpu_spike"])
    assert result.exit_code == 0
    assert "cleared" in result.output
    assert FaultState().is_active("cpu_spike") is False


def test_action_run_sensitive_interactive_deny(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    result = runner.invoke(
        app, ["action", "run", "rollback_release", "--arg", "service=demo-app"], input="n\n"
    )
    assert result.exit_code == 0
    assert "未获人工确认" in result.output
    assert read_last_audit(tmp_path)["decision"] == "denied"


def test_action_run_sensitive_yes_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    result = runner.invoke(
        app, ["action", "run", "rollback_release", "--arg", "service=demo-app", "--yes"]
    )
    assert result.exit_code == 0
    assert "simulated" in result.output
    assert read_last_audit(tmp_path)["decision"] == "executed"


def test_audit_show_prints_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    runner.invoke(app, ["action", "run", "clear_fault", "--arg", "name=cpu_spike"])
    result = runner.invoke(app, ["audit", "show"])
    assert result.exit_code == 0
    assert "executed" in result.output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_action_cli.py -q`
Expected: FAIL（CliRunner 退出码非 0：unknown command action）

- [ ] **Step 3: 实现**

在 `src/open_tam/cli.py` 的 `trace_app` 定义之前插入：

```python
action_app = typer.Typer(help="运维动作（白名单 + dry-run + 确认 + 审计）")
audit_app = typer.Typer(help="审计日志查看")
app.add_typer(action_app, name="action")
app.add_typer(audit_app, name="audit")


@action_app.command("list")
def action_list() -> None:
    from open_tam.actions import ACTION_REGISTRY

    for spec in ACTION_REGISTRY.values():
        params = ", ".join(spec.params) or "无"
        typer.echo(f"{spec.name} [{spec.sensitivity}] {spec.description} 参数: {params}")


@action_app.command("run")
def action_run(
    action: str = typer.Argument(..., help="动作名，见 open-tam action list"),
    args: list[str] = typer.Option(None, "--arg", help="动作参数，格式 k=v，可多次"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预览，不执行"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过敏感操作人工确认"),
) -> None:
    from open_tam.actions import ACTION_REGISTRY
    from open_tam.config import Settings
    from open_tam.guardrails import AuditLogger, AutoApprove, Guardrails, InteractiveConfirmer

    settings = Settings.load()
    arguments: dict[str, str] = {}
    for pair in args or []:
        if "=" not in pair:
            typer.echo(f"无效参数（需 k=v）: {pair}", err=True)
            raise typer.Exit(1)
        key, value = pair.split("=", 1)
        arguments[key] = value
    confirmer = AutoApprove() if yes else InteractiveConfirmer()
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(settings.state_dir), confirmer=confirmer)
    typer.echo(guard.run(action, arguments, actor="cli", dry_run=dry_run, confirmed=yes))


@audit_app.command("show")
def audit_show(limit: int = typer.Option(20, help="显示最近 N 条")) -> None:
    from open_tam.config import Settings
    from open_tam.guardrails import AuditLogger

    settings = Settings.load()
    entries = AuditLogger(settings.state_dir).entries()
    for entry in entries[-limit:]:
        typer.echo(json.dumps(entry, ensure_ascii=False))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_action_cli.py -q`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add src/open_tam/cli.py tests/test_action_cli.py
git commit -m "feat: CLI action run/list 与 audit show（--dry-run/--yes/交互确认）"
```

---

### Task 4: execute_action 工具与 GuardrailsBackend

**Files:**
- Modify: `src/open_tam/orchestrator/tools.py`（新增 EXECUTE_ACTION_SPEC、GuardrailsBackend；ORCHESTRATOR_TOOLS 追加）
- Modify: `src/open_tam/orchestrator/agents.py`（ORCHESTRATOR_PROMPT 增补 execute_action 策略）
- Test: `tests/test_guardrails_backend.py`

**Interfaces:**
- Consumes: `Guardrails`（Task 1）、`Backend` Protocol（现有）
- Produces:
  - `EXECUTE_ACTION_SPEC: dict`（工具 schema：`action` 必填，`arguments` 可选 object）
  - `GuardrailsBackend(inner: Backend, guardrails: Guardrails, actor: str = "agent")`：`execute("execute_action", args)` → `guardrails.run(args["action"], args.get("arguments") or {}, actor=actor)`；其余工具透传 inner
  - `ORCHESTRATOR_TOOLS = [ASK_METRIC_AGENT_SPEC, ASK_LOG_AGENT_SPEC, EXECUTE_ACTION_SPEC]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_guardrails_backend.py
import json

from open_tam.actions import ACTION_REGISTRY
from open_tam.guardrails import AuditLogger, AutoDeny, Guardrails
from open_tam.orchestrator.agents import ORCHESTRATOR_PROMPT
from open_tam.orchestrator.tools import ORCHESTRATOR_TOOLS, GuardrailsBackend


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        return "ok"


def test_orchestrator_tools_include_execute_action():
    assert [t["name"] for t in ORCHESTRATOR_TOOLS] == [
        "ask_metric_agent", "ask_log_agent", "execute_action",
    ]


def test_prompt_mentions_action_policy():
    assert "execute_action" in ORCHESTRATOR_PROMPT
    assert "敏感" in ORCHESTRATOR_PROMPT


def test_guardrails_backend_routes_execute_action(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path / "var"), confirmer=AutoDeny())
    backend = GuardrailsBackend(RecordingBackend(), guard, actor="agent")
    out = json.loads(backend.execute("execute_action", {
        "action": "rollback_release", "arguments": {"service": "demo-app"},
    }))
    assert out["denied"] is True
    assert (tmp_path / "var" / "audit.log").exists()


def test_guardrails_backend_executes_safe_action(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path / "var"), confirmer=AutoDeny())
    backend = GuardrailsBackend(RecordingBackend(), guard, actor="agent")
    out = backend.execute("execute_action", {
        "action": "clear_fault", "arguments": {"name": "cpu_spike"},
    })
    assert "cleared" in out


def test_guardrails_backend_passes_through_other_tools(tmp_path):
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path / "var"), confirmer=AutoDeny())
    inner = RecordingBackend()
    backend = GuardrailsBackend(inner, guard)
    assert backend.execute("query_metrics", {"metric": "cpu_usage"}) == "ok"
    assert inner.calls == [("query_metrics", {"metric": "cpu_usage"})]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_guardrails_backend.py -q`
Expected: FAIL（ImportError: EXECUTE_ACTION_SPEC）

- [ ] **Step 3: 实现**

`src/open_tam/orchestrator/tools.py` 顶部追加导入（放现有 `from open_tam.faults import FaultState` 之后）：

```python
from open_tam.guardrails import Guardrails
```

文件末尾（ORCHESTRATOR_TOOLS 定义处）替换为：

```python
EXECUTE_ACTION_SPEC = {
    "name": "execute_action",
    "description": "执行白名单内的运维动作（如 clear_fault 修复故障）。白名单外动作会被拒绝；敏感动作在无人确认场景会被拒绝并写入审计。",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "动作名，如 clear_fault"},
            "arguments": {"type": "object", "description": "动作参数，如 {\"name\": \"cpu_spike\"}"},
        },
        "required": ["action"],
    },
}

ORCHESTRATOR_TOOLS: list[dict] = [ASK_METRIC_AGENT_SPEC, ASK_LOG_AGENT_SPEC, EXECUTE_ACTION_SPEC]


class GuardrailsBackend:
    """execute_action 走护栏决策，其余工具透传内层后端。"""

    def __init__(self, inner: Backend, guardrails: Guardrails, actor: str = "agent") -> None:
        self.inner = inner
        self.guardrails = guardrails
        self.actor = actor

    def execute(self, name: str, args: dict) -> str:
        if name == "execute_action":
            return self.guardrails.run(
                args["action"], args.get("arguments") or {}, actor=self.actor
            )
        return self.inner.execute(name, args)
```

`src/open_tam/orchestrator/agents.py` 的 ORCHESTRATOR_PROMPT 在日志子 Agent 条目后追加一行（保持原 JSON 契约不变）：

```python
ORCHESTRATOR_PROMPT = """你是资深 SRE 运维专家（orchestrator）。收到告警后，通过两个子 Agent 排查：
- ask_metric_agent(question)：向指标分析子 Agent 提问，确认异常是否存在、异常窗口与幅度；
- ask_log_agent(question)：向日志检索子 Agent 提问，获取异常现场的日志证据。
先向指标子 Agent 确认异常，需要现场证据时再询问日志子 Agent；证据足够后定位根因。
根因确认后可用 execute_action(action, arguments) 执行白名单内修复动作：仅限 safe 级动作（如 clear_fault）；
敏感动作会被拒绝，应写入 actions 建议人工确认后执行。
最终**只输出一个 JSON 对象**（可包在 ```json 代码块中）：
{"root_cause": "<根因；无法定位则为 null>", "evidence": ["<证据>"], "actions": ["<建议动作>"], "confidence": "high|medium|low", "excluded": ["<已排除项>"]}
evidence 必须引用子 Agent 返回的关键证据原文。不要输出 JSON 以外的解释性文字。"""
```

- [ ] **Step 4: 跑全量测试确认通过**

Run: `UV_NO_EDITABLE=1 uv run pytest -q`
Expected: 全绿（既有 investigate fake 路径不受影响）

- [ ] **Step 5: 提交**

```bash
git add src/open_tam/orchestrator/tools.py src/open_tam/orchestrator/agents.py tests/test_guardrails_backend.py
git commit -m "feat: orchestrator 接入 execute_action 工具与 GuardrailsBackend 委托路由"
```

---

### Task 5: 巡检 patrol.py

**Files:**
- Create: `src/open_tam/patrol.py`
- Test: `tests/test_patrol.py`

**Interfaces:**
- Consumes: `FAULT_MODES`（现有）、`InlineBackend`/`Backend`（现有）
- Produces:
  - `run_patrol(reports_dir: Path | str, backend: Backend | None = None, now: datetime | None = None, window_minutes: int = 10) -> Path`
    - 对 FAULT_MODES 逐项查指标（inline 默认），取窗口峰值与 `baseline_high` 比较：峰值 > 阈值 → 异常
    - 报告写入 `<reports_dir>/patrol-<YYYYmmdd-HHMMSS>.md` 并返回路径
    - 报告结构：`# 巡检报告` / 巡检时间、检查窗口、`检查项：N，异常：M` / 逐项表格（故障模式|服务|指标|窗口峰值|阈值|状态）/ 异常项 `## 异常跟进` 提示 `open-tam investigate`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_patrol.py
from datetime import datetime

from open_tam.faults import FaultState
from open_tam.patrol import run_patrol


def test_patrol_clean_state_all_normal(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    now = datetime.now().replace(second=0, microsecond=0)
    path = run_patrol(tmp_path / "reports", now=now)
    text = path.read_text(encoding="utf-8")
    assert "异常：0" in text
    for mode in ("cpu_spike", "slow_query", "oom", "connection_pool_exhausted"):
        assert mode in text


def test_patrol_flags_injected_fault(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    FaultState().activate("cpu_spike", duration_minutes=30)
    now = datetime.now().replace(second=0, microsecond=0)
    path = run_patrol(tmp_path / "reports", now=now)
    text = path.read_text(encoding="utf-8")
    assert "异常：1" in text
    assert "cpu_spike" in text
    assert "open-tam investigate" in text


def test_patrol_report_filename_format(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    path = run_patrol(tmp_path / "reports", now=datetime(2026, 8, 31, 12, 0, 0))
    assert path.name == "patrol-20260831-120000.md"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_patrol.py -q`
Expected: FAIL（ModuleNotFoundError: open_tam.patrol）

- [ ] **Step 3: 最小实现**

```python
# src/open_tam/patrol.py
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from open_tam.faults import FAULT_MODES
from open_tam.orchestrator.tools import Backend, InlineBackend


def run_patrol(
    reports_dir: Path | str,
    backend: Backend | None = None,
    now: datetime | None = None,
    window_minutes: int = 10,
) -> Path:
    """对所有注册故障模式的目标指标做窗口峰值 vs 阈值巡检，产出 Markdown 巡检报告。"""
    backend = backend or InlineBackend()
    now = now or datetime.now().replace(second=0, microsecond=0)
    start = now - timedelta(minutes=window_minutes)

    checks: list[dict] = []
    for mode in FAULT_MODES.values():
        raw = backend.execute("query_metrics", {
            "metric": mode.metric, "service": mode.service,
            "start": start.isoformat(), "end": now.isoformat(),
        })
        points = json.loads(raw)
        peak = max((p["value"] for p in points), default=0.0)
        status = "anomaly" if peak > mode.baseline_high else "normal"
        checks.append({
            "fault": mode.name, "service": mode.service, "metric": mode.metric,
            "peak": round(peak, 1), "threshold": mode.baseline_high, "status": status,
        })

    anomalies = [c for c in checks if c["status"] == "anomaly"]
    lines = [
        "# 巡检报告",
        "",
        f"- 巡检时间：{now.isoformat(timespec='seconds')}",
        f"- 检查窗口：最近 {window_minutes} 分钟",
        f"- 检查项：{len(checks)}，异常：{len(anomalies)}",
        "",
        "| 故障模式 | 服务 | 指标 | 窗口峰值 | 阈值 | 状态 |",
        "|---|---|---|---|---|---|",
    ]
    for c in checks:
        status_cn = "异常" if c["status"] == "anomaly" else "正常"
        lines.append(
            f"| {c['fault']} | {c['service']} | {c['metric']} | {c['peak']} | {c['threshold']} | {status_cn} |"
        )
    if anomalies:
        lines += ["", "## 异常跟进", ""]
        for c in anomalies:
            mode = FAULT_MODES[c["fault"]]
            lines.append(
                f"- **{c['fault']}**（{c['service']}）：{mode.anomaly_desc}；"
                f"建议运行 `open-tam investigate` 深入排查"
            )

    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"patrol-{now.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: 跑测试确认通过**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_patrol.py -q`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/open_tam/patrol.py tests/test_patrol.py
git commit -m "feat: 阈值巡检 run_patrol（故障注册表逐指标检查 + Markdown 巡检报告）"
```

---

### Task 6: CLI patrol 子命令

**Files:**
- Modify: `src/open_tam/cli.py`（新增 `patrol_app` 子 typer：`patrol run`、`patrol watch`）
- Test: `tests/test_patrol_cli.py`

**Interfaces:**
- Consumes: `run_patrol`（Task 5）、`Settings.load()`、InlineBackend/McpStdioBackend
- Produces:
  - `open-tam patrol run [--transport inline|mcp]` — 巡检一次，打印报告路径
  - `open-tam patrol watch [--every-min N] [--max-runs M]` — 循环巡检（M=0 不限，Ctrl-C 退出）；`--every-min 0 --max-runs 2` 用于测试

- [ ] **Step 1: 写失败测试**

```python
# tests/test_patrol_cli.py
from typer.testing import CliRunner

from open_tam.cli import app

runner = CliRunner()


def test_patrol_run_creates_report(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    result = runner.invoke(app, ["patrol", "run"])
    assert result.exit_code == 0
    assert "patrol report" in result.output
    assert list((tmp_path / "reports").glob("patrol-*.md"))


def test_patrol_watch_runs_n_times(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
    result = runner.invoke(app, ["patrol", "watch", "--every-min", "0", "--max-runs", "2"])
    assert result.exit_code == 0
    assert result.output.count("patrol report") == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_patrol_cli.py -q`
Expected: FAIL（unknown command patrol）

- [ ] **Step 3: 实现**

在 `src/open_tam/cli.py` 的 `action_app`/`audit_app` 注册之后追加：

```python
patrol_app = typer.Typer(help="定时巡检")
app.add_typer(patrol_app, name="patrol")


@patrol_app.command("run")
def patrol_run(transport: str = typer.Option("inline", help="inline 或 mcp")) -> None:
    from open_tam.config import Settings
    from open_tam.patrol import run_patrol

    settings = Settings.load()
    backend = InlineBackend() if transport == "inline" else McpStdioBackend()
    path = run_patrol(settings.reports_dir, backend=backend)
    typer.echo(f"patrol report: {path}")


@patrol_app.command("watch")
def patrol_watch(
    every_min: int = typer.Option(5, help="巡检间隔（分钟）"),
    max_runs: int = typer.Option(0, help="最大巡检次数，0 表示不限（Ctrl-C 退出）"),
) -> None:
    import time

    from open_tam.config import Settings
    from open_tam.patrol import run_patrol

    settings = Settings.load()
    runs = 0
    while max_runs <= 0 or runs < max_runs:
        path = run_patrol(settings.reports_dir)
        typer.echo(f"patrol report: {path}")
        runs += 1
        if max_runs > 0 and runs >= max_runs:
            break
        time.sleep(every_min * 60)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_patrol_cli.py -q`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add src/open_tam/cli.py tests/test_patrol_cli.py
git commit -m "feat: CLI patrol run/watch 定时巡检入口"
```

---

### Task 7: investigate 接线护栏 + 集成测试 + 文档

**Files:**
- Modify: `src/open_tam/cli.py`（investigate：后端包 GuardrailsBackend，AutoDeny 确认器）
- Test: `tests/test_investigate_guardrails.py`
- Modify: `README.md`、`docs/mvp-plan.md`

**Interfaces:**
- Consumes: Task 1–4 全部产物、`ReActLoop`/`FakeChatModel`/`AgentBackend`（现有）
- Produces: investigate 的 orchestrator 可调用 `execute_action`（agent 路径 AutoDeny：safe 执行、sensitive 拒绝，全部入审计）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_investigate_guardrails.py
from open_tam.actions import ACTION_REGISTRY
from open_tam.faults import FaultState
from open_tam.guardrails import AuditLogger, AutoDeny, Guardrails
from open_tam.models import AlertEvent
from open_tam.orchestrator.agents import ORCHESTRATOR_PROMPT, AgentBackend
from open_tam.orchestrator.loop import FakeChatModel, ModelReply, ReActLoop, ToolCall
from open_tam.orchestrator.tools import ORCHESTRATOR_TOOLS, GuardrailsBackend


def make_alert() -> AlertEvent:
    return AlertEvent(alert_name="CPU飙高", service="demo-app", metric="cpu_usage",
                      threshold=85, current_value=92)


def make_loop(tmp_path, replies) -> ReActLoop:
    guard = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path / "var"), confirmer=AutoDeny())
    backend = GuardrailsBackend(AgentBackend({}), guard, actor="agent")
    return ReActLoop(model=FakeChatModel(replies), backend=backend,
                     system_prompt=ORCHESTRATOR_PROMPT, tools=ORCHESTRATOR_TOOLS)


def test_agent_executes_safe_action_and_audits(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    FaultState().activate("cpu_spike", duration_minutes=30)
    replies = [
        ModelReply(content="根因已确认，执行修复", tool_calls=[ToolCall(
            id="t1", name="execute_action",
            arguments={"action": "clear_fault", "arguments": {"name": "cpu_spike"}})]),
        ModelReply(content='```json\n{"root_cause": "CPU 飙升（已修复）", "evidence": ["e1"], '
                           '"actions": ["观察恢复情况"], "confidence": "high"}\n```'),
    ]
    result = make_loop(tmp_path, replies).run(make_alert())
    assert "cleared" in result.steps[0].observation
    assert FaultState().is_active("cpu_spike") is False
    audit = AuditLogger(tmp_path / "var").entries()
    assert audit[0]["actor"] == "agent"
    assert audit[0]["decision"] == "executed"


def test_agent_sensitive_action_denied_and_loop_continues(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "var"))
    replies = [
        ModelReply(content="尝试回滚", tool_calls=[ToolCall(
            id="t1", name="execute_action",
            arguments={"action": "rollback_release", "arguments": {"service": "demo-app"}})]),
        ModelReply(content='```json\n{"root_cause": "根因X", "evidence": ["e1"], '
                           '"actions": ["人工确认后回滚"], "confidence": "medium"}\n```'),
    ]
    result = make_loop(tmp_path, replies).run(make_alert())
    assert "未获人工确认" in result.steps[0].observation
    assert result.root_cause == "根因X"
    audit = AuditLogger(tmp_path / "var").entries()
    assert audit[0]["decision"] == "denied"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `UV_NO_EDITABLE=1 uv run pytest tests/test_investigate_guardrails.py -q`
Expected: FAIL 或 PASS？此测试只依赖 Task 1–4 的产物，逻辑上应已通过——它验证的是接线组合的正确性。若通过则视为接线回归测试；CLI investigate 的接线改动用 Step 4 全量测试与验收命令验证。

- [ ] **Step 3: 修改 investigate 接线**

`src/open_tam/cli.py` investigate 中 `backend = AgentBackend({...})` 之后、`loop = ReActLoop(...)` 之前：

```python
    from open_tam.actions import ACTION_REGISTRY
    from open_tam.guardrails import AuditLogger, AutoDeny, Guardrails
    from open_tam.orchestrator.tools import GuardrailsBackend

    guardrails = Guardrails(ACTION_REGISTRY, AuditLogger(settings.state_dir),
                            confirmer=AutoDeny())
    backend = GuardrailsBackend(backend, guardrails, actor="agent")
```

（imports 移到函数顶部现有 import 块更整洁——执行时统一放 investigate 函数内 import 区。）

- [ ] **Step 4: 全量测试**

Run: `UV_NO_EDITABLE=1 uv run pytest -q`
Expected: 全绿

- [ ] **Step 5: 更新文档**

`docs/mvp-plan.md` M3 区块替换为：

```markdown
## M3 护栏 + 巡检

- [x] `guardrails`：命令白名单 + dry-run 预览 + 敏感操作人工确认
- [x] 审计日志 `audit.log`
- [x] 定时巡检任务（阈值巡检，输出巡检报告）
- [x] orchestrator 接入 `execute_action`（agent 路径 safe 动作可执行、敏感动作自动拒绝）
- **验收**：白名单外命令被拦截且审计可查；巡检报告按时生成 ✅（2026-08-31，见验收记录）
```

`README.md` 命令表追加（保留既有表格风格）：

```markdown
| `open-tam action list` | 查看白名单动作注册表 |
| `open-tam action run clear_fault --arg name=cpu_spike` | 执行白名单动作（safe 直接执行） |
| `open-tam action run rollback_release --arg service=demo-app` | 敏感动作：交互确认后执行 |
| `open-tam action run rollback_release --arg service=demo-app --yes` | 敏感动作：跳过确认 |
| `open-tam action run any --dry-run` | dry-run 预览，不实际执行 |
| `open-tam audit show` | 查看审计日志（JSONL） |
| `open-tam patrol run` | 立即巡检一次，产出巡检报告 |
| `open-tam patrol watch --every-min 5` | 每 5 分钟巡检一次（Ctrl-C 退出） |
```

- [ ] **Step 6: 提交**

```bash
git add src/open_tam/cli.py tests/test_investigate_guardrails.py README.md docs/mvp-plan.md
git commit -m "feat: investigate 接入护栏后端；M3 文档与命令表更新"
```

---

### Task 8: M3 验收（手动演示）

**Files:** 无代码改动（验收产物为命令输出）

**Interfaces:** 消费全部前序任务

- [ ] **Step 1: 白名单拦截 + 审计可查**

```bash
UV_NO_EDITABLE=1 uv run open-tam action run deploy_to_prod
# 预期：{"denied": true, "reason": "白名单外动作: deploy_to_prod"}
UV_NO_EDITABLE=1 uv run open-tam audit show
# 预期：最后一条 decision=denied, action=deploy_to_prod
```

- [ ] **Step 2: dry-run 与敏感确认**

```bash
UV_NO_EDITABLE=1 uv run open-tam action run clear_fault --arg name=cpu_spike --dry-run
# 预期：[dry-run] 将执行 clear_fault（safe）参数 {'name': 'cpu_spike'}；未实际执行
UV_NO_EDITABLE=1 uv run open-tam action run rollback_release --arg service=demo-app --yes
# 预期：[simulated] ... rolled back ...
```

- [ ] **Step 3: 巡检报告**

```bash
UV_NO_EDITABLE=1 uv run open-tam fault inject cpu_spike
UV_NO_EDITABLE=1 uv run open-tam patrol run
# 预期：patrol report: reports/patrol-*.md，报告内 cpu_spike 状态异常且含异常跟进
UV_NO_EDITABLE=1 uv run open-tam fault clear cpu_spike
```

- [ ] **Step 4: fake 路径 investigate 回归**

```bash
UV_NO_EDITABLE=1 uv run open-tam investigate --alert-file alerts/demo.json --fake
# 预期：report saved + trace saved + 根因输出，全流程无异常
```

- [ ] **Step 5: 全量测试 + 收尾提交（如验收过程中有文档微调）**

Run: `UV_NO_EDITABLE=1 uv run pytest -q`
Expected: 全绿

- [ ] **Step 6: 在 mvp-plan.md M3 验收行填写实际验收证据，提交**

```bash
git add docs/mvp-plan.md
git commit -m "docs: M3 验收记录（白名单拦截/审计/巡检报告/fake 回归）"
```
