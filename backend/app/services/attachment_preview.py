"""Bounded, local previews. Documents never leave the service desk host."""
import csv
from datetime import date, datetime, time
from io import StringIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

ROW_LIMIT = 200
COLUMN_LIMIT = 40
TEXT_LIMIT = 100_000


class PreviewError(ValueError):
    def __init__(self, message, status_code=422):
        super().__init__(message)
        self.status_code = status_code


def _check_archive(path):
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 5000 or sum(entry.file_size for entry in entries) > 32 * 1024 * 1024:
            raise PreviewError("Документ слишком большой для предпросмотра. Скачайте оригинал.")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value)[:2000]


def _table(rows, **metadata):
    rows = [[_cell(value) for value in row[:COLUMN_LIMIT]] for row in rows]
    while rows and not any(rows[-1]):
        rows.pop()
    width = max((max((i + 1 for i, value in enumerate(row) if value), default=0) for row in rows), default=0)
    return {"kind": "spreadsheet", "columns": [get_column_letter(i + 1) for i in range(width)],
            "rows": [row[:width] + [""] * max(0, width - len(row)) for row in rows],
            "row_limit": ROW_LIMIT, "column_limit": COLUMN_LIMIT, **metadata}


def preview_attachment(attachment, sheet=0):
    path = Path(attachment.stored_path)
    if not path.is_file():
        raise PreviewError("Файл вложения недоступен на диске", 410)
    extension = Path(attachment.filename).suffix.lower()
    try:
        if extension in (".xlsx", ".xlsm"):
            _check_archive(path)
            workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
            try:
                if not 0 <= sheet < min(len(workbook.worksheets), 100):
                    raise PreviewError("Лист не найден", 404)
                worksheet = workbook.worksheets[sheet]
                rows = list(worksheet.iter_rows(min_row=1, max_row=ROW_LIMIT, max_col=COLUMN_LIMIT, values_only=True))
                return _table(rows, sheets=workbook.sheetnames[:100], sheet=sheet,
                              truncated=(worksheet.max_row or 0) > ROW_LIMIT or (worksheet.max_column or 0) > COLUMN_LIMIT)
            finally:
                workbook.close()
        if extension == ".docx":
            _check_archive(path)
            with ZipFile(path) as archive:
                root = ET.fromstring(archive.read("word/document.xml"))
            namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = ["".join(t.text or "" for t in paragraph.findall(".//w:t", namespace))
                          for paragraph in root.findall(".//w:p", namespace)]
            text = "\n".join(paragraphs)
            return {"kind": "text", "text": text[:TEXT_LIMIT], "truncated": len(text) > TEXT_LIMIT}
        if extension in (".txt", ".log", ".csv", ".json", ".xml", ".md"):
            with path.open("rb") as source:
                content = source.read(1024 * 1024 + 1)
            truncated = len(content) > 1024 * 1024
            content = content[:1024 * 1024]
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("cp1251", errors="replace")
            if extension == ".csv":
                try:
                    dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.reader(StringIO(text), dialect)
                rows = []
                for index, row in enumerate(reader):
                    if index == ROW_LIMIT:
                        truncated = True
                        break
                    truncated = truncated or len(row) > COLUMN_LIMIT
                    rows.append(row[:COLUMN_LIMIT])
                return _table(rows, sheets=[], sheet=0, truncated=truncated)
            return {"kind": "text", "text": text[:TEXT_LIMIT], "truncated": truncated or len(text) > TEXT_LIMIT}
    except PreviewError:
        raise
    except (BadZipFile, InvalidFileException, KeyError, ValueError, OSError, ET.ParseError, csv.Error) as exc:
        raise PreviewError("Не удалось прочитать документ. Возможно, он повреждён или защищён паролем. Скачайте оригинал.") from exc
    raise PreviewError("Предпросмотр этого формата пока недоступен. Вы можете скачать оригинал.", 415)
