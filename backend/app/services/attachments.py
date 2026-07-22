import uuid
from datetime import date
from pathlib import Path

from app.config import settings
from app.models.message import Attachment


class AttachmentTooLarge(ValueError):
    pass


def store_attachment(message_id: int, filename: str, content: bytes, mime_type: str | None) -> Attachment:
    """Writes `content` under attachments_dir/<year>/<month>/ (section 10:
    "структура по годам/месяцам") and returns an unsaved Attachment row - the
    caller adds/commits it as part of the enclosing message transaction.
    Shared by the manual upload endpoint and inbound email ingestion so both
    channels enforce the same size limit and storage layout."""
    limit_bytes = settings.default_ticket_attachment_limit_mb * 1024 * 1024
    if len(content) > limit_bytes:
        raise AttachmentTooLarge(f"Файл превышает лимит {settings.default_ticket_attachment_limit_mb} МБ")

    today = date.today()
    directory = Path(settings.attachments_dir) / str(today.year) / f"{today.month:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{filename}"
    stored_path = directory / stored_name
    stored_path.write_bytes(content)

    return Attachment(
        message_id=message_id,
        filename=filename or stored_name,
        stored_path=str(stored_path),
        size_bytes=len(content),
        mime_type=mime_type,
    )
