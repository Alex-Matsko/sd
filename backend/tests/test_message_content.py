"""Audience isolation, original screenshots, delivery ordering and retries. No network."""
import base64
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routers.portal import get_current_contact
from app.core.enums import Channel, MessageDirection, Priority, TicketType, UserRole
from app.db import get_db
from app.main import app
from app.models.channel_job import ChannelJob
from app.models.message import Message
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import messages, tickets, channel_transport, email_channel, telegram_channel, telegram_client, max_channel, max_client
from app.services.channel_queue import PermanentChannelFailure
from app.services.message_content import MessageContentError

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1foAAAAASUVORK5CYII=')


@pytest.fixture()
def context(db, contact, tmp_path, monkeypatch):
    monkeypatch.setattr('app.config.settings.attachments_dir', str(tmp_path))
    actor = db.query(User).filter(User.role == UserRole.ADMIN).first()
    ticket = tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT,
        channel=Channel.TELEGRAM, subject='Сообщение со скриншотами', manual_priority=Priority.P3,
        manual_priority_reason='test'), actor=None)
    return actor, ticket


def payload(direction=MessageDirection.OUTBOUND, **kw):
    return MessageCreate(direction=direction, body='ignored legacy fallback', request_id=uuid4(), content_blocks=[
        {'type': 'text', 'text': 'Сначала <текст>'}, {'type': 'image', 'file_index': 0},
        {'type': 'text', 'text': 'После скриншота'},
    ], **kw)


def test_original_bytes_blocks_and_idempotent_retries(db, contact, context):
    actor, ticket = context
    draft = payload()
    uploads = [('screen.png', PNG, 'application/octet-stream')]
    first = messages.add_message(db, ticket, draft, author_user=actor, attachments=uploads)
    repeated = messages.add_message(db, ticket, draft, author_user=actor, attachments=uploads)
    assert first.id == repeated.id
    assert first.body == 'Сначала <текст>\nПосле скриншота'
    assert first.content_blocks[1] == {'type': 'image', 'attachment_id': first.attachments[0].id}
    assert first.attachments[0].mime_type == 'image/png'
    from pathlib import Path
    assert Path(first.attachments[0].stored_path).read_bytes() == PNG
    assert db.query(ChannelJob).filter_by(message_id=first.id).count() == 1


@pytest.mark.parametrize('uploads', [[], [('fake.png', b'<svg onload=alert(1)>', 'image/png')]])
def test_invalid_inline_image_rejected_before_any_message_or_job(db, context, uploads):
    actor, ticket = context
    with pytest.raises(MessageContentError):
        messages.add_message(db, ticket, payload(), author_user=actor, attachments=uploads)
    assert db.query(Message).filter_by(ticket_id=ticket.id).count() == 0
    assert db.query(ChannelJob).filter_by(ticket_id=ticket.id).count() == 0


@pytest.mark.parametrize('channel', ['telegram', 'max'])
def test_delivery_preserves_text_image_text_and_resumes_at_failed_part(db, context, monkeypatch, channel):
    actor, ticket = context
    ticket.channel = Channel(channel); db.commit()
    msg = messages.add_message(db, ticket, payload(), author_user=actor, attachments=[('s.png', PNG, 'image/png')])
    job = db.query(ChannelJob).filter_by(message_id=msg.id).one()
    job.payload = {**job.payload, 'recipient': '42'}; db.commit()
    module, client = (telegram_channel, telegram_client) if channel == 'telegram' else (max_channel, max_client)
    monkeypatch.setattr(module, f'load_{channel}_config', lambda _db: SimpleNamespace(base_url='https://unused.invalid', token='fake'))
    sent = []
    def send_text(*args, **kwargs):
        if kwargs.get('attachments'):
            sent.append(('file', PNG))
        else:
            sent.append(('text', args[3]))
        return {'message_id': 123, 'message': {'body': {'mid': '123'}}}
    monkeypatch.setattr(client, 'send_message', send_text)
    if channel == 'telegram':
        def failed_file(*args, **kwargs): raise RuntimeError('temporary upload failure')
        monkeypatch.setattr(client, 'send_document', failed_file)
    else:
        def failed_file(*args, **kwargs): raise RuntimeError('temporary upload failure')
        monkeypatch.setattr(client, 'upload_file', failed_file)
    with pytest.raises(RuntimeError, match='temporary'):
        channel_transport.send_job(db, job)
    assert job.payload['content_parts_sent'] == 1
    assert sent == [('text', 'Сначала <текст>')]
    if channel == 'telegram':
        def send_file(*args, **kwargs):
            sent.append(('file', args[4])); return {'message_id': 124}
        monkeypatch.setattr(client, 'send_document', send_file)
    else:
        monkeypatch.setattr(client, 'upload_file', lambda *a, **k: 'file-token')
    channel_transport.send_job(db, job)
    assert sent == [('text', 'Сначала <текст>'), ('file', PNG), ('text', 'После скриншота')]
    assert job.payload['content_parts_sent'] == 3
    channel_transport.send_job(db, job)
    assert len(sent) == 3


