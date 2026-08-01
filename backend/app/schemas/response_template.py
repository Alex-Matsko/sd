from pydantic import BaseModel, ConfigDict


class ResponseTemplateCreate(BaseModel):
    name: str
    body: str
    category_id: int | None = None
    is_active: bool = True


class ResponseTemplateUpdate(BaseModel):
    name: str | None = None
    body: str | None = None
    category_id: int | None = None
    is_active: bool | None = None


class ResponseTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    body: str
    category_id: int | None
    is_active: bool
