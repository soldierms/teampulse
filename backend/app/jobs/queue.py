import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession

from app.models.jobs import Job

CLAIM_SQL = text(
    """
    UPDATE jobs
       SET status = 'running',
           locked_by = :worker_id,
           locked_at = now(),
           attempts = attempts + 1
     WHERE id = (
        SELECT id FROM jobs
         WHERE status = 'pending' AND run_at <= now()
         ORDER BY run_at
         FOR UPDATE SKIP LOCKED
         LIMIT 1
     )
    RETURNING id
    """
)


def enqueue(
    db: DbSession,
    kind: str,
    payload: dict[str, Any] | None = None,
    org_id: uuid.UUID | None = None,
    run_at: datetime | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = 3,
) -> int | None:
    """Returns the job id, or None when a job with the same dedupe_key is already
    queued — that is how the scheduler stays idempotent across worker restarts."""
    stmt = insert(Job).values(
        org_id=org_id,
        kind=kind,
        dedupe_key=dedupe_key,
        payload=payload or {},
        run_at=run_at or datetime.now(UTC),
        max_attempts=max_attempts,
    )
    if dedupe_key is not None:
        stmt = stmt.on_conflict_do_nothing(index_elements=[Job.kind, Job.dedupe_key])
    stmt = stmt.returning(Job.id)

    job_id = db.execute(stmt).scalar_one_or_none()
    db.commit()
    return job_id


def claim(db: DbSession, worker_id: str) -> Job | None:
    job_id = db.execute(CLAIM_SQL, {"worker_id": worker_id}).scalar_one_or_none()
    db.commit()
    return db.get(Job, job_id) if job_id is not None else None


def complete(db: DbSession, job: Job) -> None:
    job.status = "done"
    job.finished_at = datetime.now(UTC)
    job.error = None
    # Frees the dedupe key so the next scheduled run of the same kind can enqueue.
    job.dedupe_key = None
    db.commit()


def fail(db: DbSession, job: Job, error: str) -> None:
    job.error = error[:2000]
    if job.attempts >= job.max_attempts:
        job.status = "failed"
        job.finished_at = datetime.now(UTC)
        job.dedupe_key = None
    else:
        job.status = "pending"
        job.locked_by = None
        job.locked_at = None
    db.commit()
