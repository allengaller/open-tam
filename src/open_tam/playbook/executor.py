"""Playbook executor with guardrails integration."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from open_tam.guardrails import Guardrails
from open_tam.playbook.models import (
    OnFailure,
    Playbook,
    PlaybookResult,
    Sensitivity,
    StepResult,
    StepStatus,
)


class PlaybookExecutor:
    """Execute playbook steps with guardrails and optional confirmation."""

    def __init__(
        self,
        guardrails: Guardrails,
        confirmer: Callable[[str, dict], bool] | None = None,
    ) -> None:
        self.guardrails = guardrails
        self.confirmer = confirmer

    def execute(
        self,
        playbook: Playbook,
        context: dict[str, Any],
        dry_run: bool = False,
    ) -> PlaybookResult:
        """Execute all steps in the playbook."""
        result = PlaybookResult(playbook_id=playbook.id)
        executed_steps: list[StepResult] = []

        for step in playbook.steps:
            step_result = self._execute_step(step, context, dry_run)
            result.steps.append(step_result)

            if step_result.status == StepStatus.DONE:
                executed_steps.append(step_result)
            elif step_result.status in (StepStatus.FAILED, StepStatus.DENIED):
                if step.on_failure == OnFailure.ABORT:
                    break
                elif step.on_failure == OnFailure.ROLLBACK:
                    self._rollback(executed_steps, context)
                    for s in executed_steps:
                        s.status = StepStatus.ROLLED_BACK
                    break

        result.completed_at = datetime.now()
        return result

    def _execute_step(
        self,
        step: PlaybookStep,
        context: dict[str, Any],
        dry_run: bool,
    ) -> StepResult:
        """Execute a single step."""
        params = self._render_params(step.params, context)

        if step.sensitivity == Sensitivity.SENSITIVE and not step.auto_execute:
            if self.confirmer:
                if not self.confirmer(step.action, params):
                    return StepResult(step=step, status=StepStatus.DENIED, error="User denied")
            else:
                return StepResult(step=step, status=StepStatus.DENIED, error="No confirter configured")

        try:
            output = self.guardrails.run(
                step.action, params, actor="playbook", dry_run=dry_run, confirmed=True
            )
            if "denied" in output.lower() or "error" in output.lower():
                return StepResult(step=step, status=StepStatus.FAILED, error=output)
            return StepResult(step=step, status=StepStatus.DONE, result=output)
        except Exception as e:
            return StepResult(step=step, status=StepStatus.FAILED, error=str(e))

    def _render_params(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Render template variables in params."""
        rendered = {}
        for key, value in params.items():
            if isinstance(value, str):
                for ctx_key, ctx_value in context.items():
                    value = value.replace(f"{{{{ {ctx_key} }}}}", str(ctx_value))
            rendered[key] = value
        return rendered

    def _rollback(self, steps: list[StepResult], context: dict[str, Any]) -> None:
        """Rollback executed steps in reverse order."""
        for step_result in reversed(steps):
            try:
                rollback_action = f"rollback_{step_result.step.action}"
                self.guardrails.run(
                    rollback_action, step_result.step.params,
                    actor="playbook", dry_run=False, confirmed=True
                )
            except Exception:
                pass
