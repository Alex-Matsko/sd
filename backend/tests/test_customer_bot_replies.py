"""Customer routing, explicit delivery and durable file selection. All providers mocked."""
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.enums import Channel, MessageDirection, TicketStatus, UserRole
from app.db import get_db
from app.main import app
from app.models.channel_job import ChannelJob
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import Contact
from app.models.message import Attachment, Message
from app.models.messenger_reply import MessengerReply
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import channel_queue as queue, customer_delivery, max_channel, telegram_channel, messages, tickets


@pytest.fixture(params=['max', 'telegram'])
def bot(request, db, contact, monkeypatch, tmp_path):
    channel = request.param
    module = max_channel if channel == 'max' else telegram_channel
    config = SimpleNamespace(base_url='https://mock.invalid', token='local-test', poll_timeout_seconds=1)
    monkeypatch.setattr('app.config.settings.attachments_dir', str(tmp_path))
    for name, target in [('max', max_channel), ('telegram', telegram_channel)]:
        monkeypatch.setattr(target, f'load_{name}_config', lambda _db, n=name: config if n == channel else None)
    client = module.max_client if channel == 'max' else module.telegram_client
    sent = []
    def send(*args, **kwargs):
        mid = str(1000 + len(sent))
        sent.append({'text': args[3], 'buttons': kwargs.get('buttons'), 'id': mid, 'file': bool(kwargs.get('attachments'))})
        return {'message_id': int(mid), 'message': {'body': {'mid': mid}}}
    monkeypatch.setattr(client, 'send_message', send)
    if channel == 'max':
        monkeypatch.setattr(client, 'upload_file', lambda *a, **kw: 'fake-upload')
    else:
        monkeypatch.setattr(client, 'answer_callback_query', lambda *a, **kw: None)
        def send_file(*args, **kwargs):
            mid = str(1000 + len(sent)); sent.append({'file': True, 'text': args[3], 'id': mid, 'buttons': None})
            return {'message_id': int(mid)}
        monkeypatch.setattr(client, 'send_document', send_file)
    setattr(contact, channel + '_id', '111')
    db.add(ChannelConversationState(channel=Channel(channel), external_user_id='111', chat_id='111', contact_id=contact.id))
    db.commit()
    counter = [0]
    def event(text='', reply=None, callback=None, files=None):
        counter[0] += 1
        number = counter[0]
        if channel == 'max':
            if callback:
                return {'update_type': 'message_callback', 'callback': {'callback_id': f'cb-{number}',
                    'user': {'user_id': 111}, 'payload': callback}, 'message': {'recipient': {'chat_id': 111}}}
            message = {'sender': {'user_id': 111, 'name': 'Customer'}, 'recipient': {'chat_id': 111},
                       'body': {'mid': f'in.{number}', 'text': text, 'attachments': files or []}}
            if reply: message['link'] = {'type': 'reply', 'message': {'mid': str(reply)}}
            return {'update_type': 'message_created', 'message': message}
        if callback:
            return {'update_id': number, 'callback_query': {'id': f'cb-{number}', 'from': {'id': 111}, 'data': callback,
                'message': {'chat': {'id': 111, 'type': 'private'}}}}
        message = {'message_id': number, 'from': {'id': 111, 'first_name': 'Customer'},
                   'chat': {'id': 111, 'type': 'private'}, 'text': text}
        if reply: message['reply_to_message'] = {'message_id': int(reply)}
        if files: message['document'] = files[0]
        return {'update_id': number, 'message': message}
    def incoming(update):
        jid = queue.capture_update(db, Channel(channel), update, config)
        if jid is None: return None
        claimed = queue.claim(db, 'inbound', jid)
        assert claimed is not None
        assert queue.process_inbound(db, *claimed), db.get(ChannelJob, jid).last_error
        return db.get(ChannelJob, jid)
    return SimpleNamespace(channel=channel, module=module, config=config, sent=sent, event=event, incoming=incoming, root=tmp_path)


@pytest.fixture()
def actor(db):
    return db.query(User).filter_by(role=UserRole.ADMIN).first()


