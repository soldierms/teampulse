import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from app.metrics.config import get_metrics_config
from app.metrics.rollups import person_timezone, person_values, team_values, week_start
from app.models.metrics import MetricRollup
from app.models.org import Organization, Team, TeamMember, User
from app.schemas.metrics import (
    MemberLoad,
    MetricSeries,
    OrgOverview,
    PersonDetail,
    TeamDetail,
    TeamOverview,
    TrendPoint,
)

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

ALLOWED_RANGES = {7, 30, 90}

TEAM_SERIES_KEYS = [
    "pages_total",
    "pages_after_hours",
    "after_hours_page_rate",
    "deploys_total",
    "change_failure_rate",
    "p95_resolution_minutes",
    "toil_score",
]

PERSON_SERIES_KEYS = [
    "pages_total",
    "pages_after_hours",
    "after_hours_page_rate",
    "on_call_hours",
]

# Rates and scores are averaged over the window; everything else is a count.
AVERAGED_KEYS = {
    "after_hours_page_rate",
    "weekend_page_rate",
    "change_failure_rate",
    "toil_score",
    "p95_resolution_minutes",
    "mean_resolution_minutes",
    "pages_per_person_per_week",
    "deploy_frequency_per_week",
}


def _validate_days(days: int) -> int:
    if days not in ALLOWED_RANGES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"days must be one of {sorted(ALLOWED_RANGES)}"
        )
    return days


def _week_metrics(db, org_id: uuid.UUID, start) -> dict[uuid.UUID, dict[str, float]]:
    rows = db.execute(
        select(MetricRollup.team_id, MetricRollup.metric_key, MetricRollup.value).where(
            MetricRollup.org_id == org_id,
            MetricRollup.user_id.is_(None),
            MetricRollup.team_id.is_not(None),
            MetricRollup.grain == "week",
            MetricRollup.period_start == start,
        )
    ).all()
    out: dict[uuid.UUID, dict[str, float]] = defaultdict(dict)
    for team_id, key, value in rows:
        out[team_id][key] = float(value)
    return out


@router.get("/overview", response_model=OrgOverview)
def org_overview(user: CurrentUser, db: DbDep) -> OrgOverview:
    this_week = week_start(datetime.now(UTC).date())
    last_week = this_week - timedelta(days=7)

    current = _week_metrics(db, user.org_id, this_week)
    previous = _week_metrics(db, user.org_id, last_week)
    teams = db.scalars(select(Team).where(Team.org_id == user.org_id).order_by(Team.name)).all()

    out = []
    for team in teams:
        now_values = current.get(team.id, {})
        prev_values = previous.get(team.id, {})
        toil = now_values.get("toil_score", 0.0)
        toil_prev = prev_values.get("toil_score", 0.0)
        # A point of toil either way is noise, not a trend worth an arrow.
        if abs(toil - toil_prev) < 1.0:
            trend = "flat"
        else:
            trend = "up" if toil > toil_prev else "down"

        out.append(
            TeamOverview(
                team_id=team.id,
                team_name=team.name,
                toil_score=toil,
                toil_score_previous=toil_prev,
                trend=trend,
                pages_total=now_values.get("pages_total", 0.0),
                after_hours_page_rate=now_values.get("after_hours_page_rate", 0.0),
                change_failure_rate=now_values.get("change_failure_rate", 0.0),
                deploy_frequency_per_week=now_values.get("deploy_frequency_per_week", 0.0),
            )
        )

    return OrgOverview(week_start=this_week, teams=out)


def _combine(key: str, values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values) if key in AVERAGED_KEYS else sum(values)


def _series(rows, keys: list[str]) -> list[MetricSeries]:
    """Daily points for the charts. Totals never come from here — they are
    recomputed over the whole window so a rate is not an average of rates."""
    # A person on two teams has one rollup row per team per day, so collapse by
    # date before charting — averaging rates, summing counts.
    buckets: dict[tuple[str, object], list[float]] = defaultdict(list)
    for period_start, metric_key, value in rows:
        buckets[(metric_key, period_start)].append(float(value))

    by_key: dict[str, list[TrendPoint]] = defaultdict(list)
    for (metric_key, period_start), values in buckets.items():
        by_key[metric_key].append(
            TrendPoint(period_start=period_start, value=_combine(metric_key, values))
        )

    return [
        MetricSeries(
            metric_key=key, points=sorted(by_key.get(key, []), key=lambda p: p.period_start)
        )
        for key in keys
    ]


