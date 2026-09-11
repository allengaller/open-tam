"""M6 tests: Skill models, loader, extractor, CLI, injection."""
from __future__ import annotations

import json
from pathlib import Path

from open_tam.skills.models import Skill, SkillStep

# ── models ────────────────────────────────────────────────


class TestSkillModel:
    def test_matches_exact(self):
        skill = Skill(id="s1", name="test", alert_pattern="cpu_spike")
        assert skill.matches("cpu_spike") is True
        assert skill.matches("oom") is False

    def test_matches_glob(self):
        skill = Skill(id="s1", name="test", alert_pattern="cpu_*")
        assert skill.matches("cpu_spike") is True
        assert skill.matches("cpu_high") is True
        assert skill.matches("oom") is False

    def test_matches_service_filter(self):
        skill = Skill(id="s1", name="test", alert_pattern="*", service_pattern="demo-*")
        assert skill.matches("anything", "demo-app") is True
        assert skill.matches("anything", "web-svc") is False

    def test_matches_wildcard_service(self):
        skill = Skill(id="s1", name="test", alert_pattern="*", service_pattern="*")
        assert skill.matches("anything", "any-service") is True

    def test_to_prompt_section(self):
        skill = Skill(
            id="s1", name="CPU 排查", alert_pattern="cpu_*",
            description="CPU 飙升排查模板",
            steps=[SkillStep(order=1, action="query_metrics", params={"metric": "cpu_usage"}, expected_signal=">80%")],
            root_cause_hints=["正则回溯"],
            confidence=0.85,
        )
        section = skill.to_prompt_section()
        assert "CPU 排查" in section
        assert "query_metrics" in section
        assert "正则回溯" in section
        assert "0.85" in section


# ── loader ────────────────────────────────────────────────


class TestSkillLoader:
    def test_load_empty_dir(self, tmp_path):
        from open_tam.skills.loader import SkillLoader

        loader = SkillLoader(tmp_path)
        assert loader.load_all() == []

    def test_load_nonexistent_dir(self, tmp_path):
        from open_tam.skills.loader import SkillLoader

        loader = SkillLoader(tmp_path / "nonexistent")
        assert loader.load_all() == []

    def test_save_and_load(self, tmp_path):
        from open_tam.skills.loader import SkillLoader

        loader = SkillLoader(tmp_path)
        skill = Skill(id="test-001", name="test skill", alert_pattern="cpu_*", confidence=0.8)
        loader.save(skill)

        loader2 = SkillLoader(tmp_path)
        skills = loader2.load_all()
        assert len(skills) == 1
        assert skills[0].id == "test-001"
        assert skills[0].name == "test skill"

    def test_match_returns_best(self, tmp_path):
        from open_tam.skills.loader import SkillLoader

        loader = SkillLoader(tmp_path)
        loader.save(Skill(id="s1", name="low", alert_pattern="cpu_*", confidence=0.3))
        loader.save(Skill(id="s2", name="high", alert_pattern="cpu_*", confidence=0.9))

        matched = loader.match("cpu_spike")
        assert matched is not None
        assert matched.id == "s2"

    def test_match_returns_none_when_no_match(self, tmp_path):
        from open_tam.skills.loader import SkillLoader

        loader = SkillLoader(tmp_path)
        loader.save(Skill(id="s1", name="test", alert_pattern="cpu_*"))
        assert loader.match("oom") is None

    def test_get_by_id(self, tmp_path):
        from open_tam.skills.loader import SkillLoader

        loader = SkillLoader(tmp_path)
        loader.save(Skill(id="findme", name="test", alert_pattern="*"))
        assert loader.get("findme") is not None
        assert loader.get("nonexistent") is None

    def test_delete(self, tmp_path):
        from open_tam.skills.loader import SkillLoader

        loader = SkillLoader(tmp_path)
        loader.save(Skill(id="delme", name="test", alert_pattern="*"))
        assert loader.delete("delme") is True
        assert loader.get("delme") is None
        assert loader.delete("nonexistent") is False

    def test_reload(self, tmp_path):
        from open_tam.skills.loader import SkillLoader

        loader = SkillLoader(tmp_path)
        loader.load_all()
        loader.save(Skill(id="new", name="new skill", alert_pattern="*"))
        assert len(loader.load_all()) == 1  # cached, still 1
        assert len(loader.reload()) == 1  # reloaded


# ── extractor ─────────────────────────────────────────────


