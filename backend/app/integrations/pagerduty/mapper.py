"""Pure PagerDuty payload -> normalized shape translation. No HTTP here, so it
is testable against recorded fixtures."""

from datetime import UTC, datetime

from app.integrations.base import (
    PD_SCHEDULE,
    PD_SERVICE,
    NormalizedIncident,
    NormalizedPage,
    NormalizedResource,
    NormalizedShift,
    NormalizedUser,
)

NOTIFY_ENTRY = "notify_log_entry"
ACK_ENTRY = "acknowledge_log_entry"


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def map_user(payload: dict) -> NormalizedUser:
    return NormalizedUser(
        external_id=payload["id"],
        handle=payload.get("summary") or payload.get("name"),
        email=(payload.get("email") or "").lower() or None,
        name=payload.get("name"),
    )


def map_service(payload: dict) -> NormalizedResource:
    return NormalizedResource(
        resource_type=PD_SERVICE,
        external_id=payload["id"],
        name=payload.get("name") or payload.get("summary") or payload["id"],
    )


def map_schedule(payload: dict) -> NormalizedResource:
    return NormalizedResource(
        resource_type=PD_SCHEDULE,
        external_id=payload["id"],
        name=payload.get("name") or payload.get("summary") or payload["id"],
    )


def map_pages(incident_id: str, log_entries: list[dict]) -> list[NormalizedPage]:
    """One page per notification sent to a person. Acknowledgement entries are
    folded in as is_ack so we can tell 'was woken up' from 'responded'."""
    pages: list[NormalizedPage] = []
    for entry in log_entries:
        entry_type = entry.get("type", "")
        if entry_type not in (NOTIFY_ENTRY, ACK_ENTRY):
            continue
        agent = entry.get("user") or entry.get("agent") or {}
        paged_at = parse_ts(entry.get("created_at"))
        if paged_at is None:
            continue
        pages.append(
            NormalizedPage(
                external_id=entry.get("id") or f"{incident_id}:{entry_type}:{paged_at.isoformat()}",
                external_user_id=agent.get("id"),
                paged_at=paged_at,
                channel=(entry.get("channel") or {}).get("type"),
                is_ack=entry_type == ACK_ENTRY,
            )
        )
    return pages


def map_incident(payload: dict, log_entries: list[dict] | None = None) -> NormalizedIncident:
    status = payload.get("status", "triggered")
    acks = payload.get("acknowledgements") or []
    resolved_at = parse_ts(payload.get("resolved_at"))
    if resolved_at is None and status == "resolved":
        # Older API responses omit resolved_at; the last transition is the resolve.
        resolved_at = parse_ts(payload.get("last_status_change_at"))

    service = payload.get("service") or {}
    priority = payload.get("priority") or {}

    return NormalizedIncident(
        external_id=payload["id"],
        title=payload.get("title") or payload.get("summary") or "(untitled incident)",
        status=status,
        created_at=parse_ts(payload["created_at"]),
        service_external_id=service.get("id"),
        service_name=service.get("summary") or service.get("name"),
        urgency=payload.get("urgency"),
        severity=priority.get("summary"),
        acknowledged_at=parse_ts(acks[0]["at"]) if acks else None,
        resolved_at=resolved_at,
        pages=map_pages(payload["id"], log_entries or []),
        raw=payload,
    )


def map_oncall(payload: dict) -> NormalizedShift | None:
    """PD /oncalls entries without a start/end are permanent escalation-policy
    memberships, not shifts — those carry no on-call burden signal."""
    starts_at = parse_ts(payload.get("start"))
    ends_at = parse_ts(payload.get("end"))
    if starts_at is None or ends_at is None:
        return None

    user = payload.get("user") or {}
    schedule = payload.get("schedule") or {}
    schedule_id = schedule.get("id")
    return NormalizedShift(
        external_id=f"{schedule_id or 'noschedule'}:{user.get('id')}:{starts_at.isoformat()}",
        external_user_id=user.get("id"),
        starts_at=starts_at,
        ends_at=ends_at,
        schedule_external_id=schedule_id,
        schedule_name=schedule.get("summary") or schedule.get("name"),
        raw=payload,
    )
