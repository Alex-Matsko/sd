import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  downloadStoredClientReport,
  generateClientReport,
  getStoredClientReport,
  listClientReports,
  listOrganizations,
  setClientReportSent,
  type ClientReportData,
  type ClientReportSummary,
} from "../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../components/ui";
import { formatDateTime } from "../lib/labels";

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Последние 12 месяцев, начиная с прошлого: отчёт за текущий месяц
 *  формируют редко — он ещё не закончился. */
function recentMonths(count = 12) {
  const now = new Date();
  return Array.from({ length: count }, (_, i) => {
    const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1 - i, 1));
    const year = date.getUTCFullYear();
    const month = date.getUTCMonth();
    return {
      key: `${year}-${String(month + 1).padStart(2, "0")}`,
      label: `${MONTHS[month]} ${year}`,
      start: iso(new Date(Date.UTC(year, month, 1))),
      end: iso(new Date(Date.UTC(year, month + 1, 0))),
    };
  });
}

export function ClientReportsPage() {
  const qc = useQueryClient();
  const months = useMemo(() => recentMonths(), []);
  const [organizationId, setOrganizationId] = useState<number | "">("");
  const [monthKey, setMonthKey] = useState(months[0].key);
  const [customRange, setCustomRange] = useState(false);
  const [customFrom, setCustomFrom] = useState(months[0].start);
  const [customTo, setCustomTo] = useState(months[0].end);
  const [openReportId, setOpenReportId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const listQuery = useQuery({
    queryKey: ["client-reports", organizationId],
    queryFn: () => listClientReports({ organization_id: organizationId || undefined, limit: 50 }),
  });

  const selectedMonth = months.find((m) => m.key === monthKey) ?? months[0];
  const periodStart = customRange ? customFrom : selectedMonth.start;
  const periodEnd = customRange ? customTo : selectedMonth.end;

  const generateMutation = useMutation({
    mutationFn: () =>
      generateClientReport({
        organization_id: Number(organizationId),
        period_start: periodStart,
        period_end: periodEnd,
      }),
    onSuccess: (report) => {
      setError(null);
      setOpenReportId(report.id);
      qc.invalidateQueries({ queryKey: ["client-reports"] });
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось сформировать отчёт"),
  });

  const canGenerate = organizationId !== "" && periodStart <= periodEnd;

  return (
    <div className="view" style={{ maxWidth: 1180 }}>
      <h1 className="view-title">Отчёты клиентам</h1>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Отчёт за период с обращениями, соблюдением SLA и расходом пакета часов — в том виде, в каком его получит
        клиент. Первого числа отчёты за прошлый месяц формируются сами и появляются в списке ниже;
        клиенту ничего не уходит без вашего действия.
      </p>

      <div className="panel">
        <div className="panel-head">
          <h2>Сформировать отчёт</h2>
        </div>
        {error && <ErrorBanner message={error} />}
        <div className="form-row-inline" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="form-row" style={{ minWidth: 260, marginBottom: 0 }}>
            <label className="form-label">Клиент</label>
            <select
              value={organizationId}
              onChange={(e) => setOrganizationId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Выберите организацию</option>
              {(orgsQuery.data ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </div>

          {!customRange ? (
            <div className="form-row" style={{ minWidth: 200, marginBottom: 0 }}>
              <label className="form-label">Период</label>
              <select value={monthKey} onChange={(e) => setMonthKey(e.target.value)}>
                {months.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <>
              <div className="form-row" style={{ marginBottom: 0 }}>
                <label className="form-label">С</label>
                <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} />
              </div>
              <div className="form-row" style={{ marginBottom: 0 }}>
                <label className="form-label">По</label>
                <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} />
              </div>
            </>
          )}

          <button
            className="btn-link"
            onClick={() => {
              // При переходе к произвольному периоду поля заполняются
              // выбранным месяцем — так его удобно просто подправить.
              if (!customRange) {
                setCustomFrom(selectedMonth.start);
                setCustomTo(selectedMonth.end);
              }
              setCustomRange(!customRange);
            }}
          >
            {customRange ? "выбрать месяц" : "произвольный период"}
          </button>

          <div className="spacer" />
          <button className="btn btn-primary" disabled={!canGenerate || generateMutation.isPending} onClick={() => generateMutation.mutate()}>
            Сформировать
          </button>
        </div>
        {periodStart > periodEnd && <p className="muted">Конец периода раньше начала.</p>}
      </div>

      {openReportId !== null && (
        <ReportPreview reportId={openReportId} onClose={() => setOpenReportId(null)} />
      )}

      <div className="panel">
        <div className="panel-head">
          <h2>Сформированные отчёты</h2>
          <span className="muted">
            Отметка об отправке ставится вручную — рассылки нет
            {listQuery.data ? ` · всего ${listQuery.data.total}` : ""}
          </span>
        </div>
        {listQuery.isLoading && <Loading />}
        {listQuery.isError && <ErrorBanner message={(listQuery.error as Error).message} />}
        {listQuery.data && listQuery.data.items.length === 0 && (
          <EmptyState text="Отчётов пока нет — сформируйте первый или дождитесь автоматического первого числа" />
        )}
        {listQuery.data && listQuery.data.items.length > 0 && (
          <ReportList
            reports={listQuery.data.items}
            onOpen={setOpenReportId}
            onChanged={() => qc.invalidateQueries({ queryKey: ["client-reports"] })}
          />
        )}
      </div>
    </div>
  );
}

// Последняя колонка широкая: в ней четыре текстовых действия, и самое
// длинное — «Отметить отправленным».
const LIST_COLUMNS = "1.3fr 1fr 90px 80px 1fr 330px";

function ReportList({
  reports,
  onOpen,
  onChanged,
}: {
  reports: ClientReportSummary[];
  onOpen: (id: number) => void;
  onChanged: () => void;
}) {
  const sentMutation = useMutation({
    mutationFn: ({ id, sent }: { id: number; sent: boolean }) => setClientReportSent(id, sent),
    onSuccess: onChanged,
  });

  return (
    <div className="list">
      <div className="list-head" style={{ gridTemplateColumns: LIST_COLUMNS }}>
        <span>Клиент</span>
        <span>Период</span>
        <span>Обращений</span>
        <span>Часов</span>
        <span>Сформирован</span>
        <span></span>
      </div>
      {reports.map((r) => (
        <div className="list-row" style={{ gridTemplateColumns: LIST_COLUMNS }} key={r.id}>
          <span className="subject">{r.organization_name}</span>
          <span>{r.period_title}</span>
          <span className="mono">{r.tickets_count}</span>
          <span className="mono">{r.hours}</span>
          <span className="muted">
            {formatDateTime(r.generated_at)}
            {r.source === "auto" ? " · автоматически" : ""}
            {r.sent_at && <span className="sent-mark"> · отмечен отправленным</span>}
          </span>
          <span style={{ display: "flex", gap: 10 }}>
            <button className="btn-link" onClick={() => onOpen(r.id)}>
              Открыть
            </button>
            <button className="btn-link" onClick={() => downloadStoredClientReport(r, "pdf")}>
              PDF
            </button>
            <button className="btn-link" onClick={() => downloadStoredClientReport(r, "xlsx")}>
              XLSX
            </button>
            {/* Отметка ничего не отправляет — она только напоминает, кому
                отчёт уже ушёл. Поэтому «Отметить отправленным», а не
                «Отправить», и поэтому её можно снять. */}
            <button className="btn-link" onClick={() => sentMutation.mutate({ id: r.id, sent: !r.sent_at })}>
              {r.sent_at ? "Снять отметку" : "Отметить отправленным"}
            </button>
          </span>
        </div>
      ))}
    </div>
  );
}

function ReportPreview({ reportId, onClose }: { reportId: number; onClose: () => void }) {
  const query = useQuery({ queryKey: ["client-report", reportId], queryFn: () => getStoredClientReport(reportId) });

  if (query.isLoading) return <div className="panel"><Loading /></div>;
  if (query.isError) return <div className="panel"><ErrorBanner message={(query.error as Error).message} /></div>;

  const report = query.data!;
  const data: ClientReportData = report.data;
  const pkg = data.package;

  return (
    <div className="panel report-preview">
      <div className="panel-head">
        <h2>
          {data.organization} — {report.period_title}
        </h2>
        <div className="spacer" />
        <button className="btn btn-ghost" onClick={() => downloadStoredClientReport(report, "xlsx")}>
          XLSX
        </button>
        <button className="btn btn-primary" onClick={() => downloadStoredClientReport(report, "pdf")}>
          Скачать PDF
        </button>
        <button className="icon-btn" onClick={onClose} title="Свернуть">
          ×
        </button>
      </div>
      <p className="muted">
        Снимок на {formatDateTime(report.generated_at)}
        {report.generated_by ? `, ${report.generated_by}` : ", автоматически"}. Цифры зафиксированы: списания,
        внесённые позже, попадут в отчёт только после повторного формирования.
      </p>

      <div className="kpi-row">
        <div className="kpi">
          <span className="v">{data.totals.tickets}</span>
          <span className="l">Обращений</span>
        </div>
        <div className="kpi">
          <span className="v">{data.totals.resolved}</span>
          <span className="l">Решено</span>
        </div>
        <div className="kpi">
          <span className="v">{data.totals.hours}</span>
          <span className="l">Часов работы</span>
        </div>
        <div className="kpi">
          <span className="v">{data.sla?.resolution_met_pct ?? "—"}%</span>
          <span className="l">Решено в срок</span>
        </div>
        <div className="kpi">
          <span className="v">{pkg.package_remaining_hours}</span>
          <span className="l">Остаток пакета, ч</span>
        </div>
      </div>

      <div className="report-columns">
        <div>
          <h3 className="form-section">Соблюдение SLA</h3>
          <dl className="kv">
            <dt>Реакция в срок</dt>
            <dd>
              {data.sla?.reaction_met_pct ?? "—"}% из {data.sla?.reaction_total ?? 0}
            </dd>
            <dt>Решение в срок</dt>
            <dd>
              {data.sla?.resolution_met_pct ?? "—"}% из {data.sla?.resolution_total ?? 0}
            </dd>
            <dt>Просрочено решений</dt>
            <dd>{data.sla?.resolution_missed ?? 0}</dd>
          </dl>
        </div>
        <div>
          <h3 className="form-section">Пакет часов</h3>
          <dl className="kv">
            <dt>Пакет по договору, ч</dt>
            <dd>{pkg.package_total_hours}</dd>
            <dt>Израсходовано, ч</dt>
            <dd>{pkg.package_used_hours}</dd>
            <dt>Сверх пакета, ч</dt>
            <dd>{pkg.overage_hours}</dd>
            <dt>Стоимость сверх пакета, ₽</dt>
            <dd>{pkg.overage_cost}</dd>
          </dl>
        </div>
        <div>
          <h3 className="form-section">Откуда обращались</h3>
          <dl className="kv">
            {data.by_channel.map((row) => (
              <ShareRow key={row.channel} name={row.channel} count={row.count} total={data.totals.tickets} />
            ))}
          </dl>
        </div>
        <div>
          <h3 className="form-section">О чём обращались</h3>
          <dl className="kv">
            {data.by_category.map((row) => (
              <ShareRow key={row.category} name={row.category} count={row.count} total={data.totals.tickets} />
            ))}
          </dl>
        </div>
      </div>

      <h3 className="form-section">Обращения за период</h3>
      {data.tickets.length === 0 ? (
        <p className="muted">За период обращений не зарегистрировано.</p>
      ) : (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "90px 2.4fr 90px 110px 140px 70px" }}>
            <span>Заявка</span>
            <span>Тема</span>
            <span>Канал</span>
            <span>Статус</span>
            <span>Создана</span>
            <span>Часы</span>
          </div>
          {data.tickets.map((t) => (
            <div className="list-row" style={{ gridTemplateColumns: "90px 2.4fr 90px 110px 140px 70px" }} key={t.display_number}>
              <span className="mono">{t.display_number}</span>
              <span className="subject">{t.subject}</span>
              <span className="muted">{t.channel}</span>
              <span className="muted">{t.status}</span>
              <span className="muted">{t.created_at}</span>
              <span className="mono">{t.hours}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ShareRow({ name, count, total }: { name: string; count: number; total: number }) {
  return (
    <>
      <dt>{name}</dt>
      <dd>
        {count}
        <span className="muted"> · {total ? Math.round((count / total) * 100) : 0}%</span>
      </dd>
    </>
  );
}
