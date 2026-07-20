from pydantic import BaseModel, ConfigDict

from app.core.enums import AssetType


class AssetCreate(BaseModel):
    organization_id: int
    type: AssetType
    name: str
    description: str | None = None


class AssetUpdate(BaseModel):
    type: AssetType | None = None
    name: str | None = None
    description: str | None = None


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    type: AssetType
    name: str
    description: str | None
