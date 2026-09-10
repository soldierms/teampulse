"""Single-process job worker: claims jobs with SKIP LOCKED, runs them, and
schedules the recurring work. Run more than one for throughput — claiming is safe."""

import logging
import os
import socket
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import get_settings
from app.db import SessionLocal
from app.jobs import queue
from app.jobs.tasks import compute_rollups, sync_integrations, weekly_digest
from app.metrics.rollups import week_start
from app.models.integration import Integration
from app.models.org import Organization

log = logging.getLogger(__name__)

HANDLERS = {
    "sync_integration": sync_integrations.handle,
    "compute_rollups": compute_rollups.handle,
    "weekly_digest": weekly_digest.handle,
}

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def schedule_due_work(db: DbSession) -> None:
    """Enqueues syncs and rollups on a fixed cadence. The dedupe key is the time
    bucket, so running several workers still produces one job per bucket."""
    settings = get_settings()
    now = datetime.now(UTC)
    bucket = now.replace(second=0, microsecond=0)
    bucket = bucket.replace(
        minute=(bucket.minute // settings.sync_interval_minutes) * settings.sync_interval_minutes
    )
    stamp = bucket.strftime("%Y%m%d%H%M")

    due = now - timedelta(minutes=settings.sync_interval_minutes)
    integrations = db.scalars(
        select(Integration).where(
            Integration.status != "disconnected",
            (Integration.last_synced_at.is_(None)) | (Integration.last_synced_at <= due),
        )
    ).all()

    for integration in integrations:
        queue.enqueue(
            db,
            "sync_integration",
            {"integration_id": str(integration.id)},
            org_id=integration.org_id,
            dedupe_key=f"{integration.id}:{stamp}",
        )

    for org_id in db.scalars(select(Organization.id)).all():
        queue.enqueue(
            db,
            "compute_rollups",
            {"org_id": str(org_id)},
            org_id=org_id,
            dedupe_key=f"{org_id}:{stamp}",
        )

        # Monday 08:00 UTC: digest for the week that just closed.
        if now.weekday() == 0 and now.hour == 8:
            last_week = week_start(now.date() - timedelta(days=7))
            queue.enqueue(
                db,
                "weekly_digest",
                {"org_id": str(org_id), "week_start": last_week.isoformat()},
                org_id=org_id,
                dedupe_key=f"{org_id}:digest:{last_week.isoformat()}",
            )


def run_once(db: DbSession) -> bool:
    job = queue.claim(db, WORKER_ID)
    if job is None:
        return False

    handler = HANDLERS.get(job.kind)
    if handler is None:
        queue.fail(db, job, f"no handler registered for kind '{job.kind}'")
        return True

    try:
        result = handler(db, job.payload or {})
        queue.complete(db, job)
        log.info("job %s (%s) done: %s", job.id, job.kind, result)
    except Exception as exc:
        db.rollback()
        log.exception("job %s (%s) failed", job.id, job.kind)
        queue.fail(db, job, str(exc))
    return True


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    log.info("worker %s starting", WORKER_ID)

    last_schedule = 0.0
    while True:
        db = SessionLocal()
        try:
            if time.monotonic() - last_schedule > 60:
                schedule_due_work(db)
                last_schedule = time.monotonic()

            worked = run_once(db)
        except Exception:
            log.exception("worker loop error")
            worked = False
        finally:
            db.close()

        if not worked:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
