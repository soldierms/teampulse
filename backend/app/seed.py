"""Creates a demo org wired to the mock providers, syncs it, and computes rollups.

    python -m app.seed

Safe to re-run: it reuses the existing demo org rather than duplicating it.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.password import hash_password
from app.db import SessionLocal
from app.integrations.base import GH_REPO, PD_SCHEDULE, PD_SERVICE
from app.integrations.credentials import encrypt_credentials
from app.integrations.mock import generator
from app.jobs.tasks.sync_integrations import run_sync
from app.metrics.rollups import backfill
from app.models.integration import Integration, TeamResource
from app.models.org import Organization, Team, TeamMember, User

log = logging.getLogger(__name__)

DEMO_ORG_SLUG = "acme-engineering"
DEMO_ADMIN_EMAIL = "admin@example.com"
DEMO_PASSWORD = "teampulse-demo-2026"

# Single source of truth with the fixture generator, so demo teams sit in the
# same zones the fake incidents were generated for.
TEAM_TIMEZONES = generator.TEAM_TIMEZONES


def _get_or_create_org(db: DbSession) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))
    if org is None:
        org = Organization(
            name="Acme Engineering", slug=DEMO_ORG_SLUG, plan="trial", timezone="UTC"
        )
        db.add(org)
        db.commit()
    return org


def _get_or_create_user(
    db: DbSession, org: Organization, name: str, email: str, role: str, tz: str
) -> User:
    user = db.scalar(select(User).where(User.org_id == org.id, User.email == email))
    if user is None:
        user = User(
            org_id=org.id,
            email=email,
            name=name,
            password_hash=hash_password(DEMO_PASSWORD),
            role=role,
            timezone=tz,
        )
        db.add(user)
        db.commit()
    return user


def _get_or_create_team(db: DbSession, org: Organization, key: str, name: str) -> Team:
    team = db.scalar(select(Team).where(Team.org_id == org.id, Team.slug == key))
    if team is None:
        team = Team(org_id=org.id, name=name, slug=key, timezone=TEAM_TIMEZONES[key])
        db.add(team)
        db.commit()
    return team


def _claim(
    db: DbSession,
    org: Organization,
    team: Team,
    provider: str,
    kind: str,
    external_id: str,
    name: str,
) -> None:
    existing = db.scalar(
        select(TeamResource).where(
            TeamResource.org_id == org.id,
            TeamResource.provider == provider,
            TeamResource.resource_type == kind,
            TeamResource.external_id == external_id,
        )
    )
    if existing is None:
        db.add(
            TeamResource(
                org_id=org.id,
                team_id=team.id,
                provider=provider,
                resource_type=kind,
                external_id=external_id,
                name=name,
            )
        )


def _get_or_create_integration(db: DbSession, org: Organization, provider: str) -> Integration:
    name = f"{provider.title()} (mock)"
    row = db.scalar(
        select(Integration).where(
            Integration.org_id == org.id,
            Integration.provider == provider,
            Integration.display_name == name,
        )
    )
    if row is None:
        row = Integration(
            org_id=org.id,
            provider=provider,
            display_name=name,
            credentials=encrypt_credentials({}),
            config={"mock": True},
            status="active",
        )
        db.add(row)
        db.commit()
    return row


def seed() -> None:
    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
    db = SessionLocal()
    try:
        org = _get_or_create_org(db)
        admin = _get_or_create_user(
            db, org, "Demo Admin", DEMO_ADMIN_EMAIL, "owner", "Europe/London"
        )

        teams = {}
        for key, label, *_ in generator.TEAM_PROFILES:
            teams[key] = _get_or_create_team(db, org, key, label)

        # Provider user emails match these, so external identities auto-link on sync.
        for _pd_id, name, email, team_key in generator.PEOPLE:
            person = _get_or_create_user(db, org, name, email, "member", TEAM_TIMEZONES[team_key])
            link = db.get(TeamMember, {"team_id": teams[team_key].id, "user_id": person.id})
            if link is None:
                db.add(TeamMember(team_id=teams[team_key].id, user_id=person.id))

        admin_team = teams["platform"]
        if db.get(TeamMember, {"team_id": admin_team.id, "user_id": admin.id}) is None:
            db.add(TeamMember(team_id=admin_team.id, user_id=admin.id, role="lead"))
        db.commit()

        for key, label, *_ in generator.TEAM_PROFILES:
            team = teams[key]
            _claim(db, org, team, "pagerduty", PD_SERVICE, f"PSVC{key[:3].upper()}", label)
            _claim(
                db,
                org,
                team,
                "pagerduty",
                PD_SCHEDULE,
                f"PSCH{key[:3].upper()}",
                f"{label} on-call",
            )
            _claim(db, org, team, "github", GH_REPO, f"acme/{key}", f"acme/{key}")
        db.commit()

        pd = _get_or_create_integration(db, org, "pagerduty")
        gh = _get_or_create_integration(db, org, "github")

        log.info("syncing mock PagerDuty…")
        run_sync(db, pd.id)
        log.info("syncing mock GitHub…")
        run_sync(db, gh.id)

        log.info("computing 90 days of rollups…")
        started = datetime.now(UTC)
        backfill(db, org.id, days=90)
        log.info("rollups done in %.1fs", (datetime.now(UTC) - started).total_seconds())

        log.info("")
        log.info("Demo org ready. Sign in with:")
        log.info("  email:    %s", DEMO_ADMIN_EMAIL)
        log.info("  password: %s", DEMO_PASSWORD)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
