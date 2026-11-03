"""Канал «Периметр»: окно «Поддержка» в продуктах (по запросу заказчика)."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.routers import perimetr as perimetr_router
from app.config import settings
from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType
from app.models.contact import Contact, ContactEmail
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services import messages as messages_service
from app.services import perimetr_channel
from app.services import tickets as tickets_service
from app.services.unknown_queue import UNKNOWN_ORGANIZATION_NAME


def _inbound(text: str, key: str = "vms:abcdef0123456789", **kw) -> perimetr_channel.Inbound:
    return perimetr_channel.Inbound(key=key, product="Периметр VMS", text=text, **kw)


def test_первое_сообщение_открывает_заявку_следующие_идут_в_неё(db: Session, default_tariff):
    ticket = perimetr_channel.post_message(
        db, _inbound("Ворота не показывают видео", topic="camera", customer="ООО «Объект»", report="Камеры: 2")
    )
    assert ticket.channel == Channel.PERIMETR
    assert "Не подключается камера" in ticket.subject
    contact = db.get(Contact, ticket.contact_id)
    assert contact.organization.name == UNKNOWN_ORGANIZATION_NAME

    again = perimetr_channel.post_message(db, _inbound("С утра так", server="Версия 2.1.9"))
    assert again.id == ticket.id

    notes = db.query(Message).filter(Message.ticket_id == ticket.id, Message.direction == MessageDirection.INTERNAL_NOTE).all()
    assert len(notes) == 1 and "Камеры: 2" in notes[0].body


def test_ответ_инженера_виден_продукту_а_заметки_нет(db: Session, default_tariff):
    ticket = perimetr_channel.post_message(db, _inbound("Нет записи", report="секретная сводка"))
    engineer = db.query(User).first()
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.OUTBOUND, body="Перезагрузите камеру"), author_user=engineer
    )
    got = perimetr_channel.list_messages(db, "vms:abcdef0123456789")
    texts = [(m["from"], m["text"]) for m in got["messages"]]
    assert ("client", "Нет записи") in texts
    assert ("support", "Перезагрузите камеру") in texts
    assert all("секретная сводка" not in m["text"] for m in got["messages"])
    assert got["tickets"][0]["number"] == ticket.display_number and got["tickets"][0]["open"]
    last = got["messages"][-1]["id"]
    assert perimetr_channel.list_messages(db, "vms:abcdef0123456789", last)["messages"] == []


def test_после_закрытия_следующее_сообщение_открывает_новую(db: Session, default_tariff):
    first = perimetr_channel.post_message(db, _inbound("Раз"))
    for status in (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED):
        tickets_service.transition_status(db, db.get(Ticket, first.id), status, actor=None)
    second = perimetr_channel.post_message(db, _inbound("Два"))
    assert second.id != first.id
    got = perimetr_channel.list_messages(db, "vms:abcdef0123456789")
    assert [t["number"] for t in got["tickets"]] == [first.display_number, second.display_number]


def test_чужая_переписка_не_читается_по_контакту(db: Session, default_tariff, contact):
    """Адрес на сервере VMS вписывают от руки: неподтверждённый адрес не
    привязывает переписку к существующему контакту, и его заявки не видны."""
    contact.emails.append(ContactEmail(email="boss@example.test", is_primary=True))
    db.commit()
    tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.EMAIL, subject="чужая",
            manual_priority=Priority.P3, manual_priority_reason="тест", initial_message="чужое письмо",
        ),
        actor=None,
    )
    ticket = perimetr_channel.post_message(db, _inbound("Привет", key="vms:attacker000000", email="boss@example.test"))
    assert ticket.contact_id != contact.id
    got = perimetr_channel.list_messages(db, "vms:attacker000000")
    assert all(m["text"] != "чужое письмо" for m in got["messages"])
    assert perimetr_channel.list_messages(db, "vms:nobody00000000") is None


def test_подтверждённая_почта_облака_находит_контакт(db: Session, default_tariff, contact):
    contact.emails.append(ContactEmail(email="owner@example.test", is_primary=True))
    db.commit()
    ticket = perimetr_channel.post_message(
        db, _inbound("Камера", key="cloud:org-0001-0002", email="owner@example.test", email_verified=True)
    )
    assert ticket.contact_id == contact.id


def _request(secret: str | None) -> Request:
    headers = [(b"x-webhook-secret", secret.encode())] if secret is not None else []
    return Request({"type": "http", "headers": headers, "query_string": b""})


def test_без_секрета_канал_выключен_а_не_открыт(monkeypatch):
    monkeypatch.setattr(settings, "perimetr_secret", "")
    with pytest.raises(HTTPException) as e:
        perimetr_router.require_perimetr_secret(_request(None))
    assert e.value.status_code == 503
    monkeypatch.setattr(settings, "perimetr_secret", "s3cret-value")
    with pytest.raises(HTTPException) as e:
        perimetr_router.require_perimetr_secret(_request("wrong"))
    assert e.value.status_code == 401
    perimetr_router.require_perimetr_secret(_request("s3cret-value"))


# --- Обращения: несколько заявок с историей ----------------------------------


def _new(text: str, key: str = "vms:tickets00000001", **kw):
    kw.setdefault("customer", "ООО «Ромашка»")
    kw.setdefault("email", "ops@romashka.test")
    kw.setdefault("name", "admin")
    return perimetr_channel.Inbound(key=key, product="Периметр VMS", text=text, **kw)


def test_обращения_отдельные_и_с_организацией_из_кабинета(db: Session, default_tariff):
    first = perimetr_channel.create_ticket(db, _new("Не пишет архив", topic="recording"))
    second = perimetr_channel.create_ticket(db, _new("Лицензия на 8 камер", topic="license"))
    assert first.id != second.id
    contact = db.get(Contact, first.contact_id)
    assert contact.organization.name == "ООО «Ромашка»"
    assert [e.email for e in contact.emails] == ["ops@romashka.test"]
    assert second.contact_id == first.contact_id

    listed = perimetr_channel.list_tickets(db, "vms:tickets00000001")
    assert {t["number"] for t in listed} == {first.number, second.number}
    assert all(t["status_label"] and not t["final"] for t in listed)
    # Повторное название юрлица не плодит организации.
    third = perimetr_channel.create_ticket(db, _new("Ещё", email="", name="оператор", customer="ооо «ромашка»"))
    assert db.get(Contact, third.contact_id).organization_id == contact.organization_id


def test_лента_показывает_исполнителя_статусы_и_ответы(db: Session, default_tariff):
    ticket = perimetr_channel.create_ticket(db, _new("Ворота", report="секретная сводка"))
    engineer = db.query(User).first()
    tickets_service.update_ticket(db, db.get(Ticket, ticket.id), TicketUpdate(assigned_engineer_id=engineer.id), actor=engineer)
    messages_service.add_message(
        db, db.get(Ticket, ticket.id), MessageCreate(direction=MessageDirection.OUTBOUND, body="Смотрим"), author_user=engineer
    )
    detail = perimetr_channel.ticket_detail(db, "vms:tickets00000001", ticket.number)
    texts = [e["text"] for e in detail["events"]]
    assert texts[0] == "Обращение зарегистрировано"
    assert "Смотрим" in texts and "Ворота" in texts
    assert f"Исполнитель: {engineer.full_name}" in texts
    assert detail["assignee"] == engineer.full_name
    assert all("секретная сводка" not in t for t in texts)
    assert detail["last_support_id"] > 0


def test_ответ_в_закрытое_обращение_не_принимается(db: Session, default_tariff):
    ticket = perimetr_channel.create_ticket(db, _new("Раз"))
    perimetr_channel.reply(db, "vms:tickets00000001", ticket.number, "Дополнение")
    closed = perimetr_channel.close_by_client(db, "vms:tickets00000001", ticket.number)
    assert TicketStatus(closed.status) == TicketStatus.CLOSED
    with pytest.raises(perimetr_channel.TicketFinal):
        perimetr_channel.reply(db, "vms:tickets00000001", ticket.number, "Ещё")
    detail = perimetr_channel.ticket_detail(db, "vms:tickets00000001", ticket.number)
    assert detail["final"] and detail["status_label"] == "Закрыта"
    assert any(e["text"] == "Статус: Закрыта" for e in detail["events"])


def test_чужое_обращение_не_открывается(db: Session, default_tariff):
    ticket = perimetr_channel.create_ticket(db, _new("Своё"))
    with pytest.raises(perimetr_channel.TicketGone):
        perimetr_channel.ticket_detail(db, "vms:someoneelse0001", ticket.number)
    with pytest.raises(perimetr_channel.TicketGone):
        perimetr_channel.reply(db, "vms:someoneelse0001", ticket.number, "влезу")
    assert perimetr_channel.list_tickets(db, "vms:someoneelse0001") == []


def test_неподтверждённая_почта_чужой_организации_не_берёт_контакт(db: Session, default_tariff, contact):
    contact.emails.append(ContactEmail(email="boss@example.test", is_primary=True))
    db.commit()
    ticket = perimetr_channel.create_ticket(db, _new("Привет", email="boss@example.test", customer="ООО «Другая»"))
    assert ticket.contact_id != contact.id
