import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbDep
from app.models.integration import TeamResource
from app.models.org import Team, TeamMember, User
from app.schemas.org import (
    MemberAdd,
    MemberOut,
    TeamCreate,
    TeamOut,
    TeamResourceIn,
    TeamResourceOut,
    TeamUpdate,
)
from app.util import slugify

router = APIRouter(prefix="/api/teams", tags=["teams"])


def _team_or_404(db, org_id: uuid.UUID, team_id: uuid.UUID) -> Team:
    team = db.scalar(select(Team).where(Team.id == team_id, Team.org_id == org_id))
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    return team


@router.get("", response_model=list[TeamOut])
def list_teams(user: CurrentUser, db: DbDep) -> list[TeamOut]:
    rows = db.scalars(select(Team).where(Team.org_id == user.org_id).order_by(Team.name)).all()
    return [TeamOut.model_validate(r) for r in rows]


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(body: TeamCreate, admin: AdminUser, db: DbDep) -> TeamOut:
    slug = slugify(body.name)
    if db.scalar(select(Team).where(Team.org_id == admin.org_id, Team.slug == slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A team with that name exists")
    team = Team(org_id=admin.org_id, name=body.name, slug=slug, timezone=body.timezone)
    db.add(team)
    db.commit()
    return TeamOut.model_validate(team)


@router.patch("/{team_id}", response_model=TeamOut)
def update_team(team_id: uuid.UUID, body: TeamUpdate, admin: AdminUser, db: DbDep) -> TeamOut:
    team = _team_or_404(db, admin.org_id, team_id)
    if body.name is not None:
        team.name = body.name
        team.slug = slugify(body.name)
    if body.timezone is not None:
        team.timezone = body.timezone
    db.commit()
    return TeamOut.model_validate(team)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: uuid.UUID, admin: AdminUser, db: DbDep) -> None:
    team = _team_or_404(db, admin.org_id, team_id)
    db.delete(team)
    db.commit()


@router.get("/{team_id}/members", response_model=list[MemberOut])
def list_members(team_id: uuid.UUID, user: CurrentUser, db: DbDep) -> list[MemberOut]:
    _team_or_404(db, user.org_id, team_id)
    rows = db.execute(
        select(User, TeamMember.role)
        .join(TeamMember, TeamMember.user_id == User.id)
        .where(TeamMember.team_id == team_id)
        .order_by(User.name)
    ).all()
    return [
        MemberOut(id=u.id, name=u.name, email=u.email, role=team_role, timezone=u.timezone)
        for u, team_role in rows
    ]


@router.post("/{team_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_member(team_id: uuid.UUID, body: MemberAdd, admin: AdminUser, db: DbDep) -> None:
    _team_or_404(db, admin.org_id, team_id)
    member = db.scalar(select(User).where(User.id == body.user_id, User.org_id == admin.org_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this org")
    existing = db.get(TeamMember, {"team_id": team_id, "user_id": body.user_id})
    if existing is None:
        db.add(TeamMember(team_id=team_id, user_id=body.user_id, role=body.role))
        db.commit()


@router.delete("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(team_id: uuid.UUID, user_id: uuid.UUID, admin: AdminUser, db: DbDep) -> None:
    _team_or_404(db, admin.org_id, team_id)
    link = db.get(TeamMember, {"team_id": team_id, "user_id": user_id})
    if link is not None:
        db.delete(link)
        db.commit()


@router.get("/{team_id}/resources", response_model=list[TeamResourceOut])
def list_resources(team_id: uuid.UUID, user: CurrentUser, db: DbDep) -> list[TeamResourceOut]:
    _team_or_404(db, user.org_id, team_id)
    rows = db.scalars(
        select(TeamResource).where(
            TeamResource.org_id == user.org_id, TeamResource.team_id == team_id
        )
    ).all()
    return [TeamResourceOut.model_validate(r) for r in rows]


@router.post("/{team_id}/resources", response_model=TeamResourceOut, status_code=201)
def claim_resource(
    team_id: uuid.UUID, body: TeamResourceIn, admin: AdminUser, db: DbDep
) -> TeamResourceOut:
    """Claim a PagerDuty service/schedule or GitHub repo for this team.
    Re-claiming a resource moves it rather than erroring — one owner per resource."""
    _team_or_404(db, admin.org_id, team_id)
    existing = db.scalar(
        select(TeamResource).where(
            TeamResource.org_id == admin.org_id,
            TeamResource.provider == body.provider,
            TeamResource.resource_type == body.resource_type,
            TeamResource.external_id == body.external_id,
        )
    )
    if existing is not None:
        existing.team_id = team_id
        existing.name = body.name or existing.name
        db.commit()
        return TeamResourceOut.model_validate(existing)

    row = TeamResource(
        org_id=admin.org_id,
        team_id=team_id,
        provider=body.provider,
        resource_type=body.resource_type,
        external_id=body.external_id,
        name=body.name,
    )
    db.add(row)
    db.commit()
    return TeamResourceOut.model_validate(row)


@router.delete("/{team_id}/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def release_resource(
    team_id: uuid.UUID, resource_id: uuid.UUID, admin: AdminUser, db: DbDep
) -> None:
    row = db.scalar(
        select(TeamResource).where(
            TeamResource.id == resource_id,
            TeamResource.org_id == admin.org_id,
            TeamResource.team_id == team_id,
        )
    )
    if row is not None:
        db.delete(row)
        db.commit()
