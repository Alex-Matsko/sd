"""XLSX rendering for the reports section (ТЗ р. 9: "экспорт XLSX/PDF").

XLSX only for now: an .xlsx is what a manager actually re-works before
sending it on, while a PDF of the same numbers is a dead end - and rendering
PDF server-side would drag in a browser or a LaTeX toolchain for no gain
over "open the xlsx and print to PDF". Noted in docs/decisions.md so the
half of the requirement that isn't met is visible rather than silently
dropped.
"""

from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_TITLE_FONT = Font(bold=True, size=13)


def _write_sheet(wb: Workbook, title: str, headers: list[str], rows: list[list], first: bool = False):
    sheet = wb.active if first else wb.create_sheet()
    sheet.title = title[:31]  # Excel hard-limits sheet names to 31 chars
    sheet.append(headers)
    for cell in sheet[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        sheet.append(row)
    for index, header in enumerate(headers, start=1):
        longest = max([len(str(header))] + [len(str(r[index - 1])) for r in rows]) if rows else len(str(header))
        sheet.column_dimensions[get_column_letter(index)].width = min(max(longest + 2, 12), 60)
    sheet.freeze_panes = "A2"
    return sheet


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value}%"


def overview_workbook(data: dict) -> bytes:
    """The Отчёты screen, one sheet per section, as shown on screen."""
    wb = Workbook()
    period = data["period"]

    sla = data["sla"]
    _write_sheet(
        wb,
        "SLA",
        ["Показатель", "Значение"],
        [
            ["Период", f"{period['date_from']} — {period['date_to']}"],
            ["Всего заявок", sla["total"]],
            ["Выполнено по реакции", _pct(sla["reaction_met_pct"])],
            ["Выполнено по решению", _pct(sla["resolution_met_pct"])],
        ],
        first=True,
    )
    _write_sheet(
        wb,
        "SLA по приоритетам",
        ["Приоритет", "Заявок", "Реакция", "Решение"],
        [[r["priority"], r["total"], _pct(r["reaction_met_pct"]), _pct(r["resolution_met_pct"])] for r in sla["by_priority"]],
    )
    _write_sheet(
        wb,
        "Нарушения SLA",
        ["Заявка", "Тема", "Организация", "Приоритет", "Реакция", "Решение"],
        [
            [
                v["display_number"],
                v["subject"],
                v["organization"],
                v["priority"],
                "нарушена" if v["reaction_met"] is False else "—",
                "нарушено" if v["resolution_met"] is False else "—",
            ]
            for v in sla["violations"]
        ],
    )

    flow = data["flow"]
    _write_sheet(wb, "Поток по каналам", ["Канал", "Заявок"], [[r["channel"], r["count"]] for r in flow["by_channel"]])
    _write_sheet(
        wb, "Поток по категориям", ["Категория", "Заявок"], [[r["category"], r["count"]] for r in flow["by_category"]]
    )
    _write_sheet(
        wb,
        "Поток по организациям",
        ["Организация", "Заявок"],
        [[r["organization"], r["count"]] for r in flow["by_organization"]],
    )
    _write_sheet(wb, "Динамика по дням", ["Дата", "Заявок"], [[r["date"], r["count"]] for r in flow["daily"]])

    _write_sheet(
        wb,
        "Загрузка инженеров",
        ["Инженер", "Оплачиваемые мин.", "Неоплачиваемые мин.", "Решено заявок", "Среднее решение, мин."],
        [
            [
                r["engineer_name"],
                r["billable_minutes"],
                r["non_billable_minutes"],
                r["resolved_count"],
                r["avg_resolution_minutes"] if r["avg_resolution_minutes"] is not None else "—",
            ]
            for r in data["workload"]
        ],
    )

    csat = data["csat"]
    _write_sheet(
        wb,
        "CSAT",
        ["Разрез", "Средняя оценка", "Оценок"],
        [["Всего", csat["average"] if csat["average"] is not None else "—", csat["count"]]]
        + [[f"Инженер: {r['label']}", r["average"], r["count"]] for r in csat["by_engineer"]]
        + [[f"Организация: {r['label']}", r["average"], r["count"]] for r in csat["by_organization"]],
    )
    _write_sheet(
        wb, "Возраст backlog", ["Возраст", "Открытых заявок"], [[r["bucket"], r["count"]] for r in data["backlog_aging"]]
    )

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def client_report_workbook(data: dict) -> bytes:
    """ТЗ 9.2: "Отчёт клиенту за период... форма пригодная для отправки
    клиенту". Deliberately narrow - what the client is entitled to see about
    their own service: which tickets, how much time, how the contracted hour
    package was consumed. No internal engineer names or workload figures."""
    wb = Workbook()
    period = data["period"]
    usage = data["package"]

    summary = _write_sheet(
        wb,
        "Сводка",
        ["Показатель", "Значение"],
        [
            ["Организация", data["organization"]],
            ["Период", f"{period['date_from']} — {period['date_to']}"],
            ["Заявок за период", data["totals"]["tickets"]],
            ["Решено за период", data["totals"]["resolved"]],
            ["Списано времени, ч", data["totals"]["hours"]],
            ["Пакет по договору, ч", usage["package_total_hours"]],
            ["Израсходовано пакета, ч", usage["package_used_hours"]],
            ["Остаток пакета, ч", usage["package_remaining_hours"]],
            ["Сверх пакета, ч", usage["overage_hours"]],
            ["Стоимость сверх пакета, ₽", usage["overage_cost"]],
        ],
        first=True,
    )
    summary["A1"].font = _TITLE_FONT

    _write_sheet(
        wb,
        "Заявки",
        ["Заявка", "Тема", "Канал", "Приоритет", "Статус", "Создана", "Решена", "Время, ч"],
        [
            [
                t["display_number"],
                t["subject"],
                t["channel"],
                t["priority"],
                t["status"],
                t["created_at"],
                t["resolved_at"] or "—",
                t["hours"],
            ]
            for t in data["tickets"]
        ],
    )

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def filename_for(prefix: str, date_from: date, date_to: date) -> str:
    return f"{prefix}_{date_from.isoformat()}_{date_to.isoformat()}.xlsx"
