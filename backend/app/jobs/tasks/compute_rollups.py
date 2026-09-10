import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.metrics.rollups import backfill, compute_org_rollups, week_start

log = logging.getLogger(__name__)


def handle(db: DbSession, payload: dict) -> int:
    """Recomputes recent buckets. Yesterday is included because incidents that
    resolve after midnight change that day's resolution numbers."""
    org_id = uuid.UUID(payload["org_id"])

    if payload.get("backfill"):
        return backfill(db, org_id, days=int(payload.get("days", 90)))

    today = datetime.now(UTC).date()
    for day in (today, today - timedelta(days=1)):
        compute_org_rollups(db, org_id, "day", day)

    compute_org_rollups(db, org_id, "week", week_start(today))
    compute_org_rollups(db, org_id, "week", week_start(today - timedelta(days=7)))
    return 4