@pytest.fixture()
def api(db, actor):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    try:
        with TestClient(app) as client: yield client
    finally:
        app.dependency_overrides = previous


def make(db, contact, subject='Phone request', channel=Channel.PHONE):
    return tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type='incident', channel=channel,
        subject=subject, manual_priority='P3', manual_priority_reason='test'), actor=None)


def state(db, bot):
    return db.query(ChannelConversationState).filter_by(channel=Channel(bot.channel), external_user_id='111').one()


def send(db, bot, ticket, actor, body='Please clarify the version', files=None, blocks=None):
    msg = messages.add_message(db, ticket, MessageCreate(direction='outbound', body=body,
        channel=Channel(bot.channel), content_blocks=blocks), author_user=actor, attachments=files)
    job = db.query(ChannelJob).filter_by(message_id=msg.id).one()
    assert queue.process_outbound(db, *queue.claim(db, 'outbound', job.id)) is True
    return msg


def file_event(bot, name='price.xlsx'):
    return [{'type': 'file', 'filename': name, 'payload': {'url': 'https://fake.invalid/file'}}] if bot.channel == 'max' else [{'file_id': name, 'file_name': name, 'mime_type': 'application/octet-stream'}]


def test_phone_requires_explicit_destination_and_never_silently_claims_delivery(db, api, bot, contact):
    ticket = make(db, contact)
    options = api.get(f'/tickets/{ticket.id}/reply-options').json()
    assert options['source_channel'] == 'phone' and options['default_channel'] is None
    assert next(o for o in options['options'] if o['channel'] == bot.channel)['available'] is True
    r = api.post(f'/tickets/{ticket.id}/messages', json={'direction': 'outbound', 'body': 'Question'})
    assert r.status_code == 422
    assert db.query(Message).filter_by(ticket_id=ticket.id).count() == 0
    db.refresh(ticket); assert ticket.first_response_at is None
    r = api.post(f'/tickets/{ticket.id}/messages', json={'direction': 'outbound', 'body': 'Question', 'channel': bot.channel})
    assert r.status_code == 201 and r.json()['delivery']['state'] == 'pending'
    assert r.json()['channel'] == bot.channel
    assert api.get(f'/tickets/{ticket.id}/reply-options').json()['default_channel'] == bot.channel
    db.refresh(ticket); assert ticket.channel == Channel.PHONE and ticket.first_response_at is None
    assert bot.sent == []


def test_phone_to_bot_answer_has_context_and_plain_reply_does_not_create_task(db, bot, contact, actor):
    old = make(db, contact, 'Another issue')
    target = make(db, contact, 'Load new prices')
    s = state(db, bot); s.active_ticket_id = old.id; db.commit()
    msg = send(db, bot, target, actor)
    assert bot.sent[0]['text'] == f'Заявка {target.display_number} — Load new prices\n\nPlease clarify the version'
    assert bot.sent[0]['buttons'][0][0]['payload'] == f'reply:{target.id}'
    assert msg.body == 'Please clarify the version'
    assert state(db, bot).active_ticket_id == target.id
    before = db.query(Ticket).filter_by(contact_id=contact.id).count()
    bot.incoming(bot.event('Version 3.2'))
    assert db.query(Ticket).filter_by(contact_id=contact.id).count() == before
    reply = db.query(Message).filter_by(ticket_id=target.id, direction=MessageDirection.INBOUND).one()
    assert reply.body == 'Version 3.2' and reply.channel == Channel(bot.channel)


def test_native_quote_overrides_another_ticket_and_pending_new_flow(db, bot, contact, actor):
    target, other = make(db, contact, 'Quoted issue'), make(db, contact, 'Other issue')
    outbound = send(db, bot, target, actor)
    remote = bot.sent[0]['id']
    s = state(db, bot); s.active_ticket_id = other.id; s.awaiting_new_ticket_text = True
    s.updated_at = datetime.now(timezone.utc); db.commit()
    bot.incoming(bot.event('Here is the answer', reply=remote))
    assert db.query(Ticket).filter_by(contact_id=contact.id).count() == 2
    reply = db.query(Message).filter_by(ticket_id=target.id, direction=MessageDirection.INBOUND).one()
    assert reply.reply_to_message_id == outbound.id
    assert state(db, bot).active_ticket_id == target.id and not state(db, bot).awaiting_new_ticket_text
    assert db.query(Message).filter_by(ticket_id=other.id).count() == 0