class TestExtractor:
    def _write_trace(self, path: Path, entries: list[dict]) -> None:
        path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

    def test_extract_from_trace(self, tmp_path):
        from open_tam.skills.extractor import extract_skill_from_trace

        trace_path = tmp_path / "test.jsonl"
        self._write_trace(trace_path, [
            {"kind": "alert_received", "alert_name": "cpu_spike", "service": "demo-app"},
            {"kind": "tool_call", "tool": "query_metrics", "arguments": {"metric": "cpu_usage"}},
            {"kind": "observation", "data": "cpu_usage at 92%"},
            {"kind": "tool_call", "tool": "query_logs", "arguments": {"service": "demo-app"}},
            {"kind": "observation", "data": "error timeout in logs"},
            {"kind": "final", "root_cause": "正则回溯导致 CPU 飙升"},
        ])

        skill = extract_skill_from_trace(trace_path)
        assert skill.alert_pattern == "cpu_spike"
        assert len(skill.steps) == 2
        assert skill.steps[0].action == "query_metrics"
        assert "正则" in skill.root_cause_hints[0]
        assert skill.confidence > 0

    def test_extract_no_final_lower_confidence(self, tmp_path):
        from open_tam.skills.extractor import extract_skill_from_trace

        trace_path = tmp_path / "incomplete.jsonl"
        self._write_trace(trace_path, [
            {"kind": "alert_received", "alert_name": "oom", "service": "app"},
            {"kind": "tool_call", "tool": "query_metrics", "arguments": {}},
        ])

        skill = extract_skill_from_trace(trace_path)
        assert skill.confidence < 0.5

    def test_extract_from_dir_aggregates(self, tmp_path):
        from open_tam.skills.extractor import extract_skills_from_dir

        for i in range(3):
            trace_path = tmp_path / f"trace-{i}.jsonl"
            self._write_trace(trace_path, [
                {"kind": "alert_received", "alert_name": "cpu_spike", "service": "demo-app"},
                {"kind": "tool_call", "tool": "query_metrics", "arguments": {}},
                {"kind": "final", "root_cause": "CPU issue"},
            ])

        skills = extract_skills_from_dir(tmp_path)
        assert len(skills) == 1
        assert skills[0].confidence > 0.5


# ── injection ─────────────────────────────────────────────


class TestSkillInjection:
    def test_build_system_prompt_injects_skill(self, tmp_path):
        from open_tam.config import Settings
        from open_tam.models import AlertEvent
        from open_tam.orchestrator.agents import ORCHESTRATOR_PROMPT
        from open_tam.orchestrator.investigate import _build_system_prompt
        from open_tam.skills.loader import SkillLoader

        loader = SkillLoader(tmp_path)
        loader.save(Skill(id="s1", name="CPU 排查", alert_pattern="cpu_*", confidence=0.9,
                          description="测试 Skill"))

        settings = Settings.load()
        settings = Settings(
            **{**settings.__dict__, "skills_dir": tmp_path}
        )
        alert = AlertEvent(alert_name="cpu_spike", service="demo-app", metric="cpu", threshold=80, current_value=92)

        prompt = _build_system_prompt(alert, settings, ORCHESTRATOR_PROMPT)
        assert "CPU 排查" in prompt
        assert "测试 Skill" in prompt

    def test_build_system_prompt_no_skill(self, tmp_path):
        from open_tam.config import Settings
        from open_tam.models import AlertEvent
        from open_tam.orchestrator.agents import ORCHESTRATOR_PROMPT
        from open_tam.orchestrator.investigate import _build_system_prompt

        settings = Settings.load()
        settings = Settings(**{**settings.__dict__, "skills_dir": tmp_path})
        alert = AlertEvent(alert_name="cpu_spike", service="demo-app", metric="cpu", threshold=80, current_value=92)

        prompt = _build_system_prompt(alert, settings, ORCHESTRATOR_PROMPT)
        assert prompt == ORCHESTRATOR_PROMPT


# ── CLI ───────────────────────────────────────────────────


class TestSkillCLI:
    def test_skill_list_empty(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from open_tam.cli import app
        monkeypatch.setenv("OPEN_TAM_SKILLS_DIR", str(tmp_path))
        runner = CliRunner()
        result = runner.invoke(app, ["skill", "list"])
        assert result.exit_code == 0
        assert "无 Skill" in result.output

    def test_skill_learn_and_list(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from open_tam.cli import app
        traces_dir = tmp_path / "traces"
        traces_dir.mkdir()
        skills_dir = tmp_path / "skills"
        monkeypatch.setenv("OPEN_TAM_SKILLS_DIR", str(skills_dir))

        trace = traces_dir / "test.jsonl"
        trace.write_text("\n".join([
            json.dumps({"kind": "alert_received", "alert_name": "cpu_spike", "service": "demo-app"}),
            json.dumps({"kind": "tool_call", "tool": "query_metrics", "arguments": {}}),
            json.dumps({"kind": "final", "root_cause": "CPU issue"}),
        ]), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(app, ["skill", "learn", "--traces", str(traces_dir)])
        assert result.exit_code == 0
        assert "saved" in result.output

        result = runner.invoke(app, ["skill", "list"])
        assert result.exit_code == 0
        assert "cpu_spike" in result.output
