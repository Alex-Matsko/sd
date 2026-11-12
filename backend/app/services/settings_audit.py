"""Автоматический аудит изменений настроек (ТЗ р. 10).

ТЗ требует журнал «всех изменений заявок **и настроек**». Заявки, сообщения и
списания пишутся явными вызовами `audit.record` в сервисном слое — там важно
записать смысл операции («статус изменён»), а не набор полей. С настройками
иначе: их правят два десятка роутеров одинаковым образом, и явные вызовы
означали бы тридцать мест, где о записи можно забыть. Именно так и вышло —
до этого изменения тарифов, SLA-правил, ролей и токенов интеграций не
попадали в журнал вообще, то есть установить, кто ослабил SLA перед отчётным
периодом, было невозможно.

Поэтому здесь слушатель `before_flush`: он видит фактические изменения
глазами самой SQLAlchemy и не зависит от того, вспомнил ли автор роутера про
аудит.

Автор запроса кладётся в `session.info` — а не в contextvar, как было в
первой версии: синхронные зависимости FastAPI выполняются в отдельном
потоке, контекст туда копируется, и выставленное внутри значение наружу не
возвращается, из-за чего все записи оказывались без автора. Сессия же — тот
самый объект, который слушатель и получает.
"""

import logging

from sqlalchemy import event, inspect
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.orm.base import PassiveFlag
from sqlalchemy.orm import Mapper, Session

from app.models.audit import AuditLog

logger = logging.getLogger("app.settings_audit")

# Ключ в session.info, под которым лежит автор запроса. Отсутствует для
# фоновых операций воркера — они пишутся в журнал без автора, как и раньше
# писались изменения заявок.
ACTOR_KEY = "audit_actor_id"


def set_actor(session: Session, user_id: int | None) -> None:
    session.info[ACTOR_KEY] = user_id

# Настройки, изменения которых журналируются. Заявки, сообщения и списания
# сюда не входят намеренно: у них есть свои осмысленные записи, и слушатель
# только продублировал бы их набором полей.
AUDITED_TABLES = {
    "tariffs": "tariff",
    "tariff_sla_rules": "tariff_sla_rules",
    "impact_urgency_rules": "priority_matrix",
    "routing_rules": "routing_rule",
    "contracts": "contract",
    "users": "user",
    "integration_settings": "integration_setting",
    "automation_rules": "automation_rule",
    "business_calendars": "business_calendar",
    "business_calendar_windows": "business_calendar",
    "holidays": "holiday",
    "categories": "category",
    "teams": "team",
    "team_memberships": "team",
    "response_templates": "response_template",
    "ticket_schedules": "ticket_schedule",
    "organizations": "organization",
}

# Поля, значения которых в журнал не попадают ни при каких условиях.
_SECRET_HINTS = ("password", "secret", "token", "encrypted", "link_code")


def _is_secret(field: str) -> bool:
    return any(hint in field.lower() for hint in _SECRET_HINTS)


def _entity_type(obj) -> str | None:
    return AUDITED_TABLES.get(getattr(obj, "__tablename__", None))


def _changed_fields(obj) -> dict:
    """{поле: {from, to}} по данным самой SQLAlchemy.

    Значения секретов заменяются пометкой: токен бота не должен осесть в
    аудите открытым текстом — журнал читают шире, чем настройки каналов.
    """
    changes: dict = {}
    state = inspect(obj)
    for attr in state.mapper.column_attrs:
        history = get_history(obj, attr.key, PassiveFlag.PASSIVE_OFF)
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        if old == new:
            continue
        changes[attr.key] = "изменено" if _is_secret(attr.key) else {
            "from": _plain(old),
            "to": _plain(new),
        }
    return changes


def _plain(value):
    """JSON-совместимое представление: в changes лежит JSON-колонка, и
    datetime/date/Enum туда напрямую не сериализуются."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "value"):  # Enum
        return value.value
    return str(value)


def _snapshot(obj) -> dict:
    return {
        attr.key: "изменено" if _is_secret(attr.key) else _plain(getattr(obj, attr.key, None))
        for attr in inspect(obj).mapper.column_attrs
    }


@event.listens_for(Mapper, "mapper_configured")
def _enable_active_history(mapper, class_) -> None:
    """Просит SQLAlchemy подгружать прежнее значение при присваивании.

    Без этого после `commit()` объект просрочен, и присваивание без чтения не
    оставляет следа о том, что было: в журнал уходило
    {"from": null, "to": "manager"}. Прежнее значение — половина смысла
    аудита, поэтому здесь оно стоит одного лишнего SELECT; настройки правят
    редко, на горячих путях этих таблиц нет.
    """
    if getattr(class_, "__tablename__", None) not in AUDITED_TABLES:
        return
    for attr in mapper.column_attrs:
        attr.active_history = True
        # Флаг на свойстве не долетает до уже созданного инструментированного
        # атрибута — решение о подгрузке принимает именно его impl, поэтому
        # выставляется и там. Без этого на просроченном после commit объекте
        # прежнее значение по-прежнему терялось.
        impl = getattr(getattr(class_, attr.key, None), "impl", None)
        if impl is not None:
            impl.active_history = True


def _enable_active_history_for_configured() -> None:
    """То же самое для мапперов, настроенных до импорта этого модуля.

    Событие `mapper_configured` срабатывает один раз на класс, и если
    мапперы успели настроиться раньше (в тестах порядок импортов другой),
    подписка на него уже ничего не даст.
    """
    from app.models.base import Base

    for mapper in Base.registry.mappers:
        _enable_active_history(mapper, mapper.class_)


_enable_active_history_for_configured()


@event.listens_for(Session, "before_flush")
def _record_settings_changes(session: Session, flush_context, instances) -> None:
    actor_id = session.info.get(ACTOR_KEY)
    entries: list[AuditLog] = []

    for obj in session.new:
        entity_type = _entity_type(obj)
        if entity_type:
            entries.append(_entry(entity_type, obj, "created", actor_id, _snapshot(obj)))

    for obj in session.dirty:
        entity_type = _entity_type(obj)
        if not entity_type or not session.is_modified(obj, include_collections=False):
            continue
        changes = _changed_fields(obj)
        if changes:
            entries.append(_entry(entity_type, obj, "updated", actor_id, changes))

    for obj in session.deleted:
        entity_type = _entity_type(obj)
        if entity_type:
            entries.append(_entry(entity_type, obj, "deleted", actor_id, _snapshot(obj)))

    for entry in entries:
        session.add(entry)


def _entry(entity_type: str, obj, action: str, actor_id: int | None, changes: dict) -> AuditLog:
    # id ещё нет у только что созданного объекта — он проставится позже,
    # поэтому для created пишется 0, а сам объект опознаётся по changes.
    return AuditLog(
        entity_type=entity_type,
        entity_id=getattr(obj, "id", None) or 0,
        action=action,
        user_id=actor_id,
        changes=changes,
    )
