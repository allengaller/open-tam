from __future__ import annotations

import fnmatch
from pathlib import Path

import yaml

from open_tam.skills.models import Skill


class SkillLoader:
    """从 skills_dir 加载 YAML Skill 文件，按告警名匹配。"""

    def __init__(self, skills_dir: Path | str) -> None:
        self.skills_dir = Path(skills_dir)
        self._skills: list[Skill] | None = None

    def load_all(self) -> list[Skill]:
        if self._skills is not None:
            return self._skills
        if not self.skills_dir.exists():
            self._skills = []
            return self._skills
        skills = []
        for path in sorted(self.skills_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    skills.append(Skill.model_validate(data))
            except Exception:
                continue
        self._skills = skills
        return self._skills

    def match(self, alert_name: str, service: str = "") -> Skill | None:
        candidates = [s for s in self.load_all() if s.matches(alert_name, service)]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.confidence)

    def get(self, skill_id: str) -> Skill | None:
        for s in self.load_all():
            if s.id == skill_id:
                return s
        return None

    def reload(self) -> list[Skill]:
        self._skills = None
        return self.load_all()

    def save(self, skill: Skill) -> Path:
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        path = self.skills_dir / f"{skill.id}.yaml"
        path.write_text(
            yaml.dump(skill.model_dump(), allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        self._skills = None
        return path

    def delete(self, skill_id: str) -> bool:
        path = self.skills_dir / f"{skill_id}.yaml"
        if path.exists():
            path.unlink()
            self._skills = None
            return True
        return False
