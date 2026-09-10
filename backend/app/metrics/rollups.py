"""Loads events for a period, runs the pure math, writes metric_rollups.

Rollup buckets are UTC days and weeks (weeks start Monday). After-hours and
weekend classification still happens in each person's local timezone — the
bucket is when it happened, the classification is what it cost them.
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession

from app.metrics.compute import (
    DeployEvent,
    IncidentEvent,
    PageEvent,
    change_failure_rate,
    deploy_metrics,
    on_call_hours,
    page_metrics,
    pages_per_person_per_week,
    resolution_metrics,
)
from app.metrics.config import MetricsConfig, get_metrics_config
from app.metrics.toil import TOIL_METRIC_KEY, toil_score
from app.metrics.windows import resolve_timezone
from app.models.events import Deploy, Incident, IncidentPage, OnCallShift
from app.models.metrics import MetricRollup
from app.models.org import Organization, Team, TeamMember, User

log = logging.getLogger(__name__)

GRAIN_DAYS = {"day": 1, "week": 7}


def period_bounds(grain: str, period_start: date) -> tuple[datetime, datetime]:
    days = GRAIN_DAYS[grain]
    start = datetime.combine(period_start, datetime.min.time(), tzinfo=UTC)
    return start, start + timedelta(days=days)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _timezone_map(db: DbSession, org: Organization, team: Team) -> dict[uuid.UUID, str]:
    users = db.scalars(select(User).where(User.org_id == org.id)).all()
    return {u.id: resolve_timezone(u.timezone, team.timezone, org.timezone) for u in users}


def _team_headcount(db: DbSession, team_id: uuid.UUID) -> int:
    return len(db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == team_id)).all())


def _upsert(
    db: DbSession,
    org_id: uuid.UUID,
    team_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    grain: str,
    period_start: date,
    values: dict[str, float],
) -> None:
    if not values:
        return
    rows = [
        {
            "org_id": org_id,
            "team_id": team_id,
            "user_id": user_id,
            "grain": grain,
            "period_start": period_start,
            "metric_key": key,
            "value": Decimal(str(round(float(value), 4))),
            "computed_at": datetime.now(UTC),
        }
        for key, value in values.items()
    ]
    stmt = insert(MetricRollup).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            MetricRollup.org_id,
            MetricRollup.team_id,
            MetricRollup.user_id,
            MetricRollup.grain,
            MetricRollup.period_start,
            MetricRollup.metric_key,
        ],
        set_={"value": stmt.excluded.value, "computed_at": stmt.excluded.computed_at},
    )
    db.execute(stmt)


def team_values(
    db: DbSession,
    org: Organization,
    team: Team,
    window_start: datetime,
    window_end: datetime,
    config: MetricsConfig,
) -> dict[str, float]:
    """Metrics for an arbitrary window. Rollups call this per bucket; the API
    calls it directly for a date range, so a 30-day total is computed from the
    events themselves rather than by averaging 30 daily rates."""
    window_days = max((window_end - window_start).total_seconds() / 86400, 0.0)
    tz_by_user = _timezone_map(db, org, team)
    team_tz = resolve_timezone(team.timezone, org.timezone)

    page_rows = db.scalars(
        select(IncidentPage).where(
            IncidentPage.org_id == org.id,
            IncidentPage.team_id == team.id,
            IncidentPage.paged_at >= window_start,
            IncidentPage.paged_at < window_end,
        )
    ).all()
    pages = [
        PageEvent(
            user_id=str(p.user_id) if p.user_id else None,
            paged_at=p.paged_at,
            timezone=tz_by_user.get(p.user_id, team_tz),
            is_ack=p.is_ack,
        )
        for p in page_rows
    ]

    incident_rows = db.scalars(
        select(Incident).where(
            Incident.org_id == org.id,
            Incident.team_id == team.id,
            Incident.created_at_ext >= window_start,
            Incident.created_at_ext < window_end,
        )
    ).all()
    incidents = [
        IncidentEvent(created_at=i.created_at_ext, resolved_at=i.resolved_at) for i in incident_rows
    ]

    deploy_rows = db.scalars(
        select(Deploy).where(
            Deploy.org_id == org.id,
            Deploy.team_id == team.id,
            Deploy.deployed_at >= window_start,
            Deploy.deployed_at < window_end,
        )
    ).all()
    deploys = [
        DeployEvent(
            deployed_at=d.deployed_at,
            repo_full_name=d.repo_full_name,
            status=d.status,
            is_rollback=d.is_rollback,
        )
        for d in deploy_rows
    ]

    # Incidents just past the window edge still count against a deploy near the
    # end of it, otherwise every bucket boundary would hide a failure.
    lookahead_end = window_end + timedelta(minutes=config.change_failure_window_minutes)
    incidents_for_cfr = db.scalars(
        select(Incident.created_at_ext).where(
            Incident.org_id == org.id,
            Incident.team_id == team.id,
            Incident.created_at_ext >= window_start,
            Incident.created_at_ext < lookahead_end,
        )
    ).all()

    values: dict[str, float] = {}
    values.update(page_metrics(pages, config.working_hours))
    values.update(resolution_metrics(incidents))
    values.update(deploy_metrics(deploys, window_days))
    values["pages_per_person_per_week"] = pages_per_person_per_week(
        pages, _team_headcount(db, team.id), window_days
    )
    values["change_failure_rate"] = change_failure_rate(
        deploys,
        [IncidentEvent(created_at=t, resolved_at=None) for t in incidents_for_cfr],
        config.change_failure_window_minutes,
    )
    values[TOIL_METRIC_KEY] = toil_score(values, config)
    return values


def compute_team_rollup(
    db: DbSession,
    org: Organization,
    team: Team,
    grain: str,
    period_start: date,
    config: MetricsConfig,
) -> dict[str, float]:
    window_start, window_end = period_bounds(grain, period_start)
    values = team_values(db, org, team, window_start, window_end, config)
    _upsert(db, org.id, team.id, None, grain, period_start, values)
    return values


def person_values(
    db: DbSession,
    org: Organization,
    user_id: uuid.UUID,
    tz_name: str,
    window_start: datetime,
    window_end: datetime,
    config: MetricsConfig,
) -> dict[str, float]:
    page_rows = db.scalars(
        select(IncidentPage).where(
            IncidentPage.org_id == org.id,
            IncidentPage.user_id == user_id,
            IncidentPage.paged_at >= window_start,
            IncidentPage.paged_at < window_end,
        )
    ).all()
    pages = [
        PageEvent(user_id=str(user_id), paged_at=p.paged_at, timezone=tz_name, is_ack=p.is_ack)
        for p in page_rows
    ]

    shift_rows = db.execute(
        select(OnCallShift.starts_at, OnCallShift.ends_at).where(
            OnCallShift.org_id == org.id,
            OnCallShift.user_id == user_id,
            OnCallShift.starts_at < window_end,
            OnCallShift.ends_at > window_start,
        )
    ).all()

    values = page_metrics(pages, config.working_hours)
    values["on_call_hours"] = on_call_hours(
        [(s, e) for s, e in shift_rows], window_start, window_end
    )
    return values


def person_timezone(db: DbSession, org: Organization, user_id: uuid.UUID) -> str:
    """A person's own zone wins; otherwise the first team they belong to."""
    user = db.get(User, user_id)
    team = db.scalar(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id)
        .limit(1)
    )
    return resolve_timezone(
        user.timezone if user else None, team.timezone if team else None, org.timezone
    )


