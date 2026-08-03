import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  downloadOverviewXlsx,
  getReportsOverview,
  listOrganizations,
} from "../api/endpoints";
import { ErrorBanner, Loading, PriorityTag } from "../components/ui";
import { PRIORITY_LABELS, formatMinutes } from "../lib/labels";
import { CHANNEL_LABELS } from "../lib/labels";
import type { Channel } from "../api/types";

function firstOfMonth(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function BarChart({ items, max }: { items: { label: string; value: number }[]; max?: number }) {
  const peak = max ?? Math.max(1, ...items.map((i) => i.value));
  if (items.length === 0) return <p className="muted" style={{ fontSize: 12.5 }}>Нет данных за период</p>;
  return (
    <div className="bar-chart">
      {items.map((item) => (
        <div className="bar-col" key={item.label}>
          <span className="bar-value">{item.value}</span>
          <div className="bar" style={{ height: `${Math.max((item.value / peak) * 100, 2)}%` }} />
          <span className="bar-label" title={item.label}>
            {item.label}
          </span>
        </div>
      ))}
    </div>
  );
}

function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const max = Math.max(1, ...points);
  const step = 200 / (points.length - 1);
  const coords = points.map((v, i) => `${i * step},${36 - (v / max) * 32}`).join(" ");
  return (
    <svg width="100%" height="36" viewBox="0 0 200 36" preserveAspectRatio="none" className="sparkline">
      <polyline points={coords} fill="none" stroke="var(--success)" strokeWidth={2} />
    </svg>
  );
}

