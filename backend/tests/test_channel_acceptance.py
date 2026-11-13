"""Real local SMTP/IMAP sockets -> durable queue -> staff API -> SMTP with a file.

The entire acceptance scenario uses loopback simulators, never live accounts.
"""
from contextlib import contextmanager
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import json
import socketserver
import threading
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.enums import Channel, UserRole
from app.db import get_db
from app.main import app
from app.models.channel_job import ChannelJob
from app.models.contact import ContactEmail
from app.models.message import Message
from app.models.user import User
from app.schemas.integration_setting import IntegrationSettingUpdate
from app.services import channel_queue as queue, email_channel, integration_settings


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@contextmanager
def listening(handler, **attributes):
    with Server(("127.0.0.1", 0), handler) as server:
        for key, value in attributes.items():
            setattr(server, key, value)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=3)


class SMTP(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 localhost acceptance SMTP\r\n")
        while line := self.rfile.readline():
            command = line.decode().split()[0].upper()
            if command in ("EHLO", "HELO"):
                self.wfile.write(b"250-localhost\r\n250 SIZE 52428800\r\n")
            elif command in ("MAIL", "RCPT", "RSET", "NOOP"):
                self.wfile.write(b"250 OK\r\n")
            elif command == "DATA":
                if self.server.fail_next:
                    self.server.fail_next = False
                    self.wfile.write(b"451 temporary simulated outage\r\n")
                    continue
                self.wfile.write(b"354 Send message\r\n")
                parts = []
                while (part := self.rfile.readline()) != b".\r\n":
                    if not part:
                        return
                    parts.append(part[1:] if part.startswith(b"..") else part)
                self.server.messages.append(b"".join(parts))
                self.wfile.write(b"250 accepted\r\n")
            elif command == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"500 unsupported\r\n")


class IMAP(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"* OK localhost acceptance IMAP\r\n")
        while line := self.rfile.readline():
            pieces = line.decode().strip().split()
            tag, command = pieces[0], pieces[1].upper()
            if command == "CAPABILITY":
                self.wfile.write(b"* CAPABILITY IMAP4rev1 UIDPLUS\r\n")
            elif command == "SELECT":
                self.wfile.write(b"* 1 EXISTS\r\n* OK [UIDVALIDITY 73] valid\r\n")
            elif command == "UID":
                subcommand = pieces[2].upper()
                if subcommand == "SEARCH":
                    self.wfile.write(b"* SEARCH" + (b"" if self.server.seen else b" 1") + b"\r\n")
                elif subcommand == "FETCH":
                    raw = self.server.raw
                    self.wfile.write(f"* 1 FETCH (UID 1 BODY[] {{{len(raw)}}}\r\n".encode() + raw + b")\r\n")
                elif subcommand == "STORE":
                    # Acknowledgement must follow the durable journal commit.
                    self.server.seen = True
                    self.wfile.write(b"* 1 FETCH (FLAGS (\\Seen))\r\n")
            elif command == "LOGOUT":
                self.wfile.write(b"* BYE done\r\n" + f"{tag} OK logout\r\n".encode())
                return
            self.wfile.write(f"{tag} OK completed\r\n".encode())


