"""Tests for M10: 告警风暴与高级编排."""
from __future__ import annotations

from open_tam.models import AlertEvent
from open_tam.playbook.executor import PlaybookExecutor
from open_tam.playbook.models import (
    Playbook,
    PlaybookStep,
    Sensitivity,
    StepStatus,
)
from open_tam.playbook.registry import PlaybookRegistry
from open_tam.storm.correlator import AlertCorrelator
from open_tam.storm.priority_queue import (
    Priority,
    PriorityQueue,
    infer_priority,
)


def _make_alert(alert_id: str, service: str = "demo-app", severity: str = "warning") -> AlertEvent:
    return AlertEvent(
        alert_id=alert_id,
        alert_name="test alert",
        service=service,
        metric="cpu_usage",
        threshold=80.0,
        current_value=92.0,
        severity=severity,
    )


class TestAlertCorrelator:
    def test_create_group(self):
        correlator = AlertCorrelator(window_seconds=60)
        alert = _make_alert("a1")
        group_id = correlator.create_group(alert)
        assert group_id.startswith("grp-")
        group = correlator.get_group(group_id)
        assert group is not None
        assert len(group) == 1

    def test_correlate_same_service(self):
        correlator = AlertCorrelator(window_seconds=600)
        a1 = _make_alert("a1", service="demo-app")
        a2 = _make_alert("a2", service="demo-app")
        correlator.create_group(a1)
        group_id = correlator.correlate(a2)
        assert group_id is not None
        group = correlator.get_group(group_id)
        assert len(group) == 2

    def test_no_correlate_different_service(self):
        correlator = AlertCorrelator(window_seconds=600)
        a1 = _make_alert("a1", service="demo-app")
        a2 = _make_alert("a2", service="other-app")
        correlator.create_group(a1)
        group_id = correlator.correlate(a2)
        assert group_id is None

    def test_correlate_with_dependencies(self):
        correlator = AlertCorrelator(
            window_seconds=600,
            service_dependencies={"demo-app": ["db-service"]},
        )
        a1 = _make_alert("a1", service="demo-app")
        a2 = _make_alert("a2", service="db-service")
        correlator.create_group(a1)
        group_id = correlator.correlate(a2)
        assert group_id is not None

    def test_get_group_for_alert(self):
        correlator = AlertCorrelator()
        alert = _make_alert("a1")
        group_id = correlator.create_group(alert)
        group = correlator.get_group_for_alert("a1")
        assert group is not None
        assert group.id == group_id


class TestPriorityQueue:
    def test_push_and_pop(self):
        queue = PriorityQueue()
        alert = _make_alert("a1")
        queue.push(alert, Priority.P1)
        assert len(queue) == 1
        popped = queue.pop()
        assert popped is not None
        assert popped.alert.alert_id == "a1"

    def test_priority_ordering(self):
        queue = PriorityQueue()
        a1 = _make_alert("a1")
        a2 = _make_alert("a2")
        a3 = _make_alert("a3")
        queue.push(a1, Priority.P2)
        queue.push(a2, Priority.P0)
        queue.push(a3, Priority.P1)
        first = queue.pop()
        assert first.priority == Priority.P0
        second = queue.pop()
        assert second.priority == Priority.P1

    def test_peek(self):
        queue = PriorityQueue()
        alert = _make_alert("a1")
        queue.push(alert, Priority.P1)
        peeked = queue.peek()
        assert peeked is not None
        assert len(queue) == 1

    def test_empty_queue(self):
        queue = PriorityQueue()
        assert queue.is_empty()
        assert queue.pop() is None

    def test_get_by_priority(self):
        queue = PriorityQueue()
        queue.push(_make_alert("a1"), Priority.P0)
        queue.push(_make_alert("a2"), Priority.P1)
        queue.push(_make_alert("a3"), Priority.P0)
        p0_tasks = queue.get_by_priority(Priority.P0)
        assert len(p0_tasks) == 2


