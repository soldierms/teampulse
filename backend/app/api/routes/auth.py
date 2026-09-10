from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep
from app.auth.password import hash_password, verify_password
from app.auth.sessions import SESSION_COOKIE, issue_session, revoke_session
from app.config import get_settings
from app.models.org import Organization, User
from app.schemas.auth import LoginRequest, SessionOut, SignupRequest, UserOut
from app.util import slugify

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=get_settings().session_ttl_hours * 3600,
    )


@router.post("/signup", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, response: Response, db: DbDep) -> SessionOut:
    """Creates an organization and its first owner. Additional users are invited
    from org settings rather than signing up into an existing org."""
    email = body.email.lower()
    slug = slugify(body.org_name)
    if db.scalar(select(Organization).where(Organization.slug == slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An organization with that name exists")

    org = Organization(name=body.org_name, slug=slug, timezone=body.timezone)
    db.add(org)
    db.flush()

    user = User(
        org_id=org.id,
        email=email,
        password_hash=hash_password(body.password),
        name=body.name,
        timezone=body.timezone,
        role="owner",
    )
    db.add(user)
    db.commit()

    token = issue_session(db, user)
    _set_cookie(response, token)
    return SessionOut(token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=SessionOut)
def login(body: LoginRequest, response: Response, db: DbDep) -> SessionOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    # Same response whether the email is unknown or the password is wrong.
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    token = issue_session(db, user)
    _set_cookie(response, token)
    return SessionOut(token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbDep) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
