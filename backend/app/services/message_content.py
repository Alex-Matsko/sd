"""Safe, ordered text/image messages. No client-supplied HTML or remote image URLs."""
from html import escape


class MessageContentError(ValueError):
    pass


def image_mime(content: bytes) -> str | None:
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if content.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if content.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'image/webp'
    return None


def prepare(payload, uploads):
    if payload.content_blocks is None:
        return payload
    for block in payload.content_blocks:
        if block.type == 'image':
            if block.file_index >= len(uploads):
                raise MessageContentError('Скриншот не найден среди вложений сообщения')
            if not image_mime(uploads[block.file_index][1]):
                raise MessageContentError('В сообщение можно вставить изображения PNG, JPEG, GIF или WebP')
    text = '\n'.join(block.text for block in payload.content_blocks if block.type == 'text')
    if len(text) > 300000:
        raise MessageContentError("Текст сообщения превышает 300 000 символов")
    if not text.strip() and not uploads:
        raise MessageContentError('Введите сообщение или приложите файл')
    return payload.model_copy(update={'body': text})


def delivery_parts(message, attachments):
    """One stable sequence, shared by retries; remaining files go at the end."""
    by_id = {a.id: a for a in attachments}
    used = set()
    parts = []
    for block in message.content_blocks or []:
        if block['type'] == 'text':
            text = block['text']
            parts.extend(('text', text[i:i + 3000]) for i in range(0, len(text), 3000) if text[i:i + 3000].strip())
        else:
            attachment = by_id.get(block['attachment_id'])
            if attachment is None:
                raise MessageContentError('Состав скриншотов сообщения изменён')
            parts.append(('file', attachment))
            used.add(attachment.id)
    parts.extend(('file', a) for a in attachments if a.id not in used)
    return parts


def email_html(blocks, cid_by_id):
    parts = []
    for block in blocks:
        if block['type'] == 'text':
            parts.append('<div style="white-space:pre-wrap">' + escape(block['text']) + '</div>')
        else:
            cid = cid_by_id[block['attachment_id']]
            parts.append(f'<p><img src="cid:{cid}" alt="Скриншот" style="max-width:100%;height:auto"></p>')
    return '<!doctype html><html><body>' + ''.join(parts) + '</body></html>'
