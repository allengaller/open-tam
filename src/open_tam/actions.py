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
