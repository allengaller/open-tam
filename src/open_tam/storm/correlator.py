"""Alert correlation engine for storm detection."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from open_tam.models import AlertEvent


@dataclass
class AlertGroup:
    """A group of correlated alerts."""
    id: str
    alerts: list[AlertEvent] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def add(self, alert: AlertEvent) -> None:
        self.alerts.append(alert)

    def __len__(self) -> int:
        return len(self.alerts)

    def __iter__(self) -> Iterator[AlertEvent]:
        return iter(self.alerts)


class AlertCorrelator:
    """Correlate alerts by time window + service overlap.

    Strategy:
    1. Same service within time window → same group
    2. Configured service dependencies → same group
    """

    def __init__(
        self,
        window_seconds: int = 60,
        service_dependencies: dict[str, list[str]] | None = None,
    ) -> None:
        self._groups: dict[str, AlertGroup] = {}
        self._alert_group_map: dict[str, str] = {}
        self._window = timedelta(seconds=window_seconds)
        self._dependencies = service_dependencies or {}
        self._group_counter = 0

    def correlate(self, alert: AlertEvent) -> str | None:
        """Return group ID if alert correlates to existing group, else None."""
        now = datetime.now()

        for group_id, group in list(self._groups.items()):
            if not group.alerts:
                continue

            latest = max(a.triggered_at for a in group.alerts)
            if now - latest > self._window:
                continue

            for existing in group.alerts:
                if self._should_correlate(alert, existing):
                    group.add(alert)
                    self._alert_group_map[alert.alert_id] = group_id
                    return group_id

        return None

    def create_group(self, alert: AlertEvent) -> str:
        """Create a new group for this alert."""
        self._group_counter += 1
        group_id = f"grp-{self._group_counter:04d}"
        group = AlertGroup(id=group_id)
        group.add(alert)
        self._groups[group_id] = group
        self._alert_group_map[alert.alert_id] = group_id
        return group_id

    def get_group(self, group_id: str) -> AlertGroup | None:
        return self._groups.get(group_id)

    def get_group_for_alert(self, alert_id: str) -> AlertGroup | None:
        group_id = self._alert_group_map.get(alert_id)
        if group_id:
            return self._groups.get(group_id)
        return None

    def _should_correlate(self, a: AlertEvent, b: AlertEvent) -> bool:
        if a.service == b.service:
            return True
        if self._are_services_related(a.service, b.service):
            return True
        return False

    def _are_services_related(self, svc_a: str, svc_b: str) -> bool:
        deps_a = self._dependencies.get(svc_a, [])
        deps_b = self._dependencies.get(svc_b, [])
        return svc_b in deps_a or svc_a in deps_b

    def cleanup_expired(self) -> int:
        """Remove expired groups. Returns count of removed groups."""
        now = datetime.now()
        expired = []
        for group_id, group in self._groups.items():
            if not group.alerts:
                expired.append(group_id)
                continue
            latest = max(a.triggered_at for a in group.alerts)
            if now - latest > self._window * 2:
                expired.append(group_id)

        for group_id in expired:
            group = self._groups.pop(group_id)
            for alert in group.alerts:
                self._alert_group_map.pop(alert.alert_id, None)

        return len(expired)
