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
    pts = generate_series(
        metric="cpu_usage", service="demo-app",
        start=start - timedelta(minutes=5), end=start + timedelta(minutes=35),
        seed=42, state=state,
    )
    in_window = [p for p in pts if start <= p.ts <= start + timedelta(minutes=29)]
    out_window = [p for p in pts if p.ts < start]
    assert in_window and all(p.value >= 85 for p in in_window)
    assert out_window and all(p.value <= 55 for p in out_window)


def test_series_deterministic_with_same_seed(tmp_path):
    s1 = _series(FaultState(state_dir=tmp_path))
    s2 = _series(FaultState(state_dir=tmp_path))
    assert [(p.ts, p.value) for p in s1] == [(p.ts, p.value) for p in s2]


def test_slow_query_spike_in_window(tmp_path):
    state = FaultState(state_dir=tmp_path)
    state.activate("slow_query", duration_minutes=30)
    start = state.snapshot_time("slow_query")
    pts = generate_series(
        metric="db_query_duration_ms", service="demo-app",
        start=start - timedelta(minutes=5), end=start + timedelta(minutes=10),
        seed=7, state=state,
    )
    in_window = [p for p in pts if p.ts >= start]
    out_window = [p for p in pts if p.ts < start]
    assert in_window and all(p.value >= 3000 for p in in_window)
    assert out_window and all(p.value <= 350 for p in out_window)


def test_z_suffix_window_still_hits_fault(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path))
    from open_tam.orchestrator.tools import query_metrics_inline
    import json as _json

    state = FaultState(state_dir=tmp_path)
    state.activate("slow_query", duration_minutes=30)
    start = state.snapshot_time("slow_query")
    from datetime import timezone

    start_utc = start.astimezone().astimezone(timezone.utc).replace(tzinfo=None)
    payload = _json.loads(query_metrics_inline(
        metric="db_query_duration_ms", service="demo-app",
        start=start_utc.isoformat() + "Z",
        end=(start_utc + timedelta(minutes=10)).isoformat() + "Z",
    ))
    values = [p["value"] for p in payload]
    assert values and all(v >= 3000 for v in values)