def test_answer_button_selects_phone_ticket_and_cancels_new_prompt(db, bot, contact, actor):
    target = make(db, contact)
    s = state(db, bot); s.awaiting_new_ticket_text = True; db.commit()
    bot.incoming(bot.event(callback=f'reply:{target.id}'))
    bot.incoming(bot.event('Additional information'))
    assert db.query(Ticket).filter_by(contact_id=contact.id).count() == 1
    assert db.query(Message).filter_by(ticket_id=target.id).one().body == 'Additional information'


def test_resolved_reply_reopens_the_same_ticket(db, bot, contact):
    ticket = make(db, contact)
    tickets.transition_status(db, ticket, TicketStatus.IN_PROGRESS, None)
    tickets.transition_status(db, ticket, TicketStatus.RESOLVED, None)
    resolved_at = ticket.resolved_at
    s = state(db, bot); s.active_ticket_id = ticket.id; db.commit()
    bot.incoming(bot.event('The issue remains'))
    db.refresh(ticket)
    assert ticket.status == TicketStatus.IN_PROGRESS and ticket.reopen_count == 1
    assert ticket.resolved_at == resolved_at and db.query(Ticket).filter_by(contact_id=contact.id).count() == 1


def test_ambiguous_messages_and_files_wait_then_attach_once_without_redownload(db, bot, contact, monkeypatch):
    a, b = make(db, contact, 'A'), make(db, contact, 'B')
    downloads = []
    def data(config, attachment):
        downloads.append(True)
        return 'price.xlsx', b'original spreadsheet', 'application/octet-stream'
    monkeypatch.setattr(bot.module, '_attachment_data', data)
    jobs = [bot.incoming(bot.event(f'Message {i}', files=file_event(bot))) for i in range(3)]
    assert all(job.state == 'waiting' and job.ticket_id is None for job in jobs)
    assert db.query(Ticket).filter_by(contact_id=contact.id).count() == 2
    assert db.query(Message).filter(Message.ticket_id.in_([a.id, b.id])).count() == 0
    assert len(list((bot.root/'_pending').iterdir())) == 3
    callback = bot.event(callback=f'reply:{a.id}')
    bot.incoming(callback)
    replies = db.query(Message).filter_by(ticket_id=a.id).order_by(Message.created_at, Message.id).all()
    assert [r.body for r in replies] == [f'Message {i}' for i in range(3)]
    assert all(Path(r.attachments[0].stored_path).read_bytes() == b'original spreadsheet' for r in replies)
    assert len(downloads) == 3 and not list((bot.root/'_pending').iterdir())
    assert bot.incoming(callback) is None
    bot.incoming(bot.event(callback=f'reply:{a.id}'))
    assert db.query(Message).filter_by(ticket_id=a.id).count() == 3
    assert db.query(Message).filter_by(ticket_id=b.id).count() == 0
    assert all(db.get(ChannelJob, job.id).state == 'processed' for job in jobs)
    assert bot.sent == []  # all acknowledgments are queued, no external sends


def test_explicit_new_button_materializes_buffered_messages_as_one_new_task(db, bot, contact, monkeypatch):
    make(db, contact, 'A'); make(db, contact, 'B')
    monkeypatch.setattr(bot.module, '_attachment_data', lambda *a: ('price.xlsx', b'original', None))
    bot.incoming(bot.event('A new question', files=file_event(bot)))
    bot.incoming(bot.event('And more details'))
    bot.incoming(bot.event(callback='new_ticket'))
    assert db.query(Ticket).filter_by(contact_id=contact.id).count() == 3
    target = db.query(Ticket).filter_by(contact_id=contact.id, subject='A new question').one()
    replies = db.query(Message).filter_by(ticket_id=target.id).order_by(Message.id).all()
    assert [r.body for r in replies] == ['A new question', 'And more details']
    assert Path(replies[0].attachments[0].stored_path).read_bytes() == b'original'
    assert db.query(ChannelJob).filter_by(channel=bot.channel, state='waiting').count() == 0


