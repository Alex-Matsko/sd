from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import AutomationTriggerType, Channel, Priority, TicketStatus

TEMPLATE_FIELDS = {'ticket_number', 'subject', 'client_name', 'organization', 'assignee', 'due_at', 'ticket_url'}


class AutomationFilters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    organization_id: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, gt=0)
    team_id: int | None = Field(default=None, gt=0)
    assigned_engineer_id: int | None = Field(default=None, gt=0)
    unassigned: bool = False
    priorities: list[Priority] = Field(default_factory=list, max_length=4)
    channels: list[Channel] = Field(default_factory=list, max_length=7)

    @model_validator(mode='after')
    def check_assignee(self):
        if self.unassigned and self.assigned_engineer_id:
            raise ValueError('Выберите исполнителя или заявки без исполнителя')
        return self


class AutomationAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['change_status', 'internal_note', 'notify_staff', 'client_reminder']
    text: str = Field(default='', max_length=10000)
    recipient: Literal['assignee', 'team', 'managers', 'users'] = 'assignee'
    user_ids: list[int] = Field(default_factory=list, max_length=50)
    channel: Literal['ticket', 'email', 'telegram', 'max', 'portal'] = 'ticket'

    @model_validator(mode='after')
    def check_action(self):
        self.text = self.text.strip()
        if self.type != 'change_status' and not self.text:
            raise ValueError('Укажите текст действия')
        tokens = re.findall(r'\{\{\s*(.*?)\s*\}\}', self.text)
        if set(tokens) - TEMPLATE_FIELDS:
            raise ValueError('Неизвестная переменная в шаблоне')
        if self.type == 'notify_staff' and self.recipient == 'users' and not self.user_ids:
            raise ValueError('Выберите получателей')
        if any(value <= 0 for value in self.user_ids):
            raise ValueError('Некорректный получатель')
        return self


class AutomationRuleCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=255)
    trigger_type: AutomationTriggerType = AutomationTriggerType.STATUS_WITHOUT_REPLY
    from_status: TicketStatus
    to_status: TicketStatus | None = None
    threshold_days: int = Field(default=1, ge=1, le=3650)
    delay_hours: int | None = Field(default=None, ge=1, le=87600)
    filters: AutomationFilters = Field(default_factory=AutomationFilters)
    actions: list[AutomationAction] = Field(default_factory=list, max_length=10)
    repeat_hours: int | None = Field(default=None, ge=1, le=8760)
    max_runs: int = Field(default=1, ge=1, le=1000)
    is_active: bool = False

    @model_validator(mode='after')
    def check_rule(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError('Укажите название правила')
        changes = [i for i, action in enumerate(self.actions) if action.type == 'change_status']
        if not self.actions and self.to_status is None:
            raise ValueError('Добавьте хотя бы одно действие')
        if changes and (len(changes) > 1 or changes[0] != len(self.actions) - 1 or self.to_status is None):
            raise ValueError('Смена статуса должна быть последним и единственным переходом')
        if self.actions and not changes and self.to_status is not None:
            raise ValueError('Добавьте действие смены статуса или уберите целевой статус')
        if self.repeat_hours is not None and (changes or not self.actions):
            raise ValueError('Правила смены статуса выполняются однократно')
        return self


class AutomationRuleRead(AutomationRuleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    revision: int
    updated_at: datetime


class AutomationRuleUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=255)
    trigger_type: AutomationTriggerType | None = None
    from_status: TicketStatus | None = None
    to_status: TicketStatus | None = None
    threshold_days: int | None = Field(default=None, ge=1, le=3650)
    delay_hours: int | None = Field(default=None, ge=1, le=87600)
    filters: AutomationFilters | None = None
    actions: list[AutomationAction] | None = Field(default=None, max_length=10)
    repeat_hours: int | None = Field(default=None, ge=1, le=8760)
    max_runs: int | None = Field(default=None, ge=1, le=1000)
    is_active: bool | None = None

    @model_validator(mode='before')
    @classmethod
    def reject_nulls(cls, values):
        nullable = {'to_status', 'delay_hours', 'repeat_hours'}
        if isinstance(values, dict) and any(value is None and key not in nullable for key, value in values.items()):
            raise ValueError('Поля правила не могут быть пустыми')
        return values
