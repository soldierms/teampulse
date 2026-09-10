import base64
import hashlib
import hmac
import uuid

import httpx
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbDep
from app.config import get_settings
from app.integrations.credentials import encrypt_credentials
from app.integrations.registry import build_source
from app.jobs import queue
from app.models.integration import Integration, TeamResource
from app.schemas.integrations import (
    DiscoveredResource,
    GitHubConnect,
    IntegrationOut,
    MockConnect,
    PagerDutyConnect,
    SyncTriggered,
)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"


def _sign_state(org_id: uuid.UUID) -> str:
    settings = get_settings()
    payload = base64.urlsafe_b64encode(str(org_id).encode()).decode().rstrip("=")
    signature = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _verify_state(state: str) -> uuid.UUID:
    settings = get_settings()
    try:
        payload, signature = state.split(".", 1)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed OAuth state") from None

    expected = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state failed verification")

    padded = payload + "=" * (-len(payload) % 4)
    return uuid.UUID(base64.urlsafe_b64decode(padded).decode())


def _upsert_integration(
    db,
    org_id: uuid.UUID,
    provider: str,
    display_name: str,
    credentials: dict,
    config: dict,
) -> Integration:
    existing = db.scalar(
        select(Integration).where(
            Integration.org_id == org_id,
            Integration.provider == provider,
            Integration.display_name == display_name,
        )
    )
    if existing is not None:
        existing.credentials = encrypt_credentials(credentials)
        existing.config = config
        existing.status = "active"
        existing.last_error = None
        db.commit()
        return existing

    row = Integration(
        org_id=org_id,
        provider=provider,
        display_name=display_name,
        credentials=encrypt_credentials(credentials),
        config=config,
        status="active",
    )
    db.add(row)
    db.commit()
    return row


@router.get("", response_model=list[IntegrationOut])
def list_integrations(user: CurrentUser, db: DbDep) -> list[IntegrationOut]:
    rows = db.scalars(select(Integration).where(Integration.org_id == user.org_id)).all()
    return [IntegrationOut.model_validate(r) for r in rows]


@router.post("/pagerduty", response_model=IntegrationOut, status_code=status.HTTP_201_CREATED)
def connect_pagerduty(body: PagerDutyConnect, admin: AdminUser, db: DbDep) -> IntegrationOut:
    row = _upsert_integration(
        db, admin.org_id, "pagerduty", body.display_name, {"api_key": body.api_key}, {}
    )
    return IntegrationOut.model_validate(row)


@router.post("/github", response_model=IntegrationOut, status_code=status.HTTP_201_CREATED)
def connect_github(body: GitHubConnect, admin: AdminUser, db: DbDep) -> IntegrationOut:
    row = _upsert_integration(
        db,
        admin.org_id,
        "github",
        body.display_name,
        {"access_token": body.access_token},
        {"org": body.org, "repos": body.repos, "environment": body.environment},
    )
    return IntegrationOut.model_validate(row)


@router.post("/mock", response_model=IntegrationOut, status_code=status.HTTP_201_CREATED)
def connect_mock(body: MockConnect, admin: AdminUser, db: DbDep) -> IntegrationOut:
    """Fixture-backed connection for development without provider accounts."""
    name = body.display_name or f"{body.provider.title()} (mock)"
    row = _upsert_integration(db, admin.org_id, body.provider, name, {}, {"mock": True})
    return IntegrationOut.model_validate(row)


@router.get("/github/authorize")
def github_authorize(admin: AdminUser) -> RedirectResponse:
    settings = get_settings()
    if not settings.github_client_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "GITHUB_CLIENT_ID is not configured")

    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_oauth_redirect_url,
        "scope": "repo read:org read:user",
        "state": _sign_state(admin.org_id),
    }
    return RedirectResponse(f"{GITHUB_AUTHORIZE}?{httpx.QueryParams(params)}")


@router.get("/github/callback", response_model=IntegrationOut)
def github_callback(code: str, state: str, db: DbDep) -> IntegrationOut:
    settings = get_settings()
    org_id = _verify_state(state)

    response = httpx.post(
        GITHUB_TOKEN,
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": settings.github_oauth_redirect_url,
        },
        timeout=20.0,
    )
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"GitHub did not return a token: {payload.get('error_description', 'unknown error')}",
        )

    row = _upsert_integration(db, org_id, "github", "GitHub", {"access_token": token}, {})
    return IntegrationOut.model_validate(row)


@router.get("/{integration_id}/resources", response_model=list[DiscoveredResource])
def discover_resources(
    integration_id: uuid.UUID, user: CurrentUser, db: DbDep
) -> list[DiscoveredResource]:
    """Lists what this integration exposes so an admin can assign each item to a
    team. Read live from the provider — no local cache to go stale."""
    integration = db.scalar(
        select(Integration).where(
            Integration.id == integration_id, Integration.org_id == user.org_id
        )
    )
    if integration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integration not found")

    claimed = {
        (r.resource_type, r.external_id): r.team_id
        for r in db.scalars(
            select(TeamResource).where(
                TeamResource.org_id == user.org_id, TeamResource.provider == integration.provider
            )
        ).all()
    }

    source = build_source(integration)
    try:
        resources = source.list_resources()
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()

    return [
        DiscoveredResource(
            resource_type=r.resource_type,
            external_id=r.external_id,
            name=r.name,
            claimed_by_team_id=claimed.get((r.resource_type, r.external_id)),
        )
        for r in resources
    ]


@router.post("/{integration_id}/sync", response_model=SyncTriggered)
def trigger_sync(integration_id: uuid.UUID, admin: AdminUser, db: DbDep) -> SyncTriggered:
    integration = db.scalar(
        select(Integration).where(
            Integration.id == integration_id, Integration.org_id == admin.org_id
        )
    )
    if integration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integration not found")

    job_id = queue.enqueue(
        db,
        "sync_integration",
        {"integration_id": str(integration.id)},
        org_id=admin.org_id,
        dedupe_key=f"{integration.id}:manual",
    )
    return SyncTriggered(job_id=job_id, queued=job_id is not None)


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(integration_id: uuid.UUID, admin: AdminUser, db: DbDep) -> None:
    integration = db.scalar(
        select(Integration).where(
            Integration.id == integration_id, Integration.org_id == admin.org_id
        )
    )
    if integration is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integration not found")
    # Keeps ingested history; stops future syncs.
    integration.status = "disconnected"
    integration.credentials = encrypt_credentials({})
    db.commit()