def test_internal_note_cannot_be_delivered_even_if_a_job_was_created(db, context):
    actor, ticket = context
    note = messages.add_message(db, ticket, payload(MessageDirection.INTERNAL_NOTE), author_user=actor,
                                attachments=[('s.png', PNG, 'image/png')])
    assert note.delivery is None
    fake = SimpleNamespace(message_id=note.id)
    with pytest.raises(PermanentChannelFailure, match='Внутренняя'):
        channel_transport.send_job(db, fake)


def test_typed_endpoints_and_portal_do_not_expose_internal_text_or_images(db, contact, context):
    actor, ticket = context
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_current_contact] = lambda: contact
    try:
        with TestClient(app) as client:
            draft = payload(MessageDirection.INTERNAL_NOTE).model_dump(mode='json')
            r = client.post(f'/tickets/{ticket.id}/notes/send', data={'payload': json.dumps(draft)}, files={'files': ('s.png', PNG, 'image/png')})
            assert r.status_code == 201, r.text
            note = r.json(); file_id = note['attachments'][0]['id']
            wrong = client.post(f'/tickets/{ticket.id}/replies/send', data={'payload': json.dumps(draft)})
            assert wrong.status_code == 422
            visible = client.get(f'/portal/tickets/{ticket.id}').json()
            assert visible['messages'] == []
            assert client.get(f'/portal/tickets/{ticket.id}/attachments/{file_id}').status_code == 404
            draft['direction'] = 'outbound'; draft['request_id'] = str(uuid4())
            r = client.post(f'/tickets/{ticket.id}/replies/send', data={'payload': json.dumps(draft)}, files={'files': ('s.png', PNG, 'image/png')})
            assert r.status_code == 201, r.text
            visible = client.get(f'/portal/tickets/{ticket.id}').json()['messages']
            assert len(visible) == 1 and visible[0]['content_blocks'][1]['type'] == 'image'
            response = client.get(f"/portal/tickets/{ticket.id}/attachments/{visible[0]['attachments'][0]['id']}")
            assert response.content == PNG
    finally:
        app.dependency_overrides.clear()


def test_email_is_one_html_message_with_escaped_text_and_original_inline_image(context, monkeypatch):
    _, ticket = context
    captured = []
    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def send_message(self, message): captured.append(message)
    monkeypatch.setattr(email_channel.smtplib, 'SMTP', SMTP)
    cfg = SimpleNamespace(from_display_name='Поддержка', from_address='support@example.org',
        smtp_host='unused.invalid', smtp_port=25, smtp_use_tls=False, smtp_username=None)
    email_channel.send_outbound_email(cfg, 'test@example.org', ticket, 'Сначала\nПосле', None,
        attachments=[('other.txt', b'other', 'text/plain'), ('screen.png', PNG, 'image/png')], attachment_ids=[1, 2],
        content_blocks=[{'type': 'text', 'text': '<script>alert(1)</script>'}, {'type': 'image', 'attachment_id': 2}, {'type': 'text', 'text': 'После'}])
    assert len(captured) == 1
    html = captured[0].get_body(preferencelist=('html',)).get_content()
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert html.index('&lt;script&gt;') < html.index('cid:sd-image-2') < html.index('После')
    image = next(p for p in captured[0].walk() if p.get('Content-ID') == '<sd-image-2>')
    assert image.get_payload(decode=True) == PNG
    assert image.get_content_disposition() == 'inline'


def test_ticket_number_sorting_is_numeric_and_old_search_still_works(db, contact, context):
    actor, first = context
    second = tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PORTAL,
        subject='Другой номер', manual_priority=Priority.P3, manual_priority_reason='test'), actor=None)
    assert first.display_number == f'OH-{first.number:06d}'
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    try:
        with TestClient(app) as client:
            result = client.get('/tickets', params={'organization_id': contact.organization_id, 'sort': 'number_asc'}).json()
            assert [r['number'] for r in result] == sorted([first.number, second.number])
            result = client.get('/tickets', params={'organization_id': contact.organization_id, 'sort': 'number_desc'}).json()
            assert [r['number'] for r in result] == sorted([first.number, second.number], reverse=True)
            for q in [f'OH-{first.number}', first.display_number, str(first.number)]:
                assert first.id in [r['id'] for r in client.get('/tickets', params={'q': q}).json()]
    finally:
        app.dependency_overrides.clear()


def test_client_can_send_one_ordered_message_back_to_support(db, contact, context):
    _, ticket = context
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_contact] = lambda: contact
    try:
        with TestClient(app) as client:
            blocks = [{'type': 'text', 'text': 'До'}, {'type': 'image', 'file_index': 0}, {'type': 'text', 'text': 'После'}]
            r = client.post(f'/portal/tickets/{ticket.id}/messages/send', data={'body': 'До\nПосле', 'request_id': str(uuid4()),
                'content_blocks': json.dumps(blocks)}, files={'files': ('screen.png', PNG, 'image/png')})
            assert r.status_code == 201, r.text
            assert r.json()['content_blocks'][2]['text'] == 'После'
            assert r.json()['attachments'][0]['mime_type'] == 'image/png'
            visible = client.get(f'/portal/tickets/{ticket.id}').json()['messages']
            assert len(visible) == 1 and visible[0]['content_blocks'] == r.json()['content_blocks']
    finally:
        app.dependency_overrides.clear()
