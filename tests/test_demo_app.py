from fastapi.testclient import TestClient

from demo_app.app import create_app


def test_health_ok(tmp_path):
    client = TestClient(create_app(state_dir=tmp_path))
    assert client.get("/health").json() == {"status": "ok"}


def test_cpu_usage_reflects_injected_fault(tmp_path):
    client = TestClient(create_app(state_dir=tmp_path))
    normal = client.get("/metrics").json()["cpu_usage"]
    assert normal <= 55
    client.post("/faults/cpu_spike")
    spiked = client.get("/metrics").json()["cpu_usage"]
    assert spiked >= 85
    client.delete("/faults/cpu_spike")
    assert client.get("/metrics").json()["cpu_usage"] <= 55


def test_unknown_fault_returns_404(tmp_path):
    client = TestClient(create_app(state_dir=tmp_path))
    assert client.post("/faults/no_such").status_code == 404
