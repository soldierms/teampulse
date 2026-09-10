import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, DbDep
from app.auth.password import hash_password
from app.models.org import Organization, Team, TeamMember, User
from app.schemas.auth import UserOut
from app.schemas.org import OrgOut, OrgUpdate, UserInvite
from app.util import slugify

router = APIRouter(prefix="/api/org", tags=["org"])


@router.get("", response_model=OrgOut)
def get_org(user: CurrentUser, db: DbDep) -> OrgOut:
    return OrgOut.model_validate(db.get(Organization, user.org_id))


@router.patch("", response_model=OrgOut)
def update_org(body: OrgUpdate, admin: AdminUser, db: DbDep) -> OrgOut:
    org = db.get(Organization, admin.org_id)
    if body.name is not None:
        org.name = body.name
        org.slug = slugify(body.name)
    if body.timezone is not None:
        org.timezone = body.timezone
    db.commit()
    return OrgOut.model_validate(org)


@router.get("/users", response_model=list[UserOut])
def list_users(user: CurrentUser, db: DbDep) -> list[UserOut]:
    rows = db.scalars(select(User).where(User.org_id == user.org_id).order_by(User.name)).all()
    return [UserOut.model_validate(r) for r in rows]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def invite_user(body: UserInvite, admin: AdminUser, db: DbDep) -> UserOut:
    """v1 provisioning: an admin sets the initial password out of band.
    Replace with an invite-token flow once email delivery is wired up."""
    email = body.email.lower()
    exists = db.scalar(select(User).where(User.org_id == admin.org_id, User.email == email))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already in this org")

    user = User(
        org_id=admin.org_id,
        email=email,
        password_hash=hash_password(body.password),
        name=body.name,
        role=body.role,
        timezone=body.timezone,
    )
    db.add(user)
    db.commit()
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(user_id: uuid.UUID, admin: AdminUser, db: DbDep) -> None:
    user = db.scalar(select(User).where(User.id == user_id, User.org_id == admin.org_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot deactivate the org owner")
    # Soft-deactivate: their historical pages and deploys stay attributable.
    user.is_active = False
    db.execute(TeamMember.__table__.delete().where(TeamMember.user_id == user.id))
    db.commit()


@router.get("/teams-of/{user_id}", response_model=list[uuid.UUID])
def teams_of(user_id: uuid.UUID, user: CurrentUser, db: DbDep) -> list[uuid.UUID]:
    rows = db.scalars(
        select(TeamMember.team_id)
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.user_id == user_id, Team.org_id == user.org_id)
    ).all()
    return list(rows)
