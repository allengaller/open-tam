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
