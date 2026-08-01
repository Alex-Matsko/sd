"""PDF rendering for the client report (ТЗ р. 9: "экспорт XLSX/PDF").

Generated directly with reportlab rather than by printing HTML: HTML-to-PDF
would mean shipping a headless browser in the image, which is a large
dependency and a moving target. reportlab draws the document itself - one
Python package plus a Cyrillic-capable TTF (fonts-dejavu-core, installed in
the Dockerfile; reportlab's built-in Type1 faces have no Cyrillic and would
render Russian text as black boxes).

Only the client report is rendered as PDF. That's the document that gets
sent to someone outside the company, where a fixed layout matters; the
internal overview is for reworking, and stays XLSX-only.
"""

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
]
FONT_NAME = "ReportSans"
FONT_BOLD = "ReportSans-Bold"
_ACCENT = colors.HexColor("#1F3A5F")

_fonts_ready = False


def _ensure_fonts() -> bool:
    """Registers a Cyrillic TTF once per process. Returns False when none is
    available, so the caller can fail with a clear message instead of
    producing a PDF full of black boxes."""
    global _fonts_ready
    if _fonts_ready:
        return True
    for regular, bold in _FONT_CANDIDATES:
        if Path(regular).exists():
            pdfmetrics.registerFont(TTFont(FONT_NAME, regular))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, bold if Path(bold).exists() else regular))
            _fonts_ready = True
            return True
    return False


class FontUnavailable(RuntimeError):
    pass


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName=FONT_BOLD, fontSize=16, spaceAfter=2, textColor=_ACCENT),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontName=FONT_NAME, fontSize=10, textColor=colors.grey),
        "h2": ParagraphStyle("h", parent=base["Heading2"], fontName=FONT_BOLD, fontSize=12, spaceBefore=14, spaceAfter=6),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontName=FONT_NAME, fontSize=8.5, leading=11),
        "cell_right": ParagraphStyle("cr", parent=base["Normal"], fontName=FONT_NAME, fontSize=8.5, leading=11, alignment=TA_RIGHT),
        "foot": ParagraphStyle("f", parent=base["Normal"], fontName=FONT_NAME, fontSize=8, textColor=colors.grey),
    }


def client_report_pdf(data: dict) -> bytes:
    if not _ensure_fonts():
        raise FontUnavailable(
            "На сервере нет шрифта с кириллицей — установите fonts-dejavu-core (см. backend/Dockerfile)"
        )

    styles = _styles()
    period = data["period"]
    usage = data["package"]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Отчёт по обслуживанию — {data['organization']}",
    )

    story = [
        Paragraph("Отчёт по обслуживанию", styles["title"]),
        Paragraph(f"{data['organization']} · период {period['date_from']} — {period['date_to']}", styles["sub"]),
        Spacer(1, 10 * mm),
        Paragraph("Сводка", styles["h2"]),
    ]

    summary_rows = [
        ["Заявок за период", data["totals"]["tickets"]],
        ["Решено за период", data["totals"]["resolved"]],
        ["Списано времени, ч", data["totals"]["hours"]],
        ["Пакет по договору, ч", usage["package_total_hours"]],
        ["Израсходовано пакета, ч", usage["package_used_hours"]],
        ["Остаток пакета, ч", usage["package_remaining_hours"]],
        ["Сверх пакета, ч", usage["overage_hours"]],
        ["Стоимость сверх пакета, ₽", usage["overage_cost"]],
    ]
    summary = Table(
        [[Paragraph(str(k), styles["cell"]), Paragraph(str(v), styles["cell_right"])] for k, v in summary_rows],
        colWidths=[110 * mm, 64 * mm],
    )
    summary.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7DCE6")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(summary)

    story.append(Paragraph("Заявки за период", styles["h2"]))
    headers = ["Заявка", "Тема", "Канал", "Статус", "Создана", "Часы"]
    rows = [[Paragraph(f"<b>{h}</b>", styles["cell"]) for h in headers]]
    for t in data["tickets"]:
        rows.append([
            Paragraph(t["display_number"], styles["cell"]),
            Paragraph(t["subject"], styles["cell"]),
            Paragraph(t["channel"], styles["cell"]),
            Paragraph(t["status"], styles["cell"]),
            Paragraph(t["created_at"], styles["cell"]),
            Paragraph(str(t["hours"]), styles["cell_right"]),
        ])

    if len(rows) == 1:
        story.append(Paragraph("За период заявок не зарегистрировано.", styles["cell"]))
    else:
        table = Table(rows, colWidths=[20 * mm, 66 * mm, 18 * mm, 24 * mm, 30 * mm, 16 * mm], repeatRows=1)
        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7DCE6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ])
        )
        story.append(table)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("ООО «Открытые Горизонты» · отчёт сформирован автоматически", styles["foot"]))

    doc.build(story)
    return buffer.getvalue()