def test_local_email_round_trip_with_outage_attachment_and_request_replay(db, contact, monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.settings.attachments_dir", str(tmp_path))
    sender = "acceptance@example.org"
    db.add(ContactEmail(contact_id=contact.id, email=sender, is_primary=True)); db.commit()
    mail = EmailMessage()
    mail["From"], mail["To"], mail["Subject"], mail["Message-ID"] = sender, "support@example.org", "Не работает VPN", "<acceptance-inbound@example.org>"
    mail.set_content("Помогите восстановить доступ")
    mail.add_attachment(b"inbound screenshot", maintype="text", subtype="plain", filename="input.txt")
    raw = mail.as_bytes(policy=policy.SMTP)
    with listening(SMTP, messages=[], fail_next=True) as smtp, listening(IMAP, raw=raw, seen=False) as imap:
        setting = integration_settings.upsert(db, Channel.EMAIL, IntegrationSettingUpdate(is_enabled=True, config={
            "imap_host": "127.0.0.1", "imap_port": imap.server_address[1], "imap_use_ssl": False,
            "imap_username": "local", "imap_folder": "INBOX", "smtp_host": "127.0.0.1",
            "smtp_port": smtp.server_address[1], "smtp_use_tls": False, "smtp_username": "",
            "from_address": "support@example.org",
        }, secrets={"imap_password": "local"}))
        config = email_channel.load_email_config(db)
        assert email_channel.poll_inbox(db, config) == 1
        job = db.query(ChannelJob).filter_by(kind="inbound", channel="email").order_by(ChannelJob.id.desc()).first()
        assert job.raw_body == raw and job.state == "pending" and imap.seen
        assert queue.process_inbound(db, *queue.claim(db, "inbound", job.id))
        db.refresh(job)
        incoming = db.query(Message).filter_by(ticket_id=job.ticket_id).one()
        assert incoming.attachments[0].filename == "input.txt"
        assert email_channel.poll_inbox(db, config) == 0
        actor = db.query(User).filter(User.role == UserRole.ADMIN).first()
        previous = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: actor
        try:
            request_id = str(uuid4())
            payload = {"direction": "outbound", "body": "Доступ восстановлен", "request_id": request_id}
            with TestClient(app) as client:
                response = client.post(f"/tickets/{job.ticket_id}/messages/send", data={"payload": json.dumps(payload)},
                                       files={"files": ("output.txt", b"outbound instructions", "text/plain")})
                assert response.status_code == 201, response.text
                body = response.json()
                assert body["delivery"]["state"] == "pending" and body["attachments"][0]["filename"] == "output.txt"
                outgoing_id = body["delivery"]["id"]
                assert not queue.process_outbound(db, *queue.claim(db, "outbound", outgoing_id))
                assert client.get(f"/tickets/{job.ticket_id}/messages").json()[-1]["delivery"]["state"] == "retry"
                queue.retry(db, db.get(ChannelJob, outgoing_id))
                assert queue.process_outbound(db, *queue.claim(db, "outbound", outgoing_id))
                replay = client.post(f"/tickets/{job.ticket_id}/messages/send", data={"payload": json.dumps(payload)},
                                     files={"files": ("output.txt", b"outbound instructions", "text/plain")})
                assert replay.status_code == 201 and replay.json()["id"] == body["id"]
                assert queue.claim(db, "outbound", outgoing_id) is None
        finally:
            app.dependency_overrides = previous
        assert len(smtp.messages) == 1
        delivered = BytesParser(policy=policy.default).parsebytes(smtp.messages[0])
        assert delivered["To"] == sender
        assert delivered["In-Reply-To"] == "<acceptance-inbound@example.org>"
        assert "Доступ восстановлен" in delivered.get_body(preferencelist=("plain",)).get_content()
        assert [(part.get_filename(), part.get_payload(decode=True)) for part in delivered.iter_attachments()] == [("output.txt", b"outbound instructions")]


import httpx
import pytest
from app.core.enums import MessageDirection
from app.schemas.message import MessageCreate
from app.services import max_channel, messages, telegram_channel


@pytest.mark.parametrize("channel", [Channel.TELEGRAM, Channel.MAX])
def test_bot_event_file_reply_and_temporary_upload_failure(db, contact, monkeypatch, tmp_path, channel):
    """Provider-shaped HTTP responses exercise capture, ingestion and real client code."""
    monkeypatch.setattr("app.config.settings.attachments_dir", str(tmp_path))
    from tests.test_max_channel import _text_update as max_update
    from tests.test_telegram_channel import _text_update as telegram_update
    if channel == Channel.MAX:
        contact.max_id = "42"
        event = max_update(user_id="42", chat_id="chat-42", text="Нужна помощь", mid="incoming-mid")
        event["message"]["body"]["attachments"] = [{"type": "file", "payload": {"url": "https://files.provider.test/input", "filename": "input.txt"}}]
    else:
        contact.telegram_id = "42"
        event = telegram_update(user_id=42, chat_id=42, text="Нужна помощь", mid=55)
        event["message"]["document"] = {"file_id": "input-file", "file_name": "input.txt", "mime_type": "text/plain"}
    db.commit()
    integration_settings.upsert(db, channel, IntegrationSettingUpdate(is_enabled=True, config={"base_url": "https://provider.test"}, secrets={"bot_token": "42:test"}))
    posted, uploaded = [], []
    fail_once = [True]
    real_client = httpx.Client
    def handler(request):
        path = request.url.path
        if path.endswith("getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [event]})
        if path == "/updates":
            return httpx.Response(200, json={"updates": [event], "marker": 99})
        if path.endswith("setMyCommands"):
            return httpx.Response(200, json={"ok": True, "result": True})
        if path == "/me/commands":
            return httpx.Response(200, json={})
        if path.endswith("getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "input.txt"}})
        if path.endswith("/input.txt") or request.url.host == "files.provider.test":
            return httpx.Response(200, content=b"incoming attachment")
        if path == "/uploads":
            uploaded.append("MAX upload request")
            return httpx.Response(200, json={"url": "https://upload.provider.test/upload"})
        if request.url.host == "upload.provider.test":
            assert b"outgoing attachment" in request.content
            return httpx.Response(200, json={"token": "file-token"})
        if path.endswith("sendDocument"):
            if fail_once[0]:
                fail_once[0] = False
                return httpx.Response(503, json={"ok": False})
            assert b"outgoing attachment" in request.content
            posted.append({"file": "output.txt"})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 200}})
        if path.endswith("sendMessage") or path == "/messages":
            payload = json.loads(request.content)
            is_file = any(item.get("type") == "file" for item in payload.get("attachments", []))
            if is_file and fail_once[0]:
                fail_once[0] = False
                return httpx.Response(503, json={"code": "attachment.not.ready"})
            posted.append(payload)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(posted)},
                                            "message": {"body": {"mid": f"sent-{len(posted)}"}}})
        raise AssertionError(f"Unexpected simulated provider request: {request.method} {path}")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    module = telegram_channel if channel == Channel.TELEGRAM else max_channel
    config = module.load_telegram_config(db) if channel == Channel.TELEGRAM else module.load_max_config(db)
    module.poll_updates(db, config)
    inbox = db.query(ChannelJob).filter_by(kind="inbound", channel=channel.value).one()
    assert inbox.state == "pending" and not posted
    assert queue.process_inbound(db, *queue.claim(db, "inbound", inbox.id))
    ticket = db.query(Message).filter_by(author_contact_id=contact.id, direction=MessageDirection.INBOUND).one().ticket
    incoming = db.query(Message).filter_by(ticket_id=ticket.id, direction=MessageDirection.INBOUND).one()
    assert incoming.attachments[0].filename == "input.txt"
    queue.run_batch(db, "outbound")  # acknowledgement after the inbox transaction has committed
    assert posted
    posted.clear()
    actor = db.query(User).filter(User.role == UserRole.ADMIN).first()
    reply = messages.add_message(db, ticket, MessageCreate(direction=MessageDirection.OUTBOUND, body="Готово", request_id=uuid4()),
                                 author_user=actor, attachments=[("output.txt", b"outgoing attachment", "text/plain")])
    assert not queue.process_outbound(db, *queue.claim(db, "outbound", reply.delivery.id))
    queue.retry(db, db.get(ChannelJob, reply.delivery.id))
    assert queue.process_outbound(db, *queue.claim(db, "outbound", reply.delivery.id))
    assert len([item for item in posted if item.get("text") == f"Заявка {ticket.display_number} — {ticket.subject}\n\nГотово"]) == 1
    assert len(posted) == 2  # accepted text and accepted file, never a duplicate reply
    if channel == Channel.MAX:
        assert uploaded == ["MAX upload request"]  # reuse the uploaded token after attachment.not.ready
    # Re-polling the same provider event must not create a second local message.
    module.poll_updates(db, config)
    assert db.query(ChannelJob).filter_by(kind="inbound", channel=channel.value).count() == 1
