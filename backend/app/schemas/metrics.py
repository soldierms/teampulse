import uuid
from datetime import date

from pydantic import BaseModel


class TrendPoint(BaseModel):
    period_start: date
    value: float


class MetricSeries(BaseModel):
    metric_key: str
    points: list[TrendPoint]


class TeamOverview(BaseModel):
    team_id: uuid.UUID
    team_name: str
    toil_score: float
    toil_score_previous: float
    trend: str  # up | down | flat
    pages_total: float
    after_hours_page_rate: float
    change_failure_rate: float
    deploy_frequency_per_week: float


class OrgOverview(BaseModel):
    week_start: date
    teams: list[TeamOverview]


class MemberLoad(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    pages_total: float
    pages_after_hours: float
    after_hours_page_rate: float
    on_call_hours: float


class TeamDetail(BaseModel):
    team_id: uuid.UUID
    team_name: str
    days: int
    totals: dict[str, float]
    series: list[MetricSeries]
    members: list[MemberLoad]


class PersonDetail(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    days: int
    totals: dict[str, float]
    series: list[MetricSeries]
