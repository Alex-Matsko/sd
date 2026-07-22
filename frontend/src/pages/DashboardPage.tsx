import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listTickets } from "../api/endpoints";
import { ErrorBanner, Loading, PriorityTag } from "../components/ui";
import { STATUS_LABELS, formatDateTime } from "../lib/labels";
import type { TicketStatus } from "../api/types";

const OPEN_STATUSES: TicketStatus[] = [
  "new",
  "assigned",
  "in_progress",
  "waiting_customer",
  "waiting_third_party",
];

export function DashboardPage() {
  const ticketsQuery = useQuery({ queryKey: ["tickets", "dashboard"], queryFn: () => listTickets() });

  const stats = useMemo(() => {
    const tickets = ticketsQuery.data ?? [];
    const byStatus = new Map<TicketStatus, number>();
    let overdue = 0;
    const now = Date.now();
    for (const t of tickets) {
      byStatus.set(t.status, (byStatus.get(t.status) ?? 0) + 1);
      if (
        OPEN_STATUSES.includes(t.status) &&
        t.sla_resolution_due_at &&
        new Date(t.sla_resolution_due_at).getTime() < now
      ) {
        overdue += 1;
      }
    }
    const open = tickets.filter((t) => OPEN_STATUSES.includes(t.status));
    return { tickets, byStatus, overdue, open };
  }, [ticketsQuery.data]);

  if (ticketsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (ticketsQuery.isError) return <div className="view"><ErrorBanner message={(ticketsQuery.error as Error).message} /></div>;

  const recentOpen = [...stats.open]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 8);

  return (
    <div className="view">
      <h1 className="view-title">Дашборд</h1>

      <div className="stat-grid">
        <div className="stat-card">
          <span className="stat-value">{stats.open.length}</span>
          <span className="stat-label">Открытых заявок</span>
        </div>
        <div className="stat-card stat-card-warn">
          <span className="stat-value">{stats.overdue}</span>
          <span className="stat-label">Нарушение SLA</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{stats.byStatus.get("new") ?? 0}</span>
          <span className="stat-label">Новых</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{stats.byStatus.get("waiting_customer") ?? 0}</span>
          <span className="stat-label">Ждут клиента</span>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Последние открытые заявки</h2>
          <Link to="/tickets" className="link">
            Вся очередь →
          </Link>
        </div>
        {recentOpen.length === 0 && <p className="muted">Открытых заявок нет</p>}
        {recentOpen.length > 0 && (
          <div className="list">
            <div className="list-head" style={{ gridTemplateColumns: "100px 2fr 1fr 1fr 1fr" }}>
              <span>№</span>
              <span>Тема</span>
              <span>Приоритет</span>
              <span>Статус</span>
              <span>Создана</span>
            </div>
            {recentOpen.map((t) => (
              <Link className="list-row" style={{ gridTemplateColumns: "100px 2fr 1fr 1fr 1fr" }} key={t.id} to={`/tickets/${t.id}`}>
                <span className="mono">{t.display_number}</span>
                <span className="subject">{t.subject}</span>
                <span>
                  <PriorityTag priority={t.priority} />
                </span>
                <span className="muted">{STATUS_LABELS[t.status]}</span>
                <span className="muted">{formatDateTime(t.created_at)}</span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