class TestInferPriority:
    def test_critical_is_p0(self):
        alert = _make_alert("a1", severity="critical")
        assert infer_priority(alert) == Priority.P0

    def test_warning_is_p2(self):
        alert = _make_alert("a1", severity="warning")
        assert infer_priority(alert) == Priority.P2

    def test_info_is_p3(self):
        alert = _make_alert("a1", severity="info")
        assert infer_priority(alert) == Priority.P3


class TestPlaybookModels:
    def test_playbook_matches(self):
        playbook = Playbook(
            id="test", name="Test",
            steps=[], trigger_pattern="cpu*", confidence_threshold=0.5,
        )
        assert playbook.matches("cpu_spike", 0.8)
        assert not playbook.matches("memory_oom", 0.8)
        assert not playbook.matches("cpu_spike", 0.3)

    def test_step_status_values(self):
        assert StepStatus.DONE.value == "done"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.DENIED.value == "denied"


class TestPlaybookExecutor:
    def test_execute_simple_playbook(self, tmp_path, monkeypatch):
        from open_tam.actions import ACTION_REGISTRY
        from open_tam.guardrails import AuditLogger, AutoApprove, Guardrails

        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
        guardrails = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path), confirmer=AutoApprove())
        executor = PlaybookExecutor(guardrails)

        playbook = Playbook(
            id="test", name="Test",
            steps=[
                PlaybookStep(order=1, action="clear_fault", params={"name": "cpu_spike"}),
            ],
        )
        result = executor.execute(playbook, context={})
        assert len(result.steps) == 1
        assert result.steps[0].status == StepStatus.DONE

    def test_execute_with_template_params(self, tmp_path, monkeypatch):
        from open_tam.actions import ACTION_REGISTRY
        from open_tam.guardrails import AuditLogger, AutoApprove, Guardrails

        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
        guardrails = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path), confirmer=AutoApprove())
        executor = PlaybookExecutor(guardrails)

        playbook = Playbook(
            id="test", name="Test",
            steps=[
                PlaybookStep(order=1, action="clear_fault", params={"name": "{{ fault_name }}"}),
            ],
        )
        result = executor.execute(playbook, context={"fault_name": "cpu_spike"})
        assert result.steps[0].status == StepStatus.DONE

    def test_sensitive_step_denied_without_confirmer(self, tmp_path, monkeypatch):
        from open_tam.actions import ACTION_REGISTRY
        from open_tam.guardrails import AuditLogger, AutoApprove, Guardrails

        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
        guardrails = Guardrails(ACTION_REGISTRY, AuditLogger(tmp_path), confirmer=AutoApprove())
        executor = PlaybookExecutor(guardrails, confirmer=None)

        playbook = Playbook(
            id="test", name="Test",
            steps=[
                PlaybookStep(
                    order=1, action="restart_service",
                    params={"service": "demo-app"},
                    sensitivity=Sensitivity.SENSITIVE, auto_execute=False,
                ),
            ],
        )
        result = executor.execute(playbook, context={})
        assert result.steps[0].status == StepStatus.DENIED


class TestPlaybookRegistry:
    def test_register_and_get(self):
        registry = PlaybookRegistry()
        playbook = Playbook(id="test", name="Test", steps=[])
        registry.register(playbook)
        assert registry.get("test") is not None

    def test_find_matching(self):
        registry = PlaybookRegistry()
        registry.register(Playbook(id="p1", name="P1", steps=[], trigger_pattern="cpu*"))
        registry.register(Playbook(id="p2", name="P2", steps=[], trigger_pattern="memory*"))
        matches = registry.find_matching("cpu_spike", 0.8)
        assert len(matches) == 1
        assert matches[0].id == "p1"

    def test_load_from_yaml(self, tmp_path):
        yaml_content = """
id: test_playbook
name: Test Playbook
trigger:
  alert_pattern: "cpu*"
  confidence_threshold: 0.5
steps:
  - order: 1
    action: clear_fault
    params:
      name: cpu_spike
    sensitivity: safe
"""
        (tmp_path / "test.yaml").write_text(yaml_content)
        registry = PlaybookRegistry()
        count = registry.load_from_dir(tmp_path)
        assert count == 1
        playbook = registry.get("test_playbook")
        assert playbook is not None
        assert len(playbook.steps) == 1
