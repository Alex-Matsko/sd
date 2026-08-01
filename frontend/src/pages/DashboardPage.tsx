import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getTicketStats, listTickets } from "../api/endpoints";
import { ErrorBanner, Loading, PriorityTag } from "../components/ui";
import { STATUS_LABELS, formatDateTime } from "../lib/labels";

export function DashboardPage() {
  // Counters come from the server rather than from counting a fetched list:
  // the queue is paged, so a client-side tally would silently only cover the
  // first page once the system has more than a page's worth of tickets.
  const statsQuery = useQuery({ queryKey: ["ticket-stats"], queryFn: getTicketStats, refetchInterval: 60_000 });
  const recentQuery = useQuery({
    queryKey: ["tickets", "dashboard-recent"],
    queryFn: () => listTickets({ limit: 8 }),
    refetchInterval: 60_000,
  });

  if (statsQuery.isLoading || recentQuery.isLoading) return <div className="view"><Loading /></div>;
  if (statsQuery.isError) return <div className="view"><ErrorBanner message={(statsQuery.error as Error).message} /></div>;

  const stats = statsQuery.data!;
  const recentOpen = recentQuery.data?.items ?? [];

  return (
    <div className="view">
      <h1 className="view-title">Дашборд</h1>

      <div className="stat-grid">
        <div className="stat-card">
          <span className="stat-value">{stats.open_total}</span>
          <span className="stat-label">Открытых заявок</span>
        </div>
        <div className="stat-card stat-card-warn">
          <span className="stat-value">{stats.overdue}</span>
          <span className="stat-label">Нарушение SLA</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{stats.by_status.new ?? 0}</span>
          <span className="stat-label">Новых</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{stats.by_status.waiting_customer ?? 0}</span>
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
