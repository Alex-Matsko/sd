"""Both bots show full subjects, scoped counts and complete public descriptions."""
from datetime import datetime, timedelta, timezone

import pytest
from tests.test_customer_bot_replies import bot, make, state
from app.core.enums import TicketStatus, MessageDirection
from app.models.channel_job import ChannelJob
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.contact import Contact
from app.schemas.message import MessageCreate
from app.services import messenger_common as common, messages


def make_status(db, contact, subject, status):
    t=make(db, contact, subject)
    t.status=status;db.commit()
    return t


def responses(db, bot):
    return db.query(ChannelJob).filter(ChannelJob.channel==bot.channel,
        ChannelJob.event_key.like('event:%:reply:%')).order_by(ChannelJob.id).all()


def latest(db, bot):
    return responses(db,bot)[-1].payload


def payloads(reply):
    return [b['payload'] for row in reply.get('buttons',[]) for b in row]


def test_active_list_shows_full_subject_work_stage_and_global_counts(db, bot, contact):
    title='Загрузить номенклатуру и прайс Теплодар, проверить соответствие артикулов и обновить закупочные цены'
    working=make_status(db,contact,title,TicketStatus.IN_PROGRESS)
    working.planned_due_at=datetime.now(timezone.utc)+timedelta(days=1);working.estimated_minutes=150;db.commit()
    make_status(db,contact,'Ждём уточнение клиента',TicketStatus.WAITING_CUSTOMER)
    closed=make_status(db,contact,'Закрытая задача',TicketStatus.CLOSED)
    resolved=make_status(db,contact,'Результат на проверке',TicketStatus.RESOLVED)
    bot.incoming(bot.event('Мои заявки'))
    reply=latest(db,bot)
    assert title in reply['text'] and 'Сейчас в работе: 1' in reply['text']
    assert 'исполнитель выполняет' in reply['text'].lower() and 'нужен ваш ответ' in reply['text']
    assert '2 ч 30 мин' in reply['text'] and 'Плановый срок решения:' in reply['text']
    assert f'ticket:{closed.id}' not in payloads(reply) and f'ticket:{resolved.id}' not in payloads(reply)
    assert f'ticket:{working.id}'==payloads(reply)[0]
    assert 'На приёмке: 1' in reply['text'] and 'Завершённые: 1' in reply['text']


def test_scopes_keep_closed_and_waiting_acceptance_out_of_active_list(db,bot,contact):
    closed=make_status(db,contact,'Завершённая',TicketStatus.CLOSED)
    cancelled=make_status(db,contact,'Отменённая',TicketStatus.CANCELLED)
    resolved=make_status(db,contact,'Нужна приёмка',TicketStatus.RESOLVED)
    bot.incoming(bot.event('Мои заявки'))
    reply=latest(db,bot);assert 'Активных заявок нет' in reply['text']
    assert 'mytickets:completed:0' in payloads(reply) and 'mytickets:acceptance:0' in payloads(reply)
    bot.incoming(bot.event(callback='mytickets:completed:0'))
    reply=latest(db,bot);assert f'ticket:{closed.id}' in payloads(reply) and f'ticket:{cancelled.id}' in payloads(reply)
    assert 'Статус: Закрыта' in reply['text'] and 'Статус: Отменена' in reply['text']
    assert f'ticket:{resolved.id}' not in payloads(reply)
    bot.incoming(bot.event(callback='mytickets:acceptance:0'))
    reply=latest(db,bot);assert f'ticket:{resolved.id}' in payloads(reply) and 'Статус: На приёмке' in reply['text']
    assert f'ticket:{closed.id}' not in payloads(reply)


def test_paging_stays_in_selected_scope_and_legacy_callbacks_are_safe(db,bot,contact):
    archived=[make_status(db,contact,f'Архив {i}',TicketStatus.CLOSED) for i in range(7)]
    for cb in ['mytickets:completed:0','mytickets:completed:3','mytickets:completed:6']:
        bot.incoming(bot.event(callback=cb))
        reply=latest(db,bot)
        assert all(p in {f'ticket:{t.id}' for t in archived} for p in payloads(reply) if p.startswith('ticket:'))
        assert all(p.startswith('mytickets:completed:') for p in payloads(reply) if p.startswith('mytickets:') and not p.endswith(':0'))
    assert 'Показаны 7–7 из 7' in latest(db,bot)['text']
    for cb in ['mytickets:5','mytickets:completed:999999999999999999999999','mytickets:unknown:0','mytickets:-1','mytickets:active:bad']:
        job=bot.incoming(bot.event(callback=cb));assert job.state=='processed'


