from datetime import UTC, datetime
from typing import Any

from app.integrations.base import (
    NormalizedIncident,
    NormalizedResource,
    NormalizedShift,
    NormalizedUser,
)
from app.integrations.pagerduty import mapper
from app.integrations.pagerduty.client import PagerDutyClient


class PagerDutyProvider:
    """Implements IncidentSource against the live PagerDuty API."""

    provider = "pagerduty"

    def __init__(self, credentials: dict[str, Any], config: dict[str, Any] | None = None) -> None:
        self._client = PagerDutyClient(credentials.get("api_key", ""))
        self._config = config or {}

    def close(self) -> None:
        self._client.close()

    def fetch_users(self) -> list[NormalizedUser]:
        return [mapper.map_user(u) for u in self._client.users()]

    def list_resources(self) -> list[NormalizedResource]:
        return [mapper.map_service(s) for s in self._client.services()] + [
            mapper.map_schedule(s) for s in self._client.schedules()
        ]

    def fetch_incidents(self, since: datetime) -> list[NormalizedIncident]:
        until = datetime.now(UTC)
        incidents = []
        for payload in self._client.incidents(since, until):
            # One extra call per incident. Fine at v1 volumes; if it becomes the
            # bottleneck, fall back to assignees and drop per-notification grain.
            log_entries = self._client.incident_log_entries(payload["id"])
            incidents.append(mapper.map_incident(payload, log_entries))
        return incidents

    def fetch_shifts(self, start: datetime, end: datetime) -> list[NormalizedShift]:
        shifts = (mapper.map_oncall(o) for o in self._client.oncalls(start, end))
        return [s for s in shifts if s is not None]