def test_closed_quote_waits_for_explicit_followup_instead_of_creating_duplicates(db, bot, contact, actor):
    ticket = make(db, contact)
    send(db, bot, ticket, actor)
    remote = bot.sent[0]['id']
    tickets.transition_status(db, ticket, TicketStatus.IN_PROGRESS, None)
    tickets.transition_status(db, ticket, TicketStatus.RESOLVED, None)
    tickets.transition_status(db, ticket, TicketStatus.CLOSED, None)
    waiting = bot.incoming(bot.event('Need more help', reply=remote))
    assert waiting.state == 'waiting' and db.query(Ticket).filter_by(contact_id=contact.id).count() == 1
    bot.incoming(bot.event(callback=f'continue:{ticket.id}'))
    followup = db.query(Ticket).filter_by(contact_id=contact.id, parent_ticket_id=ticket.id).one()
    assert db.query(Message).filter_by(ticket_id=followup.id, direction=MessageDirection.INBOUND).one().body == 'Need more help'
    db.refresh(ticket); assert ticket.status == TicketStatus.CLOSED


def test_reply_to_file_part_knows_ticket_and_original_message(db, bot, contact, actor):
    target = make(db, contact, 'Files question')
    original = send(db, bot, target, actor, body='', files=[('one.txt', b'hello', 'text/plain')])
    remote = bot.sent[-1]['id']
    assert len(bot.sent) == 2 and bot.sent[0]['text'].startswith(f'Заявка {target.display_number}')
    assert bot.sent[-1]['file']
    ref = db.query(MessengerReply).filter_by(channel=bot.channel, external_message_id=remote).one()
    assert ref.ticket_id == target.id and ref.message_id == original.id
    bot.incoming(bot.event('Question about this file', reply=remote))
    inbound = db.query(Message).filter_by(ticket_id=target.id, direction=MessageDirection.INBOUND).one()
    assert inbound.reply_to_message_id == original.id


def test_foreign_ticket_callback_and_quote_do_not_leak_or_attach(db, bot, contact, organization):
    other = Contact(organization_id=organization.id, full_name='Other customer'); db.add(other); db.commit()
    foreign = make(db, other, 'SECRET other customer ticket')
    own = make(db, contact, 'Own ticket')
    db.add(MessengerReply(channel=bot.channel, account=__import__('app.services.messenger_dialog',fromlist=['account']).account(bot.config),
        chat_id='111', external_message_id='999', ticket_id=foreign.id, contact_id=other.id)); db.commit()
    bot.incoming(bot.event('A quote', reply='999'))
    bot.incoming(bot.event(callback=f'reply:{foreign.id}'))
    assert db.query(Message).filter_by(ticket_id=foreign.id).count() == 0
    prompts = db.query(ChannelJob).filter_by(kind='outbound', channel=bot.channel).all()
    assert all('SECRET' not in job.payload.get('text', '') for job in prompts)
    assert db.query(Ticket).filter_by(contact_id=contact.id).count() == 1


def test_internal_phone_note_is_not_delivered_but_portal_reply_is_explicit(db, api, bot, contact):
    ticket = make(db, contact)
    r = api.post(f'/tickets/{ticket.id}/messages', json={'direction':'internal_note','body':'Internal only'})
    assert r.status_code == 201 and r.json()['delivery'] is None
    r = api.post(f'/tickets/{ticket.id}/messages', json={'direction':'outbound','body':'Cabinet reply','channel':'portal'})
    assert r.status_code == 201 and r.json()['delivery'] is None
    assert db.query(ChannelJob).filter_by(ticket_id=ticket.id).count() == 0
    assert bot.sent == []


