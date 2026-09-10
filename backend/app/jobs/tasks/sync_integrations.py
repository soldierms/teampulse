import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.integrations.registry import build_source, is_deploy_provider, is_incident_provider
from app.integrations.sync import (
    last_watermark,
    sync_deploys,
    sync_identities,
    sync_incidents,
    sync_shifts,
)
from app.models.integration import Integration, SyncRun

log = logging.getLogger(__name__)

SHIFT_LOOKAHEAD_DAYS = 14


def run_sync(db: DbSession, integration_id: uuid.UUID) -> int:
    integration = db.get(Integration, integration_id)
    if integration is None:
        log.warning("sync skipped, integration %s no longer exists", integration_id)
        return 0

    started = datetime.now(UTC)
    run = SyncRun(integration_id=integration.id, kind=integration.provider, started_at=started)
    db.add(run)
    db.commit()

    source = build_source(integration)
    ingested = 0
    try:
        since = last_watermark(db, integration)

        # Identities first: incidents and deploys can only be attributed to a
        # person once the provider's users are mapped.
        ingested += sync_identities(db, integration, source.fetch_users())

        if is_incident_provider(integration):
            ingested += sync_incidents(db, integration, source.fetch_incidents(since))
            ingested += sync_shifts(
                db,
                integration,
                source.fetch_shifts(since, started + timedelta(days=SHIFT_LOOKAHEAD_DAYS)),
            )
        elif is_deploy_provider(integration):
            ingested += sync_deploys(db, integration, source.fetch_deploys(since))

        run.status = "success"
        run.watermark = started
        integration.status = "active"
        integration.last_error = None
        integration.last_synced_at = started
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:2000]
        integration.status = "error"
        integration.last_error = str(exc)[:2000]
        raise
    finally:
        run.finished_at = datetime.now(UTC)
        run.records_ingested = ingested
        db.commit()
        close = getattr(source, "close", None)
        if callable(close):
            close()

    log.info("synced %s (%s): %d records", integration.display_name, integration.provider, ingested)
    return ingested


def handle(db: DbSession, payload: dict) -> int:
    return run_sync(db, uuid.UUID(payload["integration_id"]))
