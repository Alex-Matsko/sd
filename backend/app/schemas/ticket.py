from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.enums import Channel, ImpactUrgencyLevel, Priority, SlaTimerState, TicketStatus, TicketType


class TicketCreate(BaseModel):
    contact_id: int
    type: TicketType
    channel: Channel
    subject: str
    category_id: int | None = None
    asset_id: int | None = None
    impact: ImpactUrgencyLevel | None = None
    urgency: ImpactUrgencyLevel | None = None
    manual_priority: Priority | None = None
    manual_priority_reason: str | None = None
    initial_message: str | None = None

    @model_validator(mode="after")
    def _check_priority_source(self) -> "TicketCreate":
        has_matrix_input = self.impact is not None and self.urgency is not None
        if not has_matrix_input and self.manual_priority is None:
            raise ValueError("Укажите impact и urgency, либо manual_priority")
        if self.manual_priority is not None and not self.manual_priority_reason:
            raise ValueError("При ручном приоритете нужно указать manual_priority_reason")
        return self


class TicketUpdate(BaseModel):
    status: TicketStatus | None = None
    assigned_engineer_id: int | None = None
    team_id: int | None = None
    category_id: int | None = None
    asset_id: int | None = None
    impact: ImpactUrgencyLevel | None = None
    urgency: ImpactUrgencyLevel | None = None
    manual_priority: Priority | None = None
    manual_priority_reason: str | None = None


class SlaTimerView(BaseModel):
    due_at: datetime | None
    met: bool | None
    state: SlaTimerState
    progress_pct: int | None


class TicketSlaView(BaseModel):
    reaction: SlaTimerView
    resolution: SlaTimerView
    paused: bool


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: int
    display_number: str
    type: TicketType
    channel: Channel
    subject: str
    organization_id: int
    contact_id: int
    contract_id: int | None
    tariff_id: int
    has_no_active_contract: bool
    asset_id: int | None
    category_id: int | None
    impact: ImpactUrgencyLevel | None
    urgency: ImpactUrgencyLevel | None
    priority: Priority
    priority_override_reason: str | None
    status: TicketStatus
    assigned_engineer_id: int | None
    team_id: int | None
    parent_ticket_id: int | None
    sla_reaction_due_at: datetime | None
    sla_resolution_due_at: datetime | None
    sla_paused_at: datetime | None
    first_response_at: datetime | None
    sla_reaction_met: bool | None
    resolved_at: datetime | None
    sla_resolution_met: bool | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Computed by services/sla.compute_view in the tickets router; not a model column.
    sla: TicketSlaView | None = None
