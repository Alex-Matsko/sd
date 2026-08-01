import re
import uuid
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.config import settings
from app.models.message import Attachment

MAX_STORED_NAME_LENGTH = 120


class AttachmentTooLarge(ValueError):
    pass


def safe_filename(filename: str) -> str:
    """Reduces an untrusted filename to a single, harmless path component.
    Names arrive from places we don't control - an email MIME part, a Telegram
    document, a browser upload - so a name like `../../etc/cron.d/evil` must
    never influence where the bytes land (found in audit: it was interpolated
    into the storage path as-is). Strips any directory part (POSIX and Windows
    separators both, since email clients send either), drops leading dots so
    nothing becomes hidden or `..`, and bounds the length for filesystems with
    255-byte name limits - a long name plus the uuid prefix could exceed it."""
    name = PureWindowsPath(PurePosixPath(filename or "").name).name
    name = re.sub(r"[\x00-\x1f/\\]", "", name).lstrip(". ").strip()
    if len(name) > MAX_STORED_NAME_LENGTH:
        stem, dot, suffix = name.rpartition(".")
        suffix = f".{suffix[:20]}" if dot else ""
        name = (stem or name)[: MAX_STORED_NAME_LENGTH - len(suffix)] + suffix
    return name or "file"


def store_attachment(message_id: int, filename: str, content: bytes, mime_type: str | None) -> Attachment:
    """Writes `content` under attachments_dir/<year>/<month>/ (section 10:
    "структура по годам/месяцам") and returns an unsaved Attachment row - the
    caller adds/commits it as part of the enclosing message transaction.
    Shared by the manual upload endpoint and inbound email/messenger ingestion
    so every channel enforces the same size limit, name sanitizing and layout."""
    limit_bytes = settings.default_ticket_attachment_limit_mb * 1024 * 1024
    if len(content) > limit_bytes:
        raise AttachmentTooLarge(f"Файл превышает лимит {settings.default_ticket_attachment_limit_mb} МБ")

    safe_name = safe_filename(filename)
    today = date.today()
    directory = Path(settings.attachments_dir) / str(today.year) / f"{today.month:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    stored_path = directory / f"{uuid.uuid4().hex}_{safe_name}"
    stored_path.write_bytes(content)

    return Attachment(
        message_id=message_id,
        filename=safe_name,
        stored_path=str(stored_path),
        size_bytes=len(content),
        mime_type=mime_type,
    )
