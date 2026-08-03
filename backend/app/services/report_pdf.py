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

Вёрстка сделана как у документа, а не как у выгрузки: заголовок с периодом
по-русски, крупные показатели сверху, дальше SLA и расход пакета, разбивки
и в конце список заявок. Клиент читает первые две трети страницы, и всё
существенное должно быть там.
"""

from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
]
FONT_NAME = "ReportSans"
FONT_BOLD = "ReportSans-Bold"

_ACCENT = colors.HexColor("#1F3A5F")
_LINE = colors.HexColor("#D7DCE6")
_ZEBRA = colors.HexColor("#F5F7FA")
_MUTED = colors.HexColor("#62697B")
_GOOD = colors.HexColor("#157A4F")
_WARN = colors.HexColor("#A15C00")

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
    normal = base["Normal"]
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName=FONT_BOLD, fontSize=18,
                                alignment=0, spaceAfter=1, textColor=_ACCENT),
        "org": ParagraphStyle("o", parent=normal, fontName=FONT_BOLD, fontSize=12, textColor=colors.black),
        "sub": ParagraphStyle("s", parent=normal, fontName=FONT_NAME, fontSize=9.5, textColor=_MUTED),
        "h2": ParagraphStyle("h", parent=base["Heading2"], fontName=FONT_BOLD, fontSize=11.5,
                             spaceBefore=2, spaceAfter=5, textColor=_ACCENT),
        "kpi_value": ParagraphStyle("kv", parent=normal, fontName=FONT_BOLD, fontSize=19,
                                    alignment=TA_CENTER, leading=22, textColor=_ACCENT),
        "kpi_label": ParagraphStyle("kl", parent=normal, fontName=FONT_NAME, fontSize=7.5,
                                    alignment=TA_CENTER, leading=9.5, textColor=_MUTED),
        "cell": ParagraphStyle("c", parent=normal, fontName=FONT_NAME, fontSize=8.5, leading=11),
        "cell_bold": ParagraphStyle("cb", parent=normal, fontName=FONT_BOLD, fontSize=8.5, leading=11),
        "cell_right": ParagraphStyle("cr", parent=normal, fontName=FONT_NAME, fontSize=8.5,
                                     leading=11, alignment=TA_RIGHT),
        "head_cell": ParagraphStyle("hc", parent=normal, fontName=FONT_BOLD, fontSize=8.5,
                                    leading=11, textColor=colors.white),
        "foot": ParagraphStyle("f", parent=normal, fontName=FONT_NAME, fontSize=7.5, textColor=_MUTED),
    }


def _fmt(value) -> str:
    """Числа в отчёте клиенту — без хвоста .0: «12 ч», а не «12.0 ч»."""
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else f"{value:.1f}".replace(".", ",")
    return str(value)


def _kpi_band(items: list[tuple[str, str]], styles: dict, width: float) -> Table:
    """Крупные показатели в ряд — то, ради чего клиент открывает отчёт."""
    row_values = [Paragraph(value, styles["kpi_value"]) for value, _ in items]
    row_labels = [Paragraph(label, styles["kpi_label"]) for _, label in items]
    col = width / len(items)
    table = Table([row_values, row_labels], colWidths=[col] * len(items))
    table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 1), (-1, 1), 1),
            ("BACKGROUND", (0, 0), (-1, -1), _ZEBRA),
            ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
            # Тонкие разделители между показателями вместо рамок вокруг
            # каждого: полоса читается как один блок.
            ("LINEAFTER", (0, 0), (-2, -1), 0.4, colors.white),
        ])
    )
    return table


def _key_value_table(rows: list[tuple[str, str]], styles: dict, width: float) -> Table:
    table = Table(
        [[Paragraph(k, styles["cell"]), Paragraph(v, styles["cell_right"])] for k, v in rows],
        colWidths=[width * 0.62, width * 0.38],
    )
    table.setStyle(
        TableStyle([
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, _LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    return table


def _breakdown_table(rows: list[tuple[str, int]], styles: dict, width: float, total: int) -> Table:
    """Разбивка с долей в процентах: «12 заявок» без доли ничего не говорит."""
    body = []
    for name, count in rows:
        share = f"{round(count / total * 100)}%" if total else "—"
        body.append([
            Paragraph(name, styles["cell"]),
            Paragraph(str(count), styles["cell_right"]),
            Paragraph(share, styles["cell_right"]),
        ])
    table = Table(body or [[Paragraph("—", styles["cell"]), "", ""]],
                  colWidths=[width * 0.6, width * 0.2, width * 0.2])
    table.setStyle(
        TableStyle([
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, _LINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ])
    )
    return table


def _period_title(period: dict) -> str:
    """«Июль 2026» вместо «2026-07-01 — 2026-07-31»: в шапке документа,
    который читает клиент, ISO-даты выглядят выгрузкой из базы."""
    from app.services.client_reports import period_title

    try:
        start = date.fromisoformat(period["date_from"])
        end = date.fromisoformat(period["date_to"])
    except (KeyError, ValueError):
        return f"{period.get('date_from', '')} — {period.get('date_to', '')}"
    return period_title(start, end)


def client_report_pdf(data: dict) -> bytes:
    if not _ensure_fonts():
        raise FontUnavailable(
            "На сервере нет шрифта с кириллицей — установите fonts-dejavu-core (см. backend/Dockerfile)"
        )

    styles = _styles()
    usage = data["package"]
    sla = data.get("sla") or {}
    totals = data["totals"]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=17 * mm, rightMargin=17 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Отчёт по обслуживанию — {data['organization']} — {_period_title(data['period'])}",
        author="ООО «Открытые Горизонты»",
    )
    width = doc.width

    story = [
        Paragraph("Отчёт по обслуживанию", styles["title"]),
        Paragraph(_period_title(data["period"]), styles["sub"]),
        Spacer(1, 5 * mm),
        Paragraph(data["organization"], styles["org"]),
        Spacer(1, 6 * mm),
    ]

    # --- ключевые цифры ---
    kpis = [
        (_fmt(totals["tickets"]), "Обращений<br/>за период"),
        (_fmt(totals["resolved"]), "Решено"),
        (_fmt(totals["hours"]), "Часов<br/>работы"),
    ]
    if sla.get("resolution_met_pct") is not None:
        kpis.append((f"{_fmt(sla['resolution_met_pct'])}%", "Решено<br/>в срок"))
    if isinstance(usage["package_remaining_hours"], (int, float)):
        kpis.append((_fmt(usage["package_remaining_hours"]), "Остаток<br/>пакета, ч"))
    story.append(_kpi_band(kpis, styles, width))
    story.append(Spacer(1, 8 * mm))

    # --- SLA и пакет часов, две колонки ---
    sla_rows: list[tuple[str, str]] = []
    if sla.get("reaction_total"):
        sla_rows.append((
            "Реакция в срок",
            f"{_fmt(sla['reaction_met_pct'])}% из {sla['reaction_total']}",
        ))
    if sla.get("resolution_total"):
        sla_rows.append((
            "Решение в срок",
            f"{_fmt(sla['resolution_met_pct'])}% из {sla['resolution_total']}",
        ))
    if sla.get("reaction_missed") or sla.get("resolution_missed"):
        sla_rows.append(("Просрочено решений", str(sla.get("resolution_missed", 0))))
    if not sla_rows:
        sla_rows = [("Данных за период нет", "—")]

    package_rows = [
        ("Пакет по договору, ч", _fmt(usage["package_total_hours"])),
        ("Израсходовано, ч", _fmt(usage["package_used_hours"])),
        ("Остаток, ч", _fmt(usage["package_remaining_hours"])),
        ("Сверх пакета, ч", _fmt(usage["overage_hours"])),
        ("Стоимость сверх пакета, ₽", _fmt(usage["overage_cost"])),
    ]

    # Ширина колонки и промежутка считаются так, чтобы содержимое ячейки
    # ровно совпадало с шириной вложенной таблицы: если строить вложенную
    # таблицу шириной с колонку, отступ ячейки выталкивает её за край и
    # текст соседних колонок наезжает друг на друга.
    gutter = 8 * mm
    half = (width - gutter) / 2
    two_col_style = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), gutter),
        ("RIGHTPADDING", (1, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ])

    story.append(Table(
        [[
            [Paragraph("Соблюдение SLA", styles["h2"]), _key_value_table(sla_rows, styles, half)],
            [Paragraph("Пакет часов", styles["h2"]), _key_value_table(package_rows, styles, half)],
        ]],
        colWidths=[half + gutter, half], style=two_col_style,
    ))
    story.append(Spacer(1, 7 * mm))

    # --- разбивки, тоже две колонки ---
    by_channel = [(row["channel"], row["count"]) for row in data.get("by_channel", [])]
    by_category = [(row["category"], row["count"]) for row in data.get("by_category", [])]
    if by_channel or by_category:
        story.append(Table(
            [[
                [Paragraph("Откуда обращались", styles["h2"]),
                 _breakdown_table(by_channel, styles, half, totals["tickets"])],
                [Paragraph("О чём обращались", styles["h2"]),
                 _breakdown_table(by_category, styles, half, totals["tickets"])],
            ]],
            colWidths=[half + gutter, half], style=two_col_style,
        ))
        story.append(Spacer(1, 7 * mm))

    # --- список заявок ---
    story.append(Paragraph("Обращения за период", styles["h2"]))
    headers = ["Заявка", "Тема", "Канал", "Статус", "Создана", "Часы"]
    rows = [[Paragraph(h, styles["head_cell"]) for h in headers]]
    for t in data["tickets"]:
        rows.append([
            Paragraph(t["display_number"], styles["cell"]),
            Paragraph(t["subject"], styles["cell"]),
            Paragraph(t["channel"], styles["cell"]),
            Paragraph(t["status"], styles["cell"]),
            Paragraph(t["created_at"], styles["cell"]),
            Paragraph(_fmt(t["hours"]), styles["cell_right"]),
        ])

    if len(rows) == 1:
        story.append(Paragraph("За период обращений не зарегистрировано.", styles["cell"]))
    else:
        table = Table(
            rows,
            colWidths=[width * 0.11, width * 0.38, width * 0.11, width * 0.14, width * 0.17, width * 0.09],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, _LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ])
        )
        story.append(table)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        f"ООО «Открытые Горизонты» · служба поддержки · отчёт сформирован "
        f"{datetime.now().strftime('%d.%m.%Y')}",
        styles["foot"],
    ))

    doc.build(story)
    return buffer.getvalue()
