from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectStatus = Literal['draft', 'planning', 'approval', 'approved', 'in_progress', 'paused', 'completed', 'cancelled']
TaskStatus = Literal['backlog', 'ready', 'in_progress', 'review', 'done', 'cancelled']


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Versioned(Input):
    version: int = Field(ge=1)


class ProjectCreate(Input):
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default='', max_length=20000)
    organization_id: int | None = None
    owner_id: int | None = None
    start_date: date | None = None
    due_date: date | None = None


class ProjectUpdate(Versioned):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    owner_id: int | None = None
    start_date: date | None = None
    due_date: date | None = None

    @field_validator('title', 'description', 'owner_id')
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError('Поле не может быть пустым')
        return value


class ProjectTransition(Versioned):
    status: ProjectStatus
    reason: str = Field(default='', max_length=2000)


class TaskFields(Input):
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default='', max_length=10000)
    stage: str = Field(default='Основной этап', min_length=1, max_length=100)
    assignee_id: int | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimate_minutes: int = Field(default=0, ge=0, le=6000000)
    depends_on_ids: list[int] = Field(default_factory=list, max_length=100)


class TaskCreate(TaskFields, Versioned):
    pass


class TaskUpdate(Versioned):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    stage: str | None = Field(default=None, min_length=1, max_length=100)
    assignee_id: int | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimate_minutes: int | None = Field(default=None, ge=0, le=6000000)
    depends_on_ids: list[int] | None = Field(default=None, max_length=100)
    status: TaskStatus | None = None
    actual_minutes: int | None = Field(default=None, ge=0, le=6000000)
    completion_note: str | None = Field(default=None, max_length=10000)

    @field_validator('title', 'description', 'stage', 'estimate_minutes', 'depends_on_ids', 'status', 'actual_minutes', 'completion_note')
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError('Поле не может быть пустым')
        return value


class ApprovalRequest(Versioned):
    user_ids: list[int] = Field(min_length=1, max_length=20)
    contact_ids: list[int] = Field(default_factory=list, max_length=20)


class ApprovalDecision(Versioned):
    decision: Literal['approved', 'rejected']
    comment: str = Field(default='', max_length=5000)


class TicketLink(Versioned):
    ticket_id: int


class CommentCreate(Input):
    body: str = Field(min_length=1, max_length=10000)