def compute_person_rollups(
    db: DbSession,
    org: Organization,
    team: Team,
    grain: str,
    period_start: date,
    config: MetricsConfig,
) -> int:
    window_start, window_end = period_bounds(grain, period_start)
    tz_by_user = _timezone_map(db, org, team)
    team_tz = resolve_timezone(team.timezone, org.timezone)

    member_ids = db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == team.id)).all()

    for user_id in member_ids:
        values = person_values(
            db,
            org,
            user_id,
            tz_by_user.get(user_id, team_tz),
            window_start,
            window_end,
            config,
        )
        _upsert(db, org.id, team.id, user_id, grain, period_start, values)

    return len(member_ids)


def compute_org_rollups(
    db: DbSession,
    org_id: uuid.UUID,
    grain: str,
    period_start: date,
    config: MetricsConfig | None = None,
) -> int:
    config = config or get_metrics_config()
    org = db.get(Organization, org_id)
    if org is None:
        return 0

    teams = db.scalars(select(Team).where(Team.org_id == org_id)).all()
    for team in teams:
        compute_team_rollup(db, org, team, grain, period_start, config)
        compute_person_rollups(db, org, team, grain, period_start, config)
    db.commit()
    return len(teams)


def backfill(
    db: DbSession, org_id: uuid.UUID, days: int = 90, config: MetricsConfig | None = None
) -> int:
    """Recomputes every daily bucket in the window plus the weeks covering it."""
    config = config or get_metrics_config()
    today = datetime.now(UTC).date()
    periods = 0

    for offset in range(days, -1, -1):
        compute_org_rollups(db, org_id, "day", today - timedelta(days=offset), config)
        periods += 1

    weeks = {week_start(today - timedelta(days=offset)) for offset in range(days, -1, -1)}
    for start in sorted(weeks):
        compute_org_rollups(db, org_id, "week", start, config)
        periods += 1

    return periods
