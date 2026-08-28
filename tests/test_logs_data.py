from datetime import datetime, timedelta

from open_tam.faults import FaultState
from open_tam.mock.logs_data import generate_logs


def _window_around_fault(state, name="slow_query", before=30, after=60):
    start = state.snapshot_time(name)
    return start - timedelta(minutes=before), start + timedelta(minutes=after)


def test_baseline_logs_are_info_only(tmp_path):
    now = datetime.now().replace(second=0, microsecond=0)
    records = generate_logs("demo-app", now, now + timedelta(minutes=5),
                            state=FaultState(state_dir=tmp_path))
    assert records
    assert all(r.level == "INFO" for r in records)


def test_fault_window_emits_error_logs(tmp_path):
    state = FaultState(state_dir=tmp_path)
    state.activate("slow_query", duration_minutes=30)
    start, end = _window_around_fault(state)
    records = generate_logs("demo-app", start, end, state=state)
    errors = [r for r in records if r.level == "ERROR"]
    assert errors
    assert all("Slow query detected" in r.message for r in errors)
    assert all(r.ts >= start + timedelta(minutes=30) for r in errors)


def test_level_and_keyword_filters(tmp_path):
    state = FaultState(state_dir=tmp_path)
    state.activate("slow_query", duration_minutes=30)
    start, end = _window_around_fault(state)
    records = generate_logs("demo-app", start, end, level="error", state=state)
    assert records and all(r.level == "ERROR" for r in records)
    hits = generate_logs("demo-app", start, end, keyword="slow query", state=state)
    assert hits and all("slow query" in r.message.lower() for r in hits)
    assert generate_logs("demo-app", start, end, keyword="no-such-keyword", state=state) == []


def test_logs_deterministic(tmp_path):
    state = FaultState(state_dir=tmp_path)
    state.activate("slow_query", duration_minutes=30)
    start, end = _window_around_fault(state)
    s1 = generate_logs("demo-app", start, end, state=state)
    s2 = generate_logs("demo-app", start, end, state=state)
    assert [(r.ts, r.level, r.message) for r in s1] == [(r.ts, r.level, r.message) for r in s2]
