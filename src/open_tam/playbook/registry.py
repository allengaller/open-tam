"""Playbook registry for managing remediation playbooks."""
from __future__ import annotations

from pathlib import Path

import yaml

from open_tam.playbook.models import OnFailure, Playbook, PlaybookStep, Sensitivity


class PlaybookRegistry:
    """Registry for loading and managing playbooks."""

    def __init__(self, playbooks_dir: Path | str | None = None) -> None:
        self._playbooks: dict[str, Playbook] = {}
        self._dir = Path(playbooks_dir) if playbooks_dir else None

    def register(self, playbook: Playbook) -> None:
        self._playbooks[playbook.id] = playbook

    def get(self, playbook_id: str) -> Playbook | None:
        return self._playbooks.get(playbook_id)

    def list_all(self) -> list[Playbook]:
        return list(self._playbooks.values())

    def find_matching(self, alert_name: str, confidence: float) -> list[Playbook]:
        return [p for p in self._playbooks.values() if p.matches(alert_name, confidence)]

    def load_from_dir(self, directory: Path | str | None = None) -> int:
        """Load playbooks from YAML files. Returns count loaded."""
        dir_path = Path(directory) if directory else self._dir
        if not dir_path or not dir_path.exists():
            return 0

        count = 0
        for path in dir_path.glob("*.yaml"):
            try:
                playbook = self._load_yaml(path)
                self.register(playbook)
                count += 1
            except Exception:
                continue
        return count

    def _load_yaml(self, path: Path) -> Playbook:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        steps = []
        for s in data.get("steps", []):
            steps.append(PlaybookStep(
                order=s.get("order", 0),
                action=s["action"],
                params=s.get("params", {}),
                sensitivity=Sensitivity(s.get("sensitivity", "safe")),
                auto_execute=s.get("auto_execute", True),
                on_failure=OnFailure(s.get("on_failure", "abort")),
                description=s.get("description", ""),
            ))

        trigger = data.get("trigger", {})
        return Playbook(
            id=data["id"],
            name=data.get("name", data["id"]),
            steps=steps,
            trigger_pattern=trigger.get("alert_pattern", "*"),
            confidence_threshold=trigger.get("confidence_threshold", 0.7),
            description=data.get("description", ""),
        )
