import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getTicketStats, listTickets } from "../api/endpoints";
import { ErrorBanner, Loading, PriorityTag } from "../components/ui";
import { STATUS_LABELS, formatDateTime } from "../lib/labels";

const WEEKDAYS = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

/** Поток заявок за неделю (ТЗ 8.3). Две полосы на день вместо линейного
 *  графика: смысл здесь не в тренде, а в том, разгребаем мы очередь или она
 *  копится, — а это читается по тому, какая полоса длиннее. */
function WeekFlow({ days }: { days: { date: string; created: number; closed: number }[] }) {
  const peak = Math.max(1, ...days.flatMap((d) => [d.created, d.closed]));
  return (
    <div className="week-flow">
      {days.map((day) => {
        const date = new Date(day.date);
        return (
          <div className="week-flow-day" key={day.date}>
            <div className="week-flow-bars">
              <div
                className="week-flow-bar week-flow-bar-created"
                style={{ height: `${(day.created / peak) * 100}%` }}
                title={`Создано: ${day.created}`}
              />
              <div
                className="week-flow-bar week-flow-bar-closed"
                style={{ height: `${(day.closed / peak) * 100}%` }}
                title={`Закрыто: ${day.closed}`}
              />
            </div>
            <span className="week-flow-label muted">{WEEKDAYS[date.getDay()]}</span>
            <span className="week-flow-value mono">
              {day.created}/{day.closed}
            </span>
          </div>
        );
      })}
    </div>
  );
}

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
  const workload = stats.workload ?? [];
  const workloadPeak = Math.max(1, ...workload.map((w) => w.open_tickets));

  return (
    <div className="view">
      <h1 className="view-title">Дашборд</h1>

      <div className="stat-grid">
        <div className="stat-card">
          <span className="stat-value">{stats.open_total}</span>
          <span className="stat-label">Открытых заявок</span>
        </div>
        {/* Тревожный цвет — только когда есть о чём тревожиться. Ноль,
            подсвеченный красным, приучает не смотреть на цвет вообще. */}
        <Link className={`stat-card${stats.overdue > 0 ? " stat-card-danger" : ""}`} to="/tickets?overdue=1">
          <span className="stat-value">{stats.overdue}</span>
          <span className="stat-label">Нарушение SLA</span>
        </Link>
        <div className={`stat-card${stats.at_risk_today > 0 ? " stat-card-warn" : ""}`}>
          <span className="stat-value">{stats.at_risk_today}</span>
          <span className="stat-label">Срок решения истекает сегодня</span>
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

      <div className="dashboard-columns">
        <div className="panel">
          <div className="panel-head">
            <h2>Поток за неделю</h2>
            <span className="muted week-flow-legend">
              <i className="swatch swatch-created" /> создано
              <i className="swatch swatch-closed" /> закрыто
            </span>
          </div>
          {(stats.week_flow ?? []).length === 0 ? (
            <p className="muted">Данных пока нет</p>
          ) : (
            <WeekFlow days={stats.week_flow} />
          )}
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>Загрузка инженеров</h2>
          </div>
          {workload.length === 0 && <p className="muted">Открытых заявок ни на кого не назначено</p>}
          {workload.map((row) => (
            <div className="workload-row" key={row.engineer_name}>
              <span className="workload-name">{row.engineer_name}</span>
              <span className="workload-track">
                <span className="workload-fill" style={{ width: `${(row.open_tickets / workloadPeak) * 100}%` }} />
              </span>
              <span className="mono">{row.open_tickets}</span>
            </div>
          ))}
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
