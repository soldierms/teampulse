from datetime import datetime
from typing import Any

from app.integrations.base import (
    GH_REPO,
    NormalizedDeploy,
    NormalizedIncident,
    NormalizedResource,
    NormalizedShift,
    NormalizedUser,
)
from app.integrations.github import mapper as gh_mapper
from app.integrations.mock import generator
from app.integrations.pagerduty import mapper as pd_mapper


class MockIncidentProvider:
    """Stands in for PagerDuty when no account is connected. Payloads are
    PagerDuty-shaped and go through the PagerDuty mapper unchanged."""

    provider = "pagerduty"

    def __init__(
        self, credentials: dict[str, Any] | None = None, config: dict[str, Any] | None = None
    ):
        self._config = config or {}

    def close(self) -> None:
        return None

    def fetch_users(self) -> list[NormalizedUser]:
        return [pd_mapper.map_user(u) for u in generator.users()]

    def list_resources(self) -> list[NormalizedResource]:
        return [pd_mapper.map_service(s) for s in generator.services()] + [
            pd_mapper.map_schedule(s) for s in generator.schedules()
        ]

    def fetch_incidents(self, since: datetime) -> list[NormalizedIncident]:
        _start, until = generator.window()
        return [
            pd_mapper.map_incident(payload, generator.log_entries(payload))
            for payload in generator.incidents(since, until)
        ]

    def fetch_shifts(self, start: datetime, end: datetime) -> list[NormalizedShift]:
        shifts = (pd_mapper.map_oncall(o) for o in generator.oncalls(start, end))
        return [s for s in shifts if s is not None]


class MockDeployProvider:
    """Stands in for GitHub. Same idea — GitHub-shaped payloads, real mapper."""

    provider = "github"

    def __init__(
        self, credentials: dict[str, Any] | None = None, config: dict[str, Any] | None = None
    ):
        self._config = config or {}

    def close(self) -> None:
        return None

    def fetch_users(self) -> list[NormalizedUser]:
        return [
            NormalizedUser(
                external_id=str(1000 + idx),
                handle=email.split("@")[0],
                email=email,
                name=name,
            )
            for idx, (_pid, name, email, _team) in enumerate(generator.PEOPLE)
        ]

    def list_resources(self) -> list[NormalizedResource]:
        return [
            NormalizedResource(
                resource_type=GH_REPO, external_id=r["full_name"], name=r["full_name"]
            )
            for r in generator.repos()
        ]

    def fetch_deploys(self, since: datetime) -> list[NormalizedDeploy]:
        _start, until = generator.window()
        return [
            gh_mapper.map_deployment(
                payload,
                repo_full_name=payload["_mock_repo"],
                state=payload["_mock_state"],
                commit_message=payload["_mock_message"],
                pr_number=payload["_mock_pr_number"],
            )
            for payload in generator.deployments(since, until)
        ]