def test_card_has_current_stage_full_title_and_readable_description_without_private_notes(db,bot,contact):
    title='Длинная тема заявки '+('полностью видна ' * 20)
    t=make_status(db,contact,title,TicketStatus.IN_PROGRESS)
    body='Подробное исходное описание. '+('Нужно проверить данные. ' * 150)+'КОНЕЦ ОПИСАНИЯ'
    messages.add_message(db,t,MessageCreate(direction='inbound',body=body),author_contact=contact)
    messages.add_message(db,t,MessageCreate(direction='internal_note',body='PRIVATE STAFF NOTE'))
    bot.incoming(bot.event(callback=f'ticket:{t.id}'))
    card=latest(db,bot);assert title in card['text'] and 'Статус: В работе' in card['text']
    assert 'Исполнитель выполняет задачу' in card['text'] and f'ticketbody:{t.id}:0' in payloads(card)
    received=[]
    for offset in range(0,len(body),1000):
        bot.incoming(bot.event(callback=f'ticketbody:{t.id}:{offset}'))
        reply=latest(db,bot);assert 'PRIVATE STAFF NOTE' not in reply['text']
        received.append(reply['text'].split('Описание заявки:\n',1)[1].rsplit('\n\nЧасть ',1)[0])
    assert ''.join(received)==body
    assert state(db,bot).active_ticket_id==t.id


def test_lists_and_description_cannot_read_another_contacts_data(db,bot,contact,organization):
    other=Contact(organization_id=organization.id,full_name='Another customer');db.add(other);db.commit()
    secret=make_status(db,other,'FOREIGN-TICKET-SECRET',TicketStatus.IN_PROGRESS)
    for cb in ['cmd:my_tickets','mytickets:completed:0',f'ticket:{secret.id}',f'ticketbody:{secret.id}:0']:
        bot.incoming(bot.event(callback=cb))
        assert 'FOREIGN-TICKET-SECRET' not in latest(db,bot)['text']
    assert state(db,bot).active_ticket_id is None


def test_full_emoji_subjects_and_description_pages_fit_provider_messages(db,bot,contact):
    for i in range(3): make_status(db,contact,'😀'*498+str(i),TicketStatus.IN_PROGRESS)
    bot.incoming(bot.event('Мои заявки'));reply=latest(db,bot)
    assert len(reply['text'].encode('utf-16-le'))//2<4000
    for t in db.query(Ticket).filter_by(contact_id=contact.id): assert t.subject in reply['text']
    t=db.query(Ticket).filter_by(contact_id=contact.id).first()
    messages.add_message(db,t,MessageCreate(direction='inbound',body='😀'*3000),author_contact=contact)
    bot.incoming(bot.event(callback=f'ticketbody:{t.id}:0'));reply=latest(db,bot)
    assert len(reply['text'].encode('utf-16-le'))//2<4000


def test_cancelled_card_is_view_only_until_explicit_followup(db,bot,contact):
    t=make_status(db,contact,'Отменённая задача для просмотра',TicketStatus.CANCELLED)
    bot.incoming(bot.event(callback=f'ticket:{t.id}'))
    assert state(db,bot).awaiting_revive_text is False
    assert f'continue:{t.id}' in payloads(latest(db,bot))
    assert f'reply:{t.id}' not in payloads(latest(db,bot))
    assert db.query(Ticket).filter_by(contact_id=contact.id).count()==1
    job=bot.incoming(bot.event('Нужно уточнить вопрос по отменённой задаче'))
    assert job.state=='waiting' and db.query(Ticket).filter_by(contact_id=contact.id).count()==1
    bot.incoming(bot.event(callback=f'continue:{t.id}'))
    fresh=db.query(Ticket).filter_by(parent_ticket_id=t.id).one()
    assert db.query(Message).filter_by(ticket_id=fresh.id).one().body=='Нужно уточнить вопрос по отменённой задаче'


def test_list_delivery_does_not_get_reply_buttons_for_a_previously_active_ticket(db,bot,contact):
    from app.services import channel_queue as queue
    t=make_status(db,contact,'Ранее выбранная закрытая',TicketStatus.CLOSED)
    s=state(db,bot);s.active_ticket_id=t.id;db.commit()
    bot.incoming(bot.event('Мои заявки'))
    out=responses(db,bot)[-1]
    assert out.ticket_id is None and out.payload['suppress_ticket_buttons'] is True
    assert queue.process_outbound(db,*queue.claim(db,'outbound',out.id))
    sent=bot.sent[-1]
    assert not any(b['payload'].startswith(('reply:','result:','rework:')) for row in sent['buttons'] for b in row)
    assert state(db,bot).active_ticket_id==t.id
