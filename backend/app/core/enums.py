from enum import Enum


class UserRole(str, Enum):
    ENGINEER = "engineer"
    DISPATCHER = "dispatcher"
    MANAGER = "manager"
    ADMIN = "admin"


class TicketType(str, Enum):
    INCIDENT = "incident"
    SERVICE_REQUEST = "service_request"


class TicketStatus(str, Enum):
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    WAITING_CUSTOMER = "waiting_customer"
    WAITING_THIRD_PARTY = "waiting_third_party"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


# Statuses that pause the resolution SLA timer.
SLA_PAUSING_STATUSES = {TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_THIRD_PARTY}

# Statuses considered "open" for message-thread gluing (channel dialog attach rules).
OPEN_TICKET_STATUSES = {
    TicketStatus.NEW,
    TicketStatus.ASSIGNED,
    TicketStatus.IN_PROGRESS,
    TicketStatus.WAITING_CUSTOMER,
    TicketStatus.WAITING_THIRD_PARTY,
}


class Channel(str, Enum):
    TELEGRAM = "telegram"
    MAX = "max"
    EMAIL = "email"
    PHONE = "phone"
    PORTAL = "portal"
    WHATSAPP = "whatsapp"  # future channel, interface reserved, not implemented


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL_NOTE = "internal_note"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class ImpactUrgencyLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AssetType(str, Enum):
    SERVER = "server"
    WORKSTATION = "workstation"
    ONE_C_DATABASE = "1c_database"
    RENTED_RESOURCE = "rented_resource"
    NETWORK_DEVICE = "network_device"


class ContractStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"


class RoutingRuleType(str, Enum):
    ORGANIZATION_TO_ENGINEER = "organization_to_engineer"
    CATEGORY_TO_TEAM = "category_to_team"


class OrganizationStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class NotificationType(str, Enum):
    # ТЗ 4.2 требует уведомлять исполнителя об ответе клиента, ТЗ р. 8 — о
    # работе, попавшей к инженеру. Раньше существовали только SLA-события,
    # то есть инженер узнавал о заявке лишь когда по ней уже горел срок.
    TICKET_ASSIGNED = "ticket_assigned"
    CUSTOMER_REPLIED = "customer_replied"
    SLA_REACTION_WARNING = "sla_reaction_warning"
    SLA_REACTION_BREACH = "sla_reaction_breach"
    SLA_RESOLUTION_WARNING = "sla_resolution_warning"
    SLA_RESOLUTION_BREACH = "sla_resolution_breach"


class AutomationTriggerType(str, Enum):
    # Section 4.2: "«Решена» → «Закрыта»: автозакрытие через N дней без ответа
    # клиента". The only trigger type today; more (e.g. time-in-status
    # escalation moves) can be added later without a schema change.
    RESOLVED_WITHOUT_REPLY = "resolved_without_reply"


class ScheduleCadence(str, Enum):
    """How often a TicketSchedule fires. Deliberately a short fixed list
    rather than a cron expression: an MSP's preventive work is weekly or
    monthly, and cron syntax in an admin form is a support burden for no
    real gain here."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(str, Enum):
    # Section 2.4: a call is "ringing" while the dispatcher popup is relevant,
    # then either answered/completed or missed - and a missed one becomes a
    # ticket automatically.
    RINGING = "ringing"
    ANSWERED = "answered"
    COMPLETED = "completed"
    MISSED = "missed"
    FAILED = "failed"


class SlaTimerState(str, Enum):
    NO_RULE = "no_rule"  # tariff has no SLA rule for the ticket's priority
    OK = "ok"
    WARNING = "warning"  # >= 75% of the budget consumed
    BREACHED = "breached"
    MET = "met"
    PAUSED = "paused"
