from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest
from openpyxl import Workbook

from app.api.deps import get_current_user
from app.api.routers.portal import get_current_contact
from app.core.enums import Channel, MessageDirection, Priority, TicketType, UserRole
from app.db import get_db
from app.main import app
from app.models.user import User
from app.models.contact import Contact
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import attachment_preview, messages, tickets


def workbook_bytes():
    workbook = Workbook()
    workbook.active.title = 'Расчёт'
    workbook.active.append(['Услуга', 'Часы', 'Комментарий'])
    workbook.active.append(['Настройка', 2.5, '<script>alert(1)</script>'])
    workbook.create_sheet('План').append(['Второй лист'])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def file_at(tmp_path, filename, content):
    path = tmp_path / filename
    path.write_bytes(content)
    return SimpleNamespace(stored_path=str(path), filename=filename)


def test_workbook_preview_switches_sheets_without_executing_content(tmp_path):
    attachment = file_at(tmp_path, 'План.xlsx', workbook_bytes())
    preview = attachment_preview.preview_attachment(attachment)
    assert preview['sheets'] == ['Расчёт', 'План']
    assert preview['columns'] == ['A', 'B', 'C']
    assert preview['rows'][1] == ['Настройка', '2.5', '<script>alert(1)</script>']
    assert preview['truncated'] is False
    assert attachment_preview.preview_attachment(attachment, 1)['rows'] == [['Второй лист']]
    with pytest.raises(attachment_preview.PreviewError) as error:
        attachment_preview.preview_attachment(attachment, 2)
    assert error.value.status_code == 404


def test_preview_is_bounded_and_original_bytes_are_preserved(tmp_path):
    workbook = Workbook()
    workbook.active.cell(300, 70, 'Outside preview')
    workbook.active.cell(1, 1, 'Visible')
    output = BytesIO(); workbook.save(output); workbook.close()
    content = output.getvalue()
    attachment = file_at(tmp_path, 'large.xlsx', content)
    preview = attachment_preview.preview_attachment(attachment)
    assert preview['rows'] == [['Visible']]
    assert preview['truncated'] is True
    assert (tmp_path / 'large.xlsx').read_bytes() == content


def test_csv_and_docx_previews_are_plain_text(tmp_path):
    csv = file_at(tmp_path, 'report.csv', 'Услуга;Часы\nНастройка;3'.encode('cp1251'))
    assert attachment_preview.preview_attachment(csv)['rows'] == [['Услуга', 'Часы'], ['Настройка', '3']]
    archive = BytesIO()
    with ZipFile(archive, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&lt;script&gt;Привет&lt;/script&gt;</w:t></w:r></w:p></w:body></w:document>')
    docx = file_at(tmp_path, 'report.docx', archive.getvalue())
    assert attachment_preview.preview_attachment(docx)['text'] == '<script>Привет</script>'


def test_corrupt_oversized_and_unsupported_documents_fail_cleanly(tmp_path):
    for name in ('broken.xlsx', 'broken.docx'):
        with pytest.raises(attachment_preview.PreviewError):
            attachment_preview.preview_attachment(file_at(tmp_path, name, b'bad zip'))
    with pytest.raises(attachment_preview.PreviewError) as unsupported:
        attachment_preview.preview_attachment(file_at(tmp_path, 'file.exe', b'content'))
    assert unsupported.value.status_code == 415
    archive = BytesIO()
    from zipfile import ZIP_DEFLATED
    with ZipFile(archive, 'w', compression=ZIP_DEFLATED) as z:
        z.writestr('oversized', b'0' * (32 * 1024 * 1024 + 1))
    with pytest.raises(attachment_preview.PreviewError, match='слишком большой'):
        attachment_preview.preview_attachment(file_at(tmp_path, 'oversized.xlsx', archive.getvalue()))


def test_preview_uses_the_same_ticket_and_internal_note_permissions_as_download(db, contact, engineer_user, tmp_path, monkeypatch):
    monkeypatch.setattr('app.config.settings.attachments_dir', str(tmp_path))
    actor = db.query(User).filter(User.role == UserRole.ADMIN).first()
    ticket = tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PORTAL,
        subject='Превью вложений', manual_priority=Priority.P3, manual_priority_reason='test'), actor=None)
    note = messages.add_message(db, ticket, MessageCreate(direction=MessageDirection.INTERNAL_NOTE, body='Внутренний'),
                                author_user=actor, attachments=[('План.xlsx', workbook_bytes(), None)])
    public = messages.add_message(db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body='Файл клиента'),
                                  author_contact=contact, attachments=[('Таблица.xlsx', workbook_bytes(), None)])
    note_id, public_id = note.attachments[0].id, public.attachments[0].id
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_current_contact] = lambda: contact
    try:
        with TestClient(app) as client:
            staff_path = f'/tickets/{ticket.id}/attachments/{note_id}/preview'
            assert client.get(staff_path).json()['sheets'] == ['Расчёт', 'План']
            assert client.get(f'/tickets/{ticket.id + 100000}/attachments/{note_id}/preview').status_code == 404
            assert client.get(f'/portal/tickets/{ticket.id}/attachments/{note_id}/preview').status_code == 404
            assert client.get(f'/portal/tickets/{ticket.id}/attachments/{public_id}/preview?sheet=1').json()['rows'] == [['Второй лист']]
            assert client.get(f'/portal/tickets/{ticket.id}/attachments/{public_id}/preview?sheet=-1').status_code == 422
            ticket.assigned_engineer_id = actor.id; db.commit()
            app.dependency_overrides[get_current_user] = lambda: engineer_user
            assert client.get(staff_path).status_code == 404
            other_contact = Contact(organization_id=contact.organization_id, full_name="Другой клиент", can_view_org_tickets=False)
            db.add(other_contact); db.commit()
            app.dependency_overrides[get_current_contact] = lambda: other_contact
            # Portal access is checked before reading any document bytes.
            assert client.get(f'/portal/tickets/{ticket.id}/attachments/{public_id}/preview').status_code == 404
    finally:
        app.dependency_overrides = previous