def test_disabled_or_unbound_channel_cannot_be_sent_as_success(db, api, bot, contact, monkeypatch):
    ticket = make(db, contact)
    monkeypatch.setattr(bot.module, f'load_{bot.channel}_config', lambda _: None)
    r = api.post(f'/tickets/{ticket.id}/messages', json={'direction':'outbound','body':'Never sent','channel':bot.channel})
    assert r.status_code == 422 and db.query(Message).filter_by(ticket_id=ticket.id).count() == 0


def test_abandoned_new_ticket_prompt_does_not_create_a_duplicate(db, bot, contact):
    ticket = make(db, contact)
    s = state(db, bot); s.awaiting_new_ticket_text = True
    s.updated_at = datetime.now(timezone.utc) - timedelta(hours=2); db.commit()
    bot.incoming(bot.event('Answer to the existing issue'))
    assert db.query(Ticket).filter_by(contact_id=contact.id).count() == 1
    assert db.query(Message).filter_by(ticket_id=ticket.id).one().body == 'Answer to the existing issue'


def test_failed_staging_rolls_back_files_and_retries_without_ack(db, bot, contact, monkeypatch):
    make(db, contact, 'A'); make(db, contact, 'B')
    calls = [0]
    def data(*args):
        calls[0] += 1
        if calls[0] == 2: raise RuntimeError('temporary download error')
        return 'one.txt', b'original', 'text/plain'
    monkeypatch.setattr(bot.module, '_attachment_data', data)
    event = bot.event('Files', files=file_event(bot))
    if bot.channel == 'max': event['message']['body']['attachments'] *= 2
    else: event['message']['photo'] = [{'file_id':'photo','width':1,'height':1}]
    jid = queue.capture_update(db, Channel(bot.channel), event, bot.config)
    assert queue.process_inbound(db, *queue.claim(db, 'inbound', jid)) is False
    assert db.get(ChannelJob, jid).state == 'retry'
    assert not list(bot.root.rglob('*.*'))
    assert db.query(Message).filter(Message.ticket_id.in_([t.id for t in db.query(Ticket).filter_by(contact_id=contact.id)])).count() == 0
    assert db.query(ChannelJob).filter(ChannelJob.event_key.like(f'event:{jid}:reply:%')).count() == 0
    job = db.get(ChannelJob, jid); job.available_at = datetime.now(timezone.utc)-timedelta(seconds=1); db.commit()
    assert queue.process_inbound(db, *queue.claim(db, 'inbound', jid)) is True
    db.refresh(job); assert job.state == 'waiting'
    assert len(job.payload['_sd_pending_files']) == 2
    assert bot.sent == []


def test_failed_selection_preserves_staged_files_and_retries_atomically(db, bot, contact, monkeypatch):
    from app.services import attachments
    target = make(db, contact, 'A'); make(db, contact, 'B')
    monkeypatch.setattr(bot.module, '_attachment_data', lambda *a: ('price.xlsx', b'original', None))
    first = bot.incoming(bot.event('First', files=file_event(bot)))
    second = bot.incoming(bot.event('Second', files=file_event(bot)))
    original = attachments.store_attachment
    count = [0]
    def failing(*args, **kwargs):
        count[0] += 1
        if count[0] == 2: raise RuntimeError('temporary disk error')
        return original(*args, **kwargs)
    monkeypatch.setattr(attachments, 'store_attachment', failing)
    event = bot.event(callback=f'reply:{target.id}')
    jid = queue.capture_update(db, Channel(bot.channel), event, bot.config)
    assert queue.process_inbound(db, *queue.claim(db, 'inbound', jid)) is False
    assert db.query(Message).filter_by(ticket_id=target.id).count() == 0
    assert all(db.get(ChannelJob, j.id).state == 'waiting' for j in [first, second])
    assert len(list((bot.root/'_pending').iterdir())) == 2
    assert db.query(ChannelJob).filter(ChannelJob.event_key.like(f'event:{jid}:reply:%')).count() == 0
    monkeypatch.setattr(attachments, 'store_attachment', original)
    job = db.get(ChannelJob, jid); job.available_at = datetime.now(timezone.utc)-timedelta(seconds=1); db.commit()
    assert queue.process_inbound(db, *queue.claim(db, 'inbound', jid)) is True
    assert db.query(Message).filter_by(ticket_id=target.id).count() == 2
    assert not list((bot.root/'_pending').iterdir())


