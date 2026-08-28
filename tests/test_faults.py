import datetime

import pytest

from open_tam.faults import FAULT_MODES, FaultState


def test_cpu_spike_registered_with_full_story():
    mode = FAULT_MODES["cpu_spike"]
    assert mode.metric == "cpu_usage"
    assert mode.service == "demo-app"
    assert mode.root_cause
    assert mode.remediation
    assert mode.anomaly_desc


def test_state_activate_and_expire(tmp_path):
    state = FaultState(state_dir=tmp_path)
    state.activate("cpu_spike", duration_minutes=30)
    start = state.snapshot_time("cpu_spike")
    assert state.is_active("cpu_spike", now=start)
    assert not state.is_active("cpu_spike", now=start + datetime.timedelta(minutes=31))


def test_state_persists_across_instances(tmp_path):
    s1 = FaultState(state_dir=tmp_path)
    s1.activate("cpu_spike", duration_minutes=30)
    s2 = FaultState(state_dir=tmp_path)
    assert s2.is_active("cpu_spike")
    s2.clear("cpu_spike")
    assert not FaultState(state_dir=tmp_path).is_active("cpu_spike")


def test_unknown_fault_rejected(tmp_path):
    state = FaultState(state_dir=tmp_path)
    with pytest.raises(KeyError):
        state.activate("no_such_fault")
