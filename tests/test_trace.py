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