def test_phone_status_notice_uses_selected_bot_and_can_be_answered_by_quote(db, bot, contact, actor):
    target = make(db, contact)
    send(db, bot, target, actor)
    tickets.transition_status(db, target, TicketStatus.IN_PROGRESS, actor)
    job = db.query(ChannelJob).filter(ChannelJob.ticket_id==target.id, ChannelJob.message_id.is_(None),
        ChannelJob.channel==bot.channel, ChannelJob.payload['contact_id'].as_integer()==contact.id).one()
    assert queue.process_outbound(db, *queue.claim(db, 'outbound', job.id)) is True
    remote = bot.sent[-1]['id']
    assert f'Заявка: {target.display_number}' in bot.sent[-1]['text']
    bot.incoming(bot.event('Thanks for the update', reply=remote))
    assert db.query(Ticket).filter_by(contact_id=contact.id).count() == 1
    assert db.query(Message).filter_by(ticket_id=target.id, direction=MessageDirection.INBOUND).one().body == 'Thanks for the update'


def test_plain_reply_after_closure_does_not_jump_to_unrelated_open_ticket(db, bot, contact):
    closed = make(db, contact, 'Closed')
    tickets.transition_status(db, closed, TicketStatus.IN_PROGRESS, None)
    tickets.transition_status(db, closed, TicketStatus.RESOLVED, None)
    tickets.transition_status(db, closed, TicketStatus.CLOSED, None)
    other = make(db, contact, 'Unrelated')
    s = state(db, bot); s.active_ticket_id = closed.id; db.commit()
    job = bot.incoming(bot.event('One more question about this'))
    assert job.state == 'waiting'
    assert db.query(Message).filter_by(ticket_id=other.id).count() == 0
    assert db.query(Ticket).filter_by(contact_id=contact.id).count() == 2


def test_identity_merge_preserves_native_reply_to_file_context(db, bot, contact, actor, organization):
    from app.services import messenger_common
    target = make(db, contact)
    send(db, bot, target, actor, body='', files=[('one.txt', b'original', 'text/plain')])
    remote = bot.sent[-1]['id']
    keeper = Contact(organization_id=organization.id, full_name='Confirmed phone contact')
    db.add(keeper); db.commit()
    messenger_common.merge_contacts(db, from_contact=contact, into_contact=keeper)
    bot.incoming(bot.event('Answer after linking phone', reply=remote))
    db.refresh(target)
    assert target.contact_id == keeper.id
    assert db.query(Message).filter_by(ticket_id=target.id, direction=MessageDirection.INBOUND).one().body == 'Answer after linking phone'
    assert db.query(MessengerReply).filter_by(external_message_id=remote, contact_id=keeper.id).one().ticket_id == target.id


def test_legacy_sent_answer_repairs_stale_selection_but_explicit_choice_wins(db, bot, contact, actor):
    target = make(db, contact, 'Legacy answer target')
    other = make(db, contact, 'Old active ticket')
    message = send(db, bot, target, actor)
    job = db.query(ChannelJob).filter_by(message_id=message.id).one()
    job.payload = {k:v for k,v in job.payload.items() if k != 'ticket_context'}
    s = state(db, bot); s.active_ticket_id = other.id
    s.updated_at = job.completed_at - timedelta(hours=1); db.commit()
    bot.incoming(bot.event('Answer to legacy request'))
    assert db.query(Message).filter_by(ticket_id=target.id, direction=MessageDirection.INBOUND).one().body == 'Answer to legacy request'
    bot.incoming(bot.event(callback=f'reply:{other.id}'))
    bot.incoming(bot.event('Explicitly about the other task'))
    assert db.query(Message).filter_by(ticket_id=other.id).one().body == 'Explicitly about the other task'
