"""Provider-neutral shapes every integration normalises into.

Adding Opsgenie or GitLab means implementing one of these protocols and
registering it — nothing downstream (persistence, metrics, UI) changes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

# resource_type values understood by team_resources
PD_SERVICE = "pd_service"
PD_SCHEDULE = "pd_schedule"
GH_REPO = "gh_repo"


@dataclass(slots=True)
class NormalizedUser:
    external_id: str
    handle: str | None = None
    email: str | None = None
    name: str | None = None


@dataclass(slots=True)
class NormalizedResource:
    """A provider-side thing a team can own: a PD service, a PD schedule, a repo."""

    resource_type: str
    external_id: str
    name: str


@dataclass(slots=True)
class NormalizedPage:
    external_id: str
    external_user_id: str | None
    paged_at: datetime
    channel: str | None = None
    is_ack: bool = False


@dataclass(slots=True)
class NormalizedIncident:
    external_id: str
    title: str
    status: str
    created_at: datetime
    service_external_id: str | None = None
    service_name: str | None = None
    urgency: str | None = None
    severity: str | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    pages: list[NormalizedPage] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedShift:
    external_id: str
    external_user_id: str | None
    starts_at: datetime
    ends_at: datetime
    schedule_external_id: str | None = None
    schedule_name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedDeploy:
    external_id: str
    repo_full_name: str
    deployed_at: datetime
    status: str = "success"
    environment: str | None = None
    sha: str | None = None
    ref: str | None = None
    actor_external_id: str | None = None
    pr_number: int | None = None
    pr_merged_at: datetime | None = None
    is_rollback: bool = False
    reverts_sha: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class IncidentSource(Protocol):
    """PagerDuty today; Opsgenie slots in here later."""

    provider: str

    def fetch_users(self) -> list[NormalizedUser]: ...

    def list_resources(self) -> list[NormalizedResource]: ...

    def fetch_incidents(self, since: datetime) -> list[NormalizedIncident]: ...

    def fetch_shifts(self, start: datetime, end: datetime) -> list[NormalizedShift]: ...


@runtime_checkable
class DeploySource(Protocol):
    """GitHub today; GitLab slots in here later."""

    provider: str

    def fetch_users(self) -> list[NormalizedUser]: ...

    def list_resources(self) -> list[NormalizedResource]: ...

    def fetch_deploys(self, since: datetime) -> list[NormalizedDeploy]: ...
