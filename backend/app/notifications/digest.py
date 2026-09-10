"""Builds the weekly team digest from stored rollups — no recomputation, so the
email always says exactly what the dashboard says."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models.metrics import MetricRollup
from app.models.org import Team
from app.notifications.base import Message

HEADLINE_METRICS = [
    ("toil_score", "Toil score", "{:.0f}/100"),
    ("pages_total", "Pages", "{:.0f}"),
    ("after_hours_page_rate", "After-hours pages", "{:.0%}"),
    ("deploy_frequency_per_week", "Deploys", "{:.0f}"),
    ("change_failure_rate", "Change failure rate", "{:.0%}"),
    ("p95_resolution_minutes", "p95 time to resolve", "{:.0f} min"),
]


@dataclass(slots=True)
class MetricLine:
    label: str
    current: float
    previous: float
    formatted: str

    @property
    def delta_pct(self) -> float | None:
        if self.previous == 0:
            return None
        return (self.current - self.previous) / self.previous * 100

    @property
    def direction(self) -> str:
        if self.current > self.previous:
            return "up"
        if self.current < self.previous:
            return "down"
        return "flat"


def _week_values(
    db: DbSession, org_id: uuid.UUID, team_id: uuid.UUID, start: date
) -> dict[str, float]:
    rows = db.execute(
        select(MetricRollup.metric_key, MetricRollup.value).where(
            MetricRollup.org_id == org_id,
            MetricRollup.team_id == team_id,
            MetricRollup.user_id.is_(None),
            MetricRollup.grain == "week",
            MetricRollup.period_start == start,
        )
    ).all()
    return {key: float(value) for key, value in rows}


def build_lines(current: dict[str, float], previous: dict[str, float]) -> list[MetricLine]:
    lines = []
    for key, label, fmt in HEADLINE_METRICS:
        value = current.get(key, 0.0)
        lines.append(
            MetricLine(
                label=label,
                current=value,
                previous=previous.get(key, 0.0),
                formatted=fmt.format(value),
            )
        )
    return lines


def _headline(team_name: str, lines: list[MetricLine]) -> str:
    pages = next(line for line in lines if line.label == "Pages")
    after_hours = next(line for line in lines if line.label == "After-hours pages")

    if pages.previous == 0 and pages.current == 0:
        return f"{team_name}: a quiet week — no pages at all."

    delta = pages.delta_pct
    if delta is None:
        movement = f"{pages.current:.0f} pages this week"
    elif abs(delta) < 10:
        movement = f"pages held steady at {pages.current:.0f}"
    else:
        movement = f"pages {'up' if delta > 0 else 'down'} {abs(delta):.0f}% to {pages.current:.0f}"

    tail = f", {after_hours.current:.0%} of them after hours" if after_hours.current >= 0.25 else ""
    return f"{team_name}: {movement}{tail}."


def build_team_digest(
    db: DbSession, org_id: uuid.UUID, team: Team, week_start_date: date, recipients: list[str]
) -> Message:
    current = _week_values(db, org_id, team.id, week_start_date)
    previous = _week_values(db, org_id, team.id, week_start_date - timedelta(days=7))
    lines = build_lines(current, previous)
    headline = _headline(team.name, lines)

    arrows = {"up": "^", "down": "v", "flat": "-"}
    text_rows = "\n".join(
        f"  {arrows[line.direction]} {line.label}: {line.formatted}"
        + (f" ({line.delta_pct:+.0f}% vs last week)" if line.delta_pct is not None else "")
        for line in lines
    )
    text_body = (
        f"{headline}\n\nWeek of {week_start_date:%d %b %Y}\n\n{text_rows}\n\n"
        "Open TeamPulse for the full breakdown."
    )

    html_rows = "".join(
        f"<tr><td style='padding:6px 12px 6px 0'>{escape(line.label)}</td>"
        f"<td style='padding:6px 0;font-weight:600'>{escape(line.formatted)}</td>"
        f"<td style='padding:6px 0 6px 12px;color:#6b7280'>"
        f"{f'{line.delta_pct:+.0f}%' if line.delta_pct is not None else '—'}</td></tr>"
        for line in lines
    )
    html_body = (
        f"<div style='font-family:system-ui,sans-serif;max-width:520px'>"
        f"<p style='font-size:16px'>{escape(headline)}</p>"
        f"<p style='color:#6b7280;font-size:13px'>Week of {week_start_date:%d %b %Y}</p>"
        f"<table style='border-collapse:collapse;font-size:14px'>{html_rows}</table></div>"
    )

    return Message(
        subject=f"TeamPulse — {team.name}, week of {week_start_date:%d %b}",
        text_body=text_body,
        html_body=html_body,
        recipients=recipients,
    )
