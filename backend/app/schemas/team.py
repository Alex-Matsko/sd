from pydantic import BaseModel, ConfigDict


class TeamCreate(BaseModel):
    name: str
    lead_user_id: int | None = None
    member_user_ids: list[int] = []


class TeamUpdate(BaseModel):
    name: str | None = None
    lead_user_id: int | None = None


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    lead_user_id: int | None
    member_user_ids: list[int] = []