def _window(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(UTC)
    start = datetime.combine(end.date() - timedelta(days=days), datetime.min.time(), tzinfo=UTC)
    return start, end


@router.get("/teams/{team_id}", response_model=TeamDetail)
def team_detail(
    team_id: uuid.UUID,
    user: CurrentUser,
    db: DbDep,
    days: int = Query(30),
) -> TeamDetail:
    _validate_days(days)
    team = db.scalar(select(Team).where(Team.id == team_id, Team.org_id == user.org_id))
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")

    since = datetime.now(UTC).date() - timedelta(days=days)
    rows = db.execute(
        select(MetricRollup.period_start, MetricRollup.metric_key, MetricRollup.value).where(
            MetricRollup.org_id == user.org_id,
            MetricRollup.team_id == team_id,
            MetricRollup.user_id.is_(None),
            MetricRollup.grain == "day",
            MetricRollup.period_start >= since,
        )
    ).all()
    series = _series(rows, TEAM_SERIES_KEYS)

    org = db.get(Organization, user.org_id)
    window_start, window_end = _window(days)
    totals = team_values(db, org, team, window_start, window_end, get_metrics_config())

    member_rows = (
        db.execute(
            select(User)
            .join(TeamMember, TeamMember.user_id == User.id)
            .where(TeamMember.team_id == team_id)
        )
        .scalars()
        .all()
    )

    person_rows = db.execute(
        select(MetricRollup.user_id, MetricRollup.metric_key, MetricRollup.value).where(
            MetricRollup.org_id == user.org_id,
            MetricRollup.team_id == team_id,
            MetricRollup.user_id.is_not(None),
            MetricRollup.grain == "day",
            MetricRollup.period_start >= since,
        )
    ).all()

    per_person: dict[uuid.UUID, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for user_id, key, value in person_rows:
        per_person[user_id][key] += float(value)

    members = []
    for member in sorted(member_rows, key=lambda m: m.name):
        totals_for = per_person.get(member.id, {})
        pages = totals_for.get("pages_total", 0.0)
        after_hours = totals_for.get("pages_after_hours", 0.0)
        members.append(
            MemberLoad(
                user_id=member.id,
                name=member.name,
                email=member.email,
                pages_total=pages,
                pages_after_hours=after_hours,
                after_hours_page_rate=(after_hours / pages) if pages else 0.0,
                on_call_hours=totals_for.get("on_call_hours", 0.0),
            )
        )

    return TeamDetail(
        team_id=team.id,
        team_name=team.name,
        days=days,
        totals=totals,
        series=series,
        members=sorted(members, key=lambda m: m.pages_total, reverse=True),
    )


@router.get("/people/{user_id}", response_model=PersonDetail)
def person_detail(
    user_id: uuid.UUID,
    user: CurrentUser,
    db: DbDep,
    days: int = Query(30),
) -> PersonDetail:
    _validate_days(days)
    person = db.scalar(select(User).where(User.id == user_id, User.org_id == user.org_id))
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    since = datetime.now(UTC).date() - timedelta(days=days)
    rows = db.execute(
        select(MetricRollup.period_start, MetricRollup.metric_key, MetricRollup.value).where(
            MetricRollup.org_id == user.org_id,
            MetricRollup.user_id == user_id,
            MetricRollup.grain == "day",
            MetricRollup.period_start >= since,
        )
    ).all()
    series = _series(rows, PERSON_SERIES_KEYS)

    org = db.get(Organization, user.org_id)
    window_start, window_end = _window(days)
    totals = person_values(
        db,
        org,
        person.id,
        person_timezone(db, org, person.id),
        window_start,
        window_end,
        get_metrics_config(),
    )

    return PersonDetail(
        user_id=person.id,
        name=person.name,
        email=person.email,
        days=days,
        totals=totals,
        series=series,
    )
