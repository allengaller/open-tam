from datetime import datetime, timedelta

from open_tam.faults import FaultState
from open_tam.mock.metrics_data import generate_series


def _series(state):
    return generate_series(
        metric="cpu_usage",
        service="demo-app",
        start=datetime(2026, 8, 28, 0, 0),
        end=datetime(2026, 8, 28, 23, 59),
        seed=42,
        state=state,
    )


def test_normal_series_stays_in_baseline_band(tmp_path):
    pts = _series(FaultState(state_dir=tmp_path))
    assert pts, "series should not be empty"
    assert all(0 <= p.value <= 55 for p in pts)


def test_spike_only_inside_fault_window(tmp_path):
    state = FaultState(state_dir=tmp_path)
    state.activate("cpu_spike", duration_minutes=30)
    start = state.snapshot_time("cpu_spike")
    pts = _series(state)
    in_window = [p for p in pts if start <= p.ts <= start + timedelta(minutes=29)]
    out_window = [p for p in pts if p.ts < start]
    assert in_window and all(p.value >= 85 for p in in_window)
    assert out_window and all(p.value <= 55 for p in out_window)


def test_series_deterministic_with_same_seed(tmp_path):
    s1 = _series(FaultState(state_dir=tmp_path))
    s2 = _series(FaultState(state_dir=tmp_path))
    assert [(p.ts, p.value) for p in s1] == [(p.ts, p.value) for p in s2]
