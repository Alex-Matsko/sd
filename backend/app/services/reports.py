"""Reporting aggregations (section 9, expanded per management request for
fuller company-wide visibility beyond the ТЗ-mandated baseline). Everything
here is a read-only query over existing tables - no new state, so results are
always consistent with the live ticket/time-entry data. All queries are
scoped to [date_from, date_time_to) and an optional organization filter."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.core.enums import OPEN_TICKET_STATUSES


def _bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """[date_from 00:00, date_to+1 00:00) in UTC - date_to is inclusive as a
    calendar day for the person picking dates in the UI."""
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start, end


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, 1)


def _period_filter(query, start: datetime, end: datetime, organization_id: int | None):
    query = query.filter(Ticket.created_at >= start, Ticket.created_at < end)
    if organization_id is not None:
        query = query.filter(Ticket.organization_id == organization_id)
    return query


def _sla_section(db: Session, start: datetime, end: datetime, organization_id: int | None) -> dict:
    # Считается в SQL, а не по загруженным заявкам: за месяц при 500 заявках
    # в день это 15 тысяч строк, и на годовой базе выгрузка их в Python
    # занимала секунды. См. docs/decisions.md, «Отчёты на годовом объёме».
    rows = _period_filter(
        db.query(
            Ticket.priority,
            func.count(Ticket.id),
            func.count(Ticket.sla_reaction_met),
            func.count(Ticket.sla_resolution_met),
            func.count(case((Ticket.sla_reaction_met.is_(True), 1))),
            func.count(case((Ticket.sla_resolution_met.is_(True), 1))),
        ).group_by(Ticket.priority),
        start,
        end,
        organization_id,
    ).all()

    def summarize(subset) -> dict:
        total = sum(r[1] for r in subset)
        reaction_known = sum(r[2] for r in subset)
        resolution_known = sum(r[3] for r in subset)
        return {
            "total": total,
            "reaction_met_pct": _pct(sum(r[4] for r in subset), reaction_known),
            "resolution_met_pct": _pct(sum(r[5] for r in subset), resolution_known),
        }

    by_priority = [
        {"priority": priority, **summarize([r for r in rows if r[0] == priority])}
        for priority in ("P1", "P2", "P3", "P4")
        if any(r[0] == priority for r in rows)
    ]

    orgs = {o.id: o.name for o in db.query(Organization.id, Organization.name)}
    # Нарушений может быть сколько угодно, а в отчёт идут первые 50 — LIMIT
    # в базе, а не срез после выгрузки всего периода.
    violation_rows = (
        _period_filter(
            db.query(
                Ticket.id,
                Ticket.number,
                Ticket.subject,
                Ticket.organization_id,
                Ticket.priority,
                Ticket.sla_reaction_met,
                Ticket.sla_resolution_met,
            ).filter(
                or_(Ticket.sla_reaction_met.is_(False), Ticket.sla_resolution_met.is_(False))
            ),
            start,
            end,
            organization_id,
        )
        .order_by(Ticket.created_at)
        .limit(50)
        .all()
    )
    violations = [
        {
            "ticket_id": row.id,
            "display_number": f"OH-{row.number}",
            "subject": row.subject,
            "organization": orgs.get(row.organization_id, "—"),
            "priority": row.priority,
            "reaction_met": row.sla_reaction_met,
            "resolution_met": row.sla_resolution_met,
        }
        for row in violation_rows
    ]

    return {**summarize(rows), "by_priority": by_priority, "violations": violations}


def _flow_section(db: Session, start: datetime, end: datetime, organization_id: int | None) -> dict:
    orgs = {o.id: o.name for o in db.query(Organization.id, Organization.name)}
    categories = {c.id: c.name for c in db.query(Category.id, Category.name)}

    def counted(column):
        return _period_filter(
            db.query(column, func.count(Ticket.id)).group_by(column), start, end, organization_id
        ).all()

    by_channel: dict[str, int] = defaultdict(int)
    by_category: dict[str, int] = defaultdict(int)
    by_organization: dict[str, int] = defaultdict(int)
    daily: dict[str, int] = defaultdict(int)
    total = 0
    for channel, count in counted(Ticket.channel):
        by_channel[channel.value] += count
        total += count
    for category_id, count in counted(Ticket.category_id):
        by_category[categories.get(category_id, "Без категории")] += count
    for org_id, count in counted(Ticket.organization_id):
        by_organization[orgs.get(org_id, "—")] += count
    for day, count in counted(func.date(Ticket.created_at)):
        daily[day.isoformat()] += count

    return {
        "total": total,
        "by_channel": [{"channel": k, "count": v} for k, v in sorted(by_channel.items(), key=lambda kv: -kv[1])],
        "by_category": [{"category": k, "count": v} for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])],
        "by_organization": [{"organization": k, "count": v} for k, v in sorted(by_organization.items(), key=lambda kv: -kv[1])],
        "daily": [{"date": k, "count": v} for k, v in sorted(daily.items())],
    }


def _workload_section(db: Session, start: datetime, end: datetime, organization_id: int | None) -> list[dict]:
    time_query = (
        db.query(
            TimeEntry.engineer_id,
            func.sum(case((TimeEntry.is_billable.is_(True), TimeEntry.duration_minutes), else_=0)),
            func.sum(case((TimeEntry.is_billable.is_(False), TimeEntry.duration_minutes), else_=0)),
        )
        .join(Ticket, Ticket.id == TimeEntry.ticket_id)
        .filter(TimeEntry.entry_date >= start.date(), TimeEntry.entry_date < end.date())
        .group_by(TimeEntry.engineer_id)
    )
    if organization_id is not None:
        time_query = time_query.filter(Ticket.organization_id == organization_id)

    minutes_by_engineer: dict[int, dict[str, int]] = defaultdict(lambda: {"billable": 0, "non_billable": 0})
    for engineer_id, billable, non_billable in time_query.all():
        minutes_by_engineer[engineer_id] = {"billable": int(billable or 0), "non_billable": int(non_billable or 0)}

    # Среднее время решения считает база: выгружать все решённые за месяц
    # заявки ради двух дат — самая дорогая часть отчёта на годовом объёме.
    resolved_query = (
        db.query(
            Ticket.assigned_engineer_id,
            func.count(Ticket.id),
            func.avg(func.extract("epoch", Ticket.resolved_at - Ticket.created_at) / 60),
        )
        .filter(
            Ticket.resolved_at.isnot(None),
            Ticket.resolved_at >= start,
            Ticket.resolved_at < end,
            Ticket.assigned_engineer_id.isnot(None),
        )
        .group_by(Ticket.assigned_engineer_id)
    )
    if organization_id is not None:
        resolved_query = resolved_query.filter(Ticket.organization_id == organization_id)
    resolved_by_engineer: dict[int, tuple[int, float]] = {
        engineer_id: (count, float(avg_minutes or 0))
        for engineer_id, count, avg_minutes in resolved_query.all()
    }

    engineer_ids = set(minutes_by_engineer) | set(resolved_by_engineer)
    if not engineer_ids:
        return []
    names = {u.id: u.full_name for u in db.query(User.id, User.full_name).filter(User.id.in_(engineer_ids))}

    rows = []
    for eng_id in engineer_ids:
        minutes = minutes_by_engineer.get(eng_id, {"billable": 0, "non_billable": 0})
        resolved_count, avg_minutes = resolved_by_engineer.get(eng_id, (0, 0.0))
        rows.append(
            {
                "engineer_id": eng_id,
                "engineer_name": names.get(eng_id, "—"),
                "billable_minutes": minutes["billable"],
                "non_billable_minutes": minutes["non_billable"],
                "resolved_count": resolved_count,
                "avg_resolution_minutes": round(avg_minutes) if resolved_count else None,
            }
        )
    return sorted(rows, key=lambda r: -r["billable_minutes"])


def _csat_section(db: Session, start: datetime, end: datetime, organization_id: int | None) -> dict:
    query = db.query(
        Ticket.csat_rating, Ticket.assigned_engineer_id, Ticket.organization_id
    ).filter(Ticket.csat_rating.isnot(None), Ticket.csat_rated_at >= start, Ticket.csat_rated_at < end)
    if organization_id is not None:
        query = query.filter(Ticket.organization_id == organization_id)
    tickets = query.all()

    orgs = {o.id: o.name for o in db.query(Organization.id, Organization.name)}
    names = {u.id: u.full_name for u in db.query(User.id, User.full_name)}

    def grouped(key_fn, label_fn) -> list[dict]:
        buckets: dict[str, list[int]] = defaultdict(list)
        for t in tickets:
            buckets[label_fn(key_fn(t))].append(t.csat_rating)
        return [
            {"label": label, "average": round(sum(ratings) / len(ratings), 2), "count": len(ratings)}
            for label, ratings in sorted(buckets.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
        ]

    ratings = [t.csat_rating for t in tickets]
    return {
        "average": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "count": len(ratings),
        "by_engineer": grouped(lambda t: t.assigned_engineer_id, lambda v: names.get(v, "Не назначено")),
        "by_organization": grouped(lambda t: t.organization_id, lambda v: orgs.get(v, "—")),
    }


_AGING_BUCKETS = [("0–1 дн.", 0, 1), ("1–3 дн.", 1, 3), ("3–7 дн.", 3, 7), ("7+ дн.", 7, None)]


def _backlog_aging_section(db: Session, organization_id: int | None) -> list[dict]:
    """Snapshot of currently-open tickets by age - inherently "as of now", not
    bound to the report's period filter (a backlog has no start/end date).

    Из-за отсутствия периода это самая дорогая секция отчёта: она смотрит на
    весь незакрытый бэклог за всё время. Раньше он выгружался в Python
    целиком, и на годовой базе это была большая часть времени отчёта —
    поэтому здесь один запрос с CASE, а не подсчёт по объектам."""
    now = datetime.now(timezone.utc)
    buckets = [
        func.count(
            case(
                (
                    and_(
                        Ticket.created_at <= now - timedelta(days=lo),
                        True if hi is None else Ticket.created_at > now - timedelta(days=hi),
                    ),
                    1,
                )
            )
        ).label(label)
        for label, lo, hi in _AGING_BUCKETS
    ]
    query = db.query(*buckets).filter(Ticket.status.in_(OPEN_TICKET_STATUSES))
    if organization_id is not None:
        query = query.filter(Ticket.organization_id == organization_id)
    counts = query.one()

    return [{"bucket": label, "count": count} for (label, _, _), count in zip(_AGING_BUCKETS, counts)]


_CLIENT_STATUS_LABELS = {
    "new": "Новая",
    "assigned": "Назначена",
    "in_progress": "В работе",
    "waiting_customer": "Ждём вас",
    "waiting_third_party": "Ждём третью сторону",
    "resolved": "Решена",
    "closed": "Закрыта",
    "cancelled": "Отменена",
}
_CLIENT_CHANNEL_LABELS = {
    "telegram": "Telegram",
    "max": "MAX",
    "email": "Email",
    "phone": "Телефон",
    "portal": "Портал",
    "whatsapp": "WhatsApp",
}


def get_client_report(db: Session, organization_id: int, date_from: date, date_to: date) -> dict:
    """ТЗ 9.2 - the per-period statement handed to the client: their tickets,
    the time logged against them, and how the contracted hour package went.

    Scoped deliberately to what the client is entitled to see: no engineer
    names, no internal notes, no cross-organization figures. Time is summed
    from TimeEntry rows dated inside the period (not from the ticket's own
    dates), so work done this month on a ticket opened last month lands in
    the month it was actually spent - which is how the package is billed."""
    from app.models.contract import Contract
    from app.models.organization import Organization
    from app.services import billing
    from app.services.contracts import resolve_contract_and_tariff

    organization = db.get(Organization, organization_id)
    if organization is None:
        raise ValueError("Организация не найдена")

    start, end = _bounds(date_from, date_to)
    tickets = (
        db.query(Ticket)
        .filter(Ticket.organization_id == organization_id, Ticket.created_at >= start, Ticket.created_at < end)
        .order_by(Ticket.created_at)
        .all()
    )

    minutes_by_ticket: dict[int, int] = defaultdict(int)
    entries = (
        db.query(TimeEntry)
        .join(Ticket, Ticket.id == TimeEntry.ticket_id)
        .filter(
            Ticket.organization_id == organization_id,
            TimeEntry.entry_date >= date_from,
            TimeEntry.entry_date <= date_to,
        )
        .all()
    )
    for entry in entries:
        minutes_by_ticket[entry.ticket_id] += entry.duration_minutes
    total_minutes = sum(minutes_by_ticket.values())

    contract, _, has_no_active_contract = resolve_contract_and_tariff(db, organization_id)
    if contract is not None and not has_no_active_contract:
        usage = billing.get_organization_usage(db, organization_id, contract, date_to.year, date_to.month)
        package = {
            "package_total_hours": round(usage["package_total_minutes"] / 60, 2),
            "package_used_hours": round(usage["package_used_minutes"] / 60, 2),
            "package_remaining_hours": round(usage["package_remaining_minutes"] / 60, 2),
            "overage_hours": round(usage["overage_minutes"] / 60, 2),
            "overage_cost": usage["overage_cost"],
        }
    else:
        # No active contract - the ticket still got served (docs/decisions.md),
        # but there's no package to report against, and inventing zeros would
        # read as "your package is exhausted".
        package = {
            "package_total_hours": "нет договора",
            "package_used_hours": "—",
            "package_remaining_hours": "—",
            "overage_hours": "—",
            "overage_cost": "—",
        }

    return {
        "organization": organization.name,
        "period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "totals": {
            "tickets": len(tickets),
            "resolved": sum(1 for t in tickets if t.resolved_at is not None),
            "hours": round(total_minutes / 60, 2),
        },
        "package": package,
        "tickets": [
            {
                "display_number": t.display_number,
                "subject": t.subject,
                "channel": _CLIENT_CHANNEL_LABELS.get(t.channel.value, t.channel.value),
                "priority": t.priority,
                "status": _CLIENT_STATUS_LABELS.get(str(t.status).split(".")[-1].lower(), str(t.status)),
                "created_at": t.created_at.strftime("%d.%m.%Y %H:%M"),
                "resolved_at": t.resolved_at.strftime("%d.%m.%Y %H:%M") if t.resolved_at else None,
                "hours": round(minutes_by_ticket.get(t.id, 0) / 60, 2),
            }
            for t in tickets
        ],
    }


def get_overview(db: Session, date_from: date, date_to: date, organization_id: int | None = None) -> dict:
    start, end = _bounds(date_from, date_to)
    return {
        "period": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
        "sla": _sla_section(db, start, end, organization_id),
        "flow": _flow_section(db, start, end, organization_id),
        "workload": _workload_section(db, start, end, organization_id),
        "csat": _csat_section(db, start, end, organization_id),
        "backlog_aging": _backlog_aging_section(db, organization_id),
    }
