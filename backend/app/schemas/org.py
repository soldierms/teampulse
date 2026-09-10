import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    plan: str
    timezone: str


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = None


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str | None = None


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = None


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    timezone: str | None


class MemberOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    timezone: str | None


class MemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = "member"


class UserInvite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    role: str = "member"
    timezone: str | None = None


class TeamResourceIn(BaseModel):
    provider: str
    resource_type: str
    external_id: str
    name: str | None = None


class TeamResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    team_id: uuid.UUID
    provider: str
    resource_type: str
    external_id: str
    name: str | None
