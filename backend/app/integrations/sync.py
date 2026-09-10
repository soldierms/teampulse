"""Persists normalized provider data. Provider-agnostic by design — it only
speaks the shapes in integrations.base.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession

from app.integrations.base import (
    GH_REPO,
    PD_SCHEDULE,
    PD_SERVICE,
    NormalizedDeploy,
    NormalizedIncident,
    NormalizedShift,
    NormalizedUser,
)
from app.models.events import Deploy, Incident, IncidentPage, OnCallShift
from app.models.integration import ExternalIdentity, Integration, SyncRun, TeamResource
from app.models.org import User

log = logging.getLogger(__name__)

DEFAULT_BACKFILL_DAYS = 90


class TeamIndex:
    """Resolves provider resource ids to the team that claimed them."""

    def __init__(self, db: DbSession, org_id: uuid.UUID, provider: str) -> None:
        rows = db.scalars(
            select(TeamResource).where(
                TeamResource.org_id == org_id, TeamResource.provider == provider
            )
        ).all()
        self._by_resource = {(r.resource_type, r.external_id): r.team_id for r in rows}

    def team_for(self, resource_type: str, external_id: str | None) -> uuid.UUID | None:
        if external_id is None:
            return None
        return self._by_resource.get((resource_type, external_id))


class IdentityIndex:
    """Resolves provider user ids to TeamPulse users."""

    def __init__(self, db: DbSession, org_id: uuid.UUID, provider: str) -> None:
        rows = db.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.org_id == org_id, ExternalIdentity.provider == provider
            )
        ).all()
        self._by_external = {r.external_id: r.user_id for r in rows}

    def user_for(self, external_id: str | None) -> uuid.UUID | None:
        if external_id is None:
            return None
        return self._by_external.get(external_id)


def sync_identities(db: DbSession, integration: Integration, users: list[NormalizedUser]) -> int:
    """Upserts provider users and auto-links them to org users by email.
    Unmatched identities still land, so an admin can claim them in settings."""
    if not users:
        return 0

    org_users = db.scalars(select(User).where(User.org_id == integration.org_id)).all()
    by_email = {u.email.lower(): u.id for u in org_users}

    rows = [
        {
            "org_id": integration.org_id,
            "provider": integration.provider,
            "external_id": u.external_id,
            "external_handle": u.handle,
            "email": u.email,
            "user_id": by_email.get((u.email or "").lower()),
        }
        for u in users
    ]

    stmt = insert(ExternalIdentity).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            ExternalIdentity.org_id,
            ExternalIdentity.provider,
            ExternalIdentity.external_id,
        ],
        set_={
            "external_handle": stmt.excluded.external_handle,
            "email": stmt.excluded.email,
            # Existing link wins — an auto-match must never overwrite a manual claim.
            "user_id": func.coalesce(ExternalIdentity.user_id, stmt.excluded.user_id),
        },
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def sync_incidents(
    db: DbSession, integration: Integration, incidents: list[NormalizedIncident]
) -> int:
    teams = TeamIndex(db, integration.org_id, integration.provider)
    identities = IdentityIndex(db, integration.org_id, integration.provider)
    count = 0

    for incident in incidents:
        team_id = teams.team_for(PD_SERVICE, incident.service_external_id)
        stmt = insert(Incident).values(
            org_id=integration.org_id,
            integration_id=integration.id,
            provider=integration.provider,
            external_id=incident.external_id,
            team_id=team_id,
            service_external_id=incident.service_external_id,
            service_name=incident.service_name,
            title=incident.title,
            urgency=incident.urgency,
            severity=incident.severity,
            status=incident.status,
            created_at_ext=incident.created_at,
            acknowledged_at=incident.acknowledged_at,
            resolved_at=incident.resolved_at,
            raw=incident.raw,
            synced_at=datetime.now(UTC),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Incident.org_id, Incident.provider, Incident.external_id],
            set_={
                "team_id": stmt.excluded.team_id,
                "status": stmt.excluded.status,
                "acknowledged_at": stmt.excluded.acknowledged_at,
                "resolved_at": stmt.excluded.resolved_at,
                "severity": stmt.excluded.severity,
                "raw": stmt.excluded.raw,
                "synced_at": stmt.excluded.synced_at,
            },
        ).returning(Incident.id)
        incident_id = db.execute(stmt).scalar_one()
        count += 1

        if incident.pages:
            page_rows = [
                {
                    "org_id": integration.org_id,
                    "incident_id": incident_id,
                    "provider": integration.provider,
                    "external_id": page.external_id,
                    "user_id": identities.user_for(page.external_user_id),
                    "external_user_id": page.external_user_id,
                    "team_id": team_id,
                    "paged_at": page.paged_at,
                    "channel": page.channel,
                    "is_ack": page.is_ack,
                }
                for page in incident.pages
            ]
            page_stmt = insert(IncidentPage).values(page_rows)
            page_stmt = page_stmt.on_conflict_do_update(
                index_elements=[
                    IncidentPage.org_id,
                    IncidentPage.provider,
                    IncidentPage.external_id,
                ],
                set_={
                    "user_id": page_stmt.excluded.user_id,
                    "team_id": page_stmt.excluded.team_id,
                    "is_ack": page_stmt.excluded.is_ack,
                },
            )
            db.execute(page_stmt)

    db.commit()
    return count


def sync_shifts(db: DbSession, integration: Integration, shifts: list[NormalizedShift]) -> int:
    if not shifts:
        return 0

    teams = TeamIndex(db, integration.org_id, integration.provider)
    identities = IdentityIndex(db, integration.org_id, integration.provider)

    rows = [
        {
            "org_id": integration.org_id,
            "integration_id": integration.id,
            "provider": integration.provider,
            "external_id": shift.external_id,
            "schedule_external_id": shift.schedule_external_id,
            "schedule_name": shift.schedule_name,
            "user_id": identities.user_for(shift.external_user_id),
            "external_user_id": shift.external_user_id,
            "team_id": teams.team_for(PD_SCHEDULE, shift.schedule_external_id),
            "starts_at": shift.starts_at,
            "ends_at": shift.ends_at,
            "raw": shift.raw,
        }
        for shift in shifts
    ]

    stmt = insert(OnCallShift).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[OnCallShift.org_id, OnCallShift.provider, OnCallShift.external_id],
        set_={
            "user_id": stmt.excluded.user_id,
            "team_id": stmt.excluded.team_id,
            "ends_at": stmt.excluded.ends_at,
            "schedule_name": stmt.excluded.schedule_name,
        },
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def sync_deploys(db: DbSession, integration: Integration, deploys: list[NormalizedDeploy]) -> int:
    if not deploys:
        return 0

    teams = TeamIndex(db, integration.org_id, integration.provider)
    identities = IdentityIndex(db, integration.org_id, integration.provider)

    rows = [
        {
            "org_id": integration.org_id,
            "integration_id": integration.id,
            "provider": integration.provider,
            "external_id": d.external_id,
            "repo_full_name": d.repo_full_name,
            "team_id": teams.team_for(GH_REPO, d.repo_full_name),
            "environment": d.environment,
            "sha": d.sha,
            "ref": d.ref,
            "deployed_at": d.deployed_at,
            "status": d.status,
            "actor_user_id": identities.user_for(d.actor_external_id),
            "actor_external_id": d.actor_external_id,
            "pr_number": d.pr_number,
            "pr_merged_at": d.pr_merged_at,
            "is_rollback": d.is_rollback,
            "reverts_sha": d.reverts_sha,
            "raw": d.raw,
        }
        for d in deploys
    ]

    stmt = insert(Deploy).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Deploy.org_id, Deploy.provider, Deploy.external_id],
        set_={
            "team_id": stmt.excluded.team_id,
            "status": stmt.excluded.status,
            "actor_user_id": stmt.excluded.actor_user_id,
            "is_rollback": stmt.excluded.is_rollback,
            "reverts_sha": stmt.excluded.reverts_sha,
        },
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


def last_watermark(db: DbSession, integration: Integration) -> datetime:
    row = db.scalar(
        select(SyncRun)
        .where(SyncRun.integration_id == integration.id, SyncRun.status == "success")
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )
    if row is not None and row.watermark is not None:
        # Re-pull a short overlap so incidents that resolved after the last run
        # get their final timestamps.
        return row.watermark - timedelta(hours=2)
    return datetime.now(UTC) - timedelta(days=DEFAULT_BACKFILL_DAYS)
