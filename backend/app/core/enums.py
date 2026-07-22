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
    SLA_REACTION_WARNING = "sla_reaction_warning"
    SLA_REACTION_BREACH = "sla_reaction_breach"
    SLA_RESOLUTION_WARNING = "sla_resolution_warning"
    SLA_RESOLUTION_BREACH = "sla_resolution_breach"


class SlaTimerState(str, Enum):
    NO_RULE = "no_rule"  # tariff has no SLA rule for the ticket's priority
    OK = "ok"
    WARNING = "warning"  # >= 75% of the budget consumed
    BREACHED = "breached"
    MET = "met"
    PAUSED = "paused"
