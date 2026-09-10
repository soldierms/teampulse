import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import get_settings
from app.metrics.rollups import week_start
from app.models.org import Team, TeamMember, User
from app.notifications.digest import build_team_digest
from app.notifications.senders import get_notifier

log = logging.getLogger(__name__)


def _recipients(db: DbSession, team_id: uuid.UUID) -> list[str]:
    rows = db.scalars(
        select(User.email)
        .join(TeamMember, TeamMember.user_id == User.id)
        .where(TeamMember.team_id == team_id, User.is_active.is_(True))
    ).all()
    return list(rows)


def handle(db: DbSession, payload: dict) -> int:
    """Sends one digest per team for the week that just ended."""
    org_id = uuid.UUID(payload["org_id"])
    target_week = (
        datetime.fromisoformat(payload["week_start"]).date()
        if payload.get("week_start")
        else week_start(datetime.now(UTC).date() - timedelta(days=7))
    )

    notifier = get_notifier(get_settings())
    teams = db.scalars(select(Team).where(Team.org_id == org_id)).all()

    sent = 0
    for team in teams:
        message = build_team_digest(db, org_id, team, target_week, _recipients(db, team.id))
        try:
            notifier.send(message)
            sent += 1
        except Exception:
            # One team's bad address must not block the rest of the org's digests.
            log.exception("digest failed for team %s", team.name)

    return sent
