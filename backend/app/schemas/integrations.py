import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IntegrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    display_name: str
    status: str
    config: dict
    last_synced_at: datetime | None
    last_error: str | None


class PagerDutyConnect(BaseModel):
    display_name: str = Field(default="PagerDuty", max_length=200)
    api_key: str = Field(min_length=1)


class MockConnect(BaseModel):
    provider: str = Field(pattern="^(pagerduty|github)$")
    display_name: str | None = None


class GitHubConnect(BaseModel):
    """Direct token connect — the OAuth flow is the normal path, this is for
    a PAT during development."""

    display_name: str = Field(default="GitHub", max_length=200)
    access_token: str = Field(min_length=1)
    org: str | None = None
    repos: list[str] = Field(default_factory=list)
    environment: str = "production"


class DiscoveredResource(BaseModel):
    resource_type: str
    external_id: str
    name: str
    claimed_by_team_id: uuid.UUID | None = None


class SyncTriggered(BaseModel):
    job_id: int | None
    queued: bool
