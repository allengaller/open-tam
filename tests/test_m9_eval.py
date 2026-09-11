"""M9 tests: LLM-as-Judge, multi-dimensional eval, A/B compare, CLI flags."""
from __future__ import annotations

# ── LLM-as-Judge ─────────────────────────────────────────


class TestEvidenceJudge:
    def test_parse_score_integer(self):
        from open_tam.eval_judge import EvidenceJudge, fake_judge_model

        judge = EvidenceJudge(model=fake_judge_model(0.8))
        assert judge._parse_score("0.8") == 0.8

    def test_parse_score_from_text(self):
        from open_tam.eval_judge import EvidenceJudge, fake_judge_model

        judge = EvidenceJudge(model=fake_judge_model())
        assert judge._parse_score("评分: 0.75 分") == 0.75

    def test_parse_score_clamped(self):
        from open_tam.eval_judge import EvidenceJudge, fake_judge_model

        judge = EvidenceJudge(model=fake_judge_model())
        assert judge._parse_score("1.5") == 1.0
        assert judge._parse_score("-0.1") == 0.0

    def test_parse_score_empty(self):
        from open_tam.eval_judge import EvidenceJudge, fake_judge_model

        judge = EvidenceJudge(model=fake_judge_model())
        assert judge._parse_score("") == 0.0
        assert judge._parse_score(None) == 0.0

    def test_judge_returns_verdict(self):
        from open_tam.eval_judge import EvidenceJudge, fake_judge_model

        judge = EvidenceJudge(model=fake_judge_model(0.85))
        verdict = judge.judge(
            report="根因是正则回溯导致 CPU 飙升",
            trace_entries=[
                {"kind": "tool_call", "tool": "query_metrics", "arguments": {"metric": "cpu"}},
                {"kind": "observation", "data": "cpu at 92%"},
                {"kind": "final", "root_cause": "正则回溯"},
            ],
            expected_root_cause="正则回溯导致 CPU 飙升",
        )
        assert verdict.score == 0.85
        assert verdict.dimension == "evidence_sufficiency"

    def test_summarize_trace(self):
        from open_tam.eval_judge import EvidenceJudge, fake_judge_model

        judge = EvidenceJudge(model=fake_judge_model())
        summary = judge._summarize_trace([
            {"kind": "tool_call", "tool": "query_metrics", "arguments": {"metric": "cpu"}},
            {"kind": "observation", "data": "cpu at 92%"},
            {"kind": "final", "root_cause": "CPU issue"},
        ])
        assert "query_metrics" in summary
        assert "cpu at 92%" in summary
        assert "CPU issue" in summary


# ── Multi-dimensional EvalReport ──────────────────────────


class TestEvalReportMultiDimension:
    def test_avg_evidence_sufficiency(self):
        from open_tam.eval import EvalReport, EvalRun

        report = EvalReport(model_label="test", runs=[
            EvalRun(fault="cpu", root_cause="x", keyword_hit=True, confidence="high",
                    steps=3, elapsed_s=1.0, evidence_sufficiency=0.8),
            EvalRun(fault="oom", root_cause="y", keyword_hit=True, confidence="high",
                    steps=4, elapsed_s=2.0, evidence_sufficiency=0.6),
        ])
        assert report.avg_evidence_sufficiency == 0.7

    def test_check_min_hit_rate_pass(self):
        from open_tam.eval import EvalReport, EvalRun

        report = EvalReport(model_label="test", runs=[
            EvalRun(fault="cpu", root_cause="x", keyword_hit=True, confidence="high",
                    steps=3, elapsed_s=1.0),
        ])
        assert report.check_min_hit_rate(0.5) is True

    def test_check_min_hit_rate_fail(self):
        from open_tam.eval import EvalReport, EvalRun

        report = EvalReport(model_label="test", runs=[
            EvalRun(fault="cpu", root_cause=None, keyword_hit=False, confidence="low",
                    steps=3, elapsed_s=1.0),
        ])
        assert report.check_min_hit_rate(0.5) is False


# ── A/B Compare ───────────────────────────────────────────


class TestCompareReport:
    def test_summary_row(self):
        from open_tam.eval import EvalReport, EvalRun
        from open_tam.eval_compare import CompareReport, CompareResult

        r1 = CompareResult(model_label="model-a", report=EvalReport(
            model_label="model-a",
            runs=[EvalRun(fault="cpu", root_cause="x", keyword_hit=True,
                          confidence="high", steps=3, elapsed_s=1.0)],
        ))
        r2 = CompareResult(model_label="model-b", report=EvalReport(
            model_label="model-b",
            runs=[EvalRun(fault="cpu", root_cause="y", keyword_hit=False,
                          confidence="low", steps=5, elapsed_s=2.0)],
        ))
        report = CompareReport(results=[r1, r2], fault_names=["cpu"])
        assert report.models == ["model-a", "model-b"]
        row = report.summary_row("hit_rate")
        assert row["model-a"] == 1.0
        assert row["model-b"] == 0.0


# ── CLI flags ─────────────────────────────────────────────


class TestEvalCLI:
    def test_eval_min_hit_rate_pass(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from open_tam.cli import app
        monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "traces"))
        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "state"))

        runner = CliRunner()
        result = runner.invoke(app, ["eval", "--fake", "--faults", "cpu_spike", "--min-hit-rate", "0.5"])
        assert result.exit_code == 0

    def test_eval_min_hit_rate_fail(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from open_tam.cli import app
        monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "traces"))
        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "state"))

        runner = CliRunner()
        result = runner.invoke(app, ["eval", "--fake", "--faults", "cpu_spike", "--min-hit-rate", "1.1"])
        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_eval_compare(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from open_tam.cli import app
        monkeypatch.setenv("OPEN_TAM_REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setenv("OPEN_TAM_TRACES_DIR", str(tmp_path / "traces"))
        monkeypatch.setenv("OPEN_TAM_STATE_DIR", str(tmp_path / "state"))

        runner = CliRunner()
        result = runner.invoke(app, [
            "eval-compare", "--models", "qwen-plus,qwen-turbo",
            "--faults", "cpu_spike", "--fake",
        ])
        assert result.exit_code == 0
        assert "qwen-plus" in result.output
        assert "qwen-turbo" in result.output
        assert "compare report" in result.output
