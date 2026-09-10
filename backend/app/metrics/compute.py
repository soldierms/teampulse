"""Pure metric math.

Every function here takes plain values and returns plain values — no database,
no ORM, no clock. That is what makes the numbers testable, and these are the
numbers customers make staffing decisions on.
"""

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.metrics.config import WorkingHours
from app.metrics.windows import is_after_hours, is_weekend

MINUTES_PER_WEEK = 7 * 24 * 60


@dataclass(frozen=True, slots=True)
class PageEvent:
    user_id: str | None
    paged_at: datetime
    timezone: str
    is_ack: bool = False


@dataclass(frozen=True, slots=True)
class IncidentEvent:
    created_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class DeployEvent:
    deployed_at: datetime
    repo_full_name: str
    status: str = "success"
    is_rollback: bool = False


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile. Chosen over interpolation because the result is
    always an observed value — 'p95 is 47 minutes' refers to a real incident."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _safe_rate(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def page_metrics(pages: list[PageEvent], hours: WorkingHours) -> dict[str, float]:
    """Acknowledgement events are excluded — being woken up is the burden, and
    counting the ack too would double-count every page one person answered."""
    notifications = [p for p in pages if not p.is_ack]
    total = len(notifications)
    after_hours = sum(1 for p in notifications if is_after_hours(p.paged_at, p.timezone, hours))
    weekend = sum(1 for p in notifications if is_weekend(p.paged_at, p.timezone, hours))

    return {
        "pages_total": float(total),
        "pages_after_hours": float(after_hours),
        "pages_weekend": float(weekend),
        "after_hours_page_rate": _safe_rate(after_hours, total),
        "weekend_page_rate": _safe_rate(weekend, total),
    }


def pages_per_person_per_week(pages: list[PageEvent], headcount: int, window_days: float) -> float:
    """Counts only pages we could attribute to a person — an unmatched provider
    identity would otherwise deflate the per-person average."""
    attributed = [p for p in pages if not p.is_ack and p.user_id is not None]
    if not headcount or window_days <= 0:
        return 0.0
    weeks = window_days / 7
    return _safe_rate(len(attributed), headcount * weeks)


def resolution_metrics(incidents: list[IncidentEvent]) -> dict[str, float]:
    durations = [
        (i.resolved_at - i.created_at).total_seconds() / 60
        for i in incidents
        if i.resolved_at is not None and i.resolved_at >= i.created_at
    ]
    return {
        "incidents_total": float(len(incidents)),
        "incidents_resolved": float(len(durations)),
        "mean_resolution_minutes": _safe_rate(sum(durations), len(durations)),
        "p95_resolution_minutes": percentile(durations, 0.95),
    }


def deploy_metrics(deploys: list[DeployEvent], window_days: float) -> dict[str, float]:
    weeks = window_days / 7 if window_days > 0 else 0
    return {
        "deploys_total": float(len(deploys)),
        "deploy_frequency_per_week": _safe_rate(len(deploys), weeks),
    }


def _has_event_in(sorted_times: list[datetime], start: datetime, end: datetime) -> bool:
    """Half-open (start, end]: an event at the exact deploy instant did not follow it."""
    index = bisect_right(sorted_times, start)
    return index < len(sorted_times) and sorted_times[index] <= end


def _has_event_within(sorted_times: list[datetime], start: datetime, end: datetime) -> bool:
    """Closed [start, end] — used for incidents, where one opening at the deploy
    timestamp is still that deploy's fault."""
    index = bisect_left(sorted_times, start)
    return index < len(sorted_times) and sorted_times[index] <= end


def change_failure_rate(
    deploys: list[DeployEvent],
    incidents: list[IncidentEvent],
    window_minutes: int,
) -> float:
    """A deploy counts as failed if it failed outright, was rolled back in the
    same repo inside the window, or was followed by an incident on the team."""
    if not deploys:
        return 0.0

    window = timedelta(minutes=window_minutes)
    rollbacks_by_repo: dict[str, list[datetime]] = defaultdict(list)
    for deploy in deploys:
        if deploy.is_rollback:
            rollbacks_by_repo[deploy.repo_full_name].append(deploy.deployed_at)
    for times in rollbacks_by_repo.values():
        times.sort()

    incident_times = sorted(i.created_at for i in incidents)

    failures = 0
    for deploy in deploys:
        if deploy.status == "failure":
            failures += 1
            continue
        end = deploy.deployed_at + window
        rolled_back = _has_event_in(
            rollbacks_by_repo.get(deploy.repo_full_name, []), deploy.deployed_at, end
        )
        caused_incident = _has_event_within(incident_times, deploy.deployed_at, end)
        if rolled_back or caused_incident:
            failures += 1

    return failures / len(deploys)


def on_call_hours(
    shifts: list[tuple[datetime, datetime]], window_start: datetime, window_end: datetime
) -> float:
    """Shift time that overlaps the reporting window, so a weekly rotation
    straddling the edge is not counted twice."""
    total = 0.0
    for starts_at, ends_at in shifts:
        start = max(starts_at, window_start)
        end = min(ends_at, window_end)
        if end > start:
            total += (end - start).total_seconds() / 3600
    return total
