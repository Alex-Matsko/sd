"""Client controls must preserve drafts, ticket context, files and acceptance."""
from tests.test_customer_bot_replies import bot, make, state
from tests.test_customer_acceptance import actor, publish, deliver, working
from app.core.enums import TicketStatus
from app.models.ticket import Ticket
from app.models.channel_job import ChannelJob
from app.models.contact import Contact
from app.models.message import Message


def latest(db,bot):
    return db.query(ChannelJob).filter(ChannelJob.channel==bot.channel,ChannelJob.event_key.like('event:%:reply:%')).order_by(ChannelJob.id.desc()).first()


def test_help_and_cancel_never_become_a_ticket_or_append_to_old_ticket(db,bot,contact):
    original=make(db,contact)
    state(db,bot).active_ticket_id=original.id;db.commit()
    bot.incoming(bot.event(callback='cmd:new_ticket'))
    assert state(db,bot).awaiting_new_ticket_text
    bot.incoming(bot.event('/help'))
    assert state(db,bot).awaiting_new_ticket_text
    assert db.query(Ticket).filter_by(contact_id=contact.id).count()==1
    assert 'Как пользоваться поддержкой' in latest(db,bot).payload['text']
    bot.incoming(bot.event(callback='cmd:help'))
    assert state(db,bot).awaiting_new_ticket_text
    bot.incoming(bot.event('/cancel'))
    assert not state(db,bot).awaiting_new_ticket_text
    assert state(db,bot).active_ticket_id==original.id
    assert original.display_number in latest(db,bot).payload['text']
    assert db.query(Message).filter_by(ticket_id=original.id).count()==0
    out=latest(db,bot);assert out.ticket_id is None and out.payload['suppress_ticket_buttons']
    bot.incoming(bot.event('Уточнение по исходному вопросу'))
    assert db.query(Message).filter_by(ticket_id=original.id,body='Уточнение по исходному вопросу').one()
    assert db.query(Ticket).filter_by(contact_id=contact.id).count()==1


def test_cancel_button_does_not_delete_buffered_messages_or_files(db,bot,contact,monkeypatch):
    from tests.test_customer_bot_replies import file_event
    make(db,contact,'Первый');target=make(db,contact,'Второй')
    monkeypatch.setattr(bot.module,'_attachment_data',lambda config,attachment:('evidence.txt',b'keep-me','text/plain'))
    incoming=bot.incoming(bot.event('Файл для уточнения',files=file_event(bot,'evidence.txt')))
    assert incoming.state=='waiting'
    bot.incoming(bot.event(callback='cmd:cancel'))
    db.refresh(incoming);assert incoming.state=='waiting'
    assert 'сообщения и файлы сохранены' in latest(db,bot).payload['text']
    bot.incoming(bot.event(callback=f'reply:{target.id}'))
    message=db.query(Message).filter_by(ticket_id=target.id,body='Файл для уточнения').one()
    from pathlib import Path
    assert Path(message.attachments[0].stored_path).read_bytes()==b'keep-me'


def test_result_question_keeps_acceptance_available_until_explicit_rework(db,bot,contact,actor):
    ticket=working(db,contact);publish(db,ticket,bot,actor);result=ticket.resolution_message_id;deliver(db,result)
    bot.incoming(bot.event(callback=f'reply:{ticket.id}'))
    bot.incoming(bot.event('Где проверить результат?'))
    db.refresh(ticket)
    assert ticket.status==TicketStatus.RESOLVED and ticket.reopen_count==0
    assert ticket.resolution_message_id==result and ticket.accepted_at is None
    bot.incoming(bot.event(callback=f'accept:{ticket.id}:{result}'))
    db.refresh(ticket);assert ticket.status==TicketStatus.CLOSED and ticket.accepted_at


def test_rating_checks_owner_closed_status_range_and_repeated_click(db,bot,contact,organization):
    ticket=make(db,contact)
    other=Contact(organization_id=organization.id,full_name='Foreign');db.add(other);db.commit()
    foreign=make(db,other);foreign.status=TicketStatus.CLOSED;db.commit()
    for cb in [f'csat:{foreign.id}:5',f'csat:{ticket.id}:5',f'csat:{ticket.id}:0','csat:broken','csat:1:5:extra']:
        job=bot.incoming(bot.event(callback=cb));assert job.state=='processed'
    db.refresh(ticket);db.refresh(foreign);assert ticket.csat_rating is None and foreign.csat_rating is None
    ticket.status=TicketStatus.CLOSED;db.commit()
    bot.incoming(bot.event(callback=f'csat:{ticket.id}:4'))
    db.refresh(ticket);assert ticket.csat_rating==4
    assert ticket.display_number in latest(db,bot).payload['text']
    assert latest(db,bot).ticket_id is None
    bot.incoming(bot.event(callback=f'csat:{ticket.id}:1'))
    db.refresh(ticket);assert ticket.csat_rating==4