export function ReportsPage() {
  const [dateFrom, setDateFrom] = useState(firstOfMonth());
  const [dateTo, setDateTo] = useState(today());
  const [organizationId, setOrganizationId] = useState<number | "">("");

  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const reportQuery = useQuery({
    queryKey: ["reports-overview", dateFrom, dateTo, organizationId],
    queryFn: () => getReportsOverview({ date_from: dateFrom, date_to: dateTo, organization_id: organizationId || undefined }),
  });

  return (
    <div className="view" style={{ maxWidth: 1180 }}>
      <h1 className="view-title">Сводный отчёт</h1>
      <div className="filter-bar">
        <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        <select value={organizationId} onChange={(e) => setOrganizationId(e.target.value ? Number(e.target.value) : "")}>
          <option value="">Все организации</option>
          {(orgsQuery.data ?? []).map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <div className="spacer" />
        <button className="btn btn-ghost" onClick={() => downloadOverviewXlsx(dateFrom, dateTo, organizationId || undefined)}>
          Выгрузить в XLSX
        </button>
      </div>

      {reportQuery.isLoading && <Loading />}
      {reportQuery.isError && <ErrorBanner message={(reportQuery.error as Error).message} />}
      {reportQuery.data && (
        <>
          <div className="panel">
            <div className="kpi-row">
              <div className="kpi">
                <span className="v">{reportQuery.data.flow.total}</span>
                <span className="l">Заявок за период</span>
              </div>
              <div className="kpi">
                <span className="v">{reportQuery.data.sla.reaction_met_pct ?? "—"}%</span>
                <span className="l">Реакция в срок</span>
              </div>
              <div className="kpi">
                <span className="v">{reportQuery.data.sla.resolution_met_pct ?? "—"}%</span>
                <span className="l">Решение в срок</span>
              </div>
              <div className="kpi">
                <span className="v">{reportQuery.data.sla.violations.length}</span>
                <span className="l">Нарушений SLA</span>
              </div>
              <div className="kpi">
                <span className="v">{reportQuery.data.csat.average ?? "—"}</span>
                <span className="l">Средний CSAT ({reportQuery.data.csat.count})</span>
              </div>
              <div className="kpi">
                <span className="v">{reportQuery.data.backlog_aging.reduce((s, b) => s + b.count, 0)}</span>
                <span className="l">Открыто сейчас</span>
              </div>
            </div>
          </div>

          <div className="report-grid">
            <div className="panel span-2">
              <div className="panel-head">
                <h2>SLA — выполнение по приоритетам</h2>
              </div>
              <BarChart
                items={reportQuery.data.sla.by_priority.map((p) => ({
                  label: `${PRIORITY_LABELS[p.priority]} · реакция`,
                  value: p.reaction_met_pct ?? 0,
                }))}
                max={100}
              />
              {reportQuery.data.sla.violations.length > 0 && (
                <div className="list" style={{ marginTop: 14 }}>
                  <div className="list-head" style={{ gridTemplateColumns: "90px 2fr 1.4fr 1fr 1fr 1fr" }}>
                    <span>№</span>
                    <span>Тема</span>
                    <span>Организация</span>
                    <span>Приоритет</span>
                    <span>Реакция</span>
                    <span>Решение</span>
                  </div>
                  {reportQuery.data.sla.violations.slice(0, 10).map((v) => (
                    <div className="list-row" style={{ gridTemplateColumns: "90px 2fr 1.4fr 1fr 1fr 1fr" }} key={v.ticket_id}>
                      <span className="mono">{v.display_number}</span>
                      <span className="subject">{v.subject}</span>
                      <span className="muted">{v.organization}</span>
                      <span>
                        <PriorityTag priority={v.priority} />
                      </span>
                      <span className={v.reaction_met === false ? "muted" : ""} style={v.reaction_met === false ? { color: "var(--danger)", fontWeight: 700 } : undefined}>
                        {v.reaction_met === false ? "Нарушена" : "—"}
                      </span>
                      <span style={v.resolution_met === false ? { color: "var(--danger)", fontWeight: 700 } : undefined}>
                        {v.resolution_met === false ? "Нарушена" : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>CSAT</h2>
              </div>
              <div className="csat-score">
                <span className="big">{reportQuery.data.csat.average ?? "—"}</span>
                <span className="muted">/ 5 · {reportQuery.data.csat.count} оценок</span>
              </div>
              <BarChart items={reportQuery.data.csat.by_organization.slice(0, 5).map((r) => ({ label: r.label, value: r.average }))} max={5} />
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>Поток заявок по каналам</h2>
              </div>
              <BarChart
                items={reportQuery.data.flow.by_channel.map((c) => ({
                  label: CHANNEL_LABELS[c.channel as Channel] ?? c.channel,
                  value: c.count,
                }))}
              />
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>По категориям</h2>
              </div>
              <BarChart items={reportQuery.data.flow.by_category.slice(0, 6).map((c) => ({ label: c.category, value: c.count }))} />
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>Динамика заявок</h2>
              </div>
              <Sparkline points={reportQuery.data.flow.daily.map((d) => d.count)} />
              <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                {reportQuery.data.flow.daily.length} дн. в периоде
              </div>
            </div>

            <div className="panel">
              <div className="panel-head">
                <h2>Незакрытый backlog по возрасту</h2>
              </div>
              <BarChart items={reportQuery.data.backlog_aging.map((b) => ({ label: b.bucket, value: b.count }))} />
            </div>

            <div className="panel span-2">
              <div className="panel-head">
                <h2>Загрузка инженеров</h2>
              </div>
              {reportQuery.data.workload.length === 0 && <p className="muted">Нет данных за период</p>}
              {reportQuery.data.workload.length > 0 && (
                <table className="matrix-table">
                  <thead>
                    <tr>
                      <th>Инженер</th>
                      <th>Списано (billable)</th>
                      <th>Списано (non-billable)</th>
                      <th>Решено</th>
                      <th>Ср. время решения</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reportQuery.data.workload.map((row) => (
                      <tr key={row.engineer_id}>
                        <td>{row.engineer_name}</td>
                        <td className="mono">{formatMinutes(row.billable_minutes)}</td>
                        <td className="mono">{formatMinutes(row.non_billable_minutes)}</td>
                        <td className="mono">{row.resolved_count}</td>
                        <td className="mono">{row.avg_resolution_minutes != null ? formatMinutes(row.avg_resolution_minutes) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

