from open_tam.tracing.trace import TraceRecorder, load_trace


def test_recorder_appends_jsonl_and_loads(tmp_path):
    rec = TraceRecorder("a1", traces_dir=tmp_path)
    rec.record("alert_received", user="alert json")
    rec.record("tool_call", tool="query_metrics", arguments={"metric": "cpu_usage"})
    records = load_trace(rec.path)
    assert [r["kind"] for r in records] == ["alert_received", "tool_call"]
    assert records[1]["arguments"] == {"metric": "cpu_usage"}
    assert records[0]["alert_id"] == "a1"
    assert records[0]["ts"]


def test_trace_env_default_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "t"))
    rec = TraceRecorder("a2")
    rec.record("final", content="done")
    assert (tmp_path / "t" / "a2.jsonl").exists()


def test_recorder_tags_agent_field(tmp_path):
    rec = TraceRecorder("a3", traces_dir=tmp_path, agent="log")
    rec.record("tool_call", tool="query_logs", arguments={"service": "demo-app"})
    records = load_trace(rec.path)
    assert records[0]["agent"] == "log"


def test_record_invokes_sink(tmp_path):
    seen: list[dict] = []
    trace = TraceRecorder(alert_id="a1", traces_dir=tmp_path, sink=seen.append)
    trace.record("tool_call", step=0, tool="query_metrics", arguments={"m": 1})
    trace.record("final", content="done")

    assert [e["kind"] for e in seen] == ["tool_call", "final"]
    assert seen[0]["tool"] == "query_metrics"
    on_disk = load_trace(tmp_path / "a1.jsonl")
    assert [e["kind"] for e in on_disk] == ["tool_call", "final"]
    assert seen[0] == on_disk[0]


def test_record_without_sink_unchanged(tmp_path):
    trace = TraceRecorder(alert_id="a2", traces_dir=tmp_path)
    trace.record("final", content="ok")
    assert load_trace(tmp_path / "a2.jsonl")[0]["kind"] == "final"
