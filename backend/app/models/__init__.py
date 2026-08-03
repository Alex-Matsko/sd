"""Реестр моделей.

Здесь должна быть **каждая** модель проекта: `alembic/env.py` берёт
`Base.metadata` отсюда, и модель, не попавшая в этот файл, для автогенерации
миграций просто не существует — autogenerate предложит удалить её таблицу.
Так уже случалось: список перестали пополнять после Этапа 5, и к Этапу 10
автогенерация предлагала снести восемь таблиц. Полнота проверяется тестом
test_all_models_are_registered.
"""

from app.models.base import Base
from app.models.organization import Organization, OrganizationEmailDomain, PublicEmailDomain
from app.models.contact import Contact, ContactEmail, ContactPhone
from app.models.user import User, TeamMembership
from app.models.team import Team
from app.models.calendar import BusinessCalendar, BusinessCalendarWindow, Holiday
from app.models.priority import ImpactUrgencyRule
from app.models.tariff import Tariff, TariffSlaRule
from app.models.contract import Contract
from app.models.category import Category
from app.models.asset import Asset
from app.models.routing import RoutingRule
from app.models.ticket import Ticket
from app.models.message import Message, Attachment
from app.models.time_entry import TimeEntry
from app.models.audit import AuditLog
from app.models.auth import RefreshToken
from app.models.notification import Notification
from app.models.automation_rule import AutomationRule
from app.models.integration_setting import IntegrationSetting
from app.models.channel_conversation_state import ChannelConversationState
from app.models.call import Call
from app.models.response_template import ResponseTemplate
from app.models.portal_auth import PortalCredential, PortalLoginToken
from app.models.saved_filter import SavedFilter
from app.models.ticket_schedule import TicketSchedule
from app.models.monitoring_alert import MonitoringAlert
from app.models.active_timer import ActiveTimer
from app.models.client_report import ClientReport

__all__ = [
    "Base",
    "Organization",
    "OrganizationEmailDomain",
    "PublicEmailDomain",
    "Contact",
    "ContactEmail",
    "ContactPhone",
    "User",
    "TeamMembership",
    "Team",
    "BusinessCalendar",
    "BusinessCalendarWindow",
    "Holiday",
    "ImpactUrgencyRule",
    "Tariff",
    "TariffSlaRule",
    "Contract",
    "Category",
    "Asset",
    "RoutingRule",
    "Ticket",
    "Message",
    "Attachment",
    "TimeEntry",
    "AuditLog",
    "RefreshToken",
    "Notification",
    "IntegrationSetting",
    "ChannelConversationState",
    "AutomationRule",
    "Call",
    "ResponseTemplate",
    "PortalCredential",
    "PortalLoginToken",
    "SavedFilter",
    "TicketSchedule",
    "MonitoringAlert",
    "ActiveTimer",
    "ClientReport",
]
