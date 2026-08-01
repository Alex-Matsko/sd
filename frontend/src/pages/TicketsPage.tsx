import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { listOrganizations, listTickets, listUsers } from "../api/endpoints";
import { EmptyState, ErrorBanner, Loading, PriorityTag, SlaTag, StatusTag, ChannelTag } from "../components/ui";
import { formatDateTime } from "../lib/labels";
import { KanbanBoard } from "./KanbanBoard";
import type { Priority, TicketStatus } from "../api/types";

const SLA_RISK_OPTIONS: { value: "" | "warning" | "breached"; label: string }[] = [
  { value: "", label: "Любой SLA-риск" },
  { value: "warning", label: "Риск (75%+)" },
  { value: "breached", label: "Нарушен" },
];

const STATUS_OPTIONS: { value: TicketStatus | ""; label: string }[] = [
  { value: "", label: "Все статусы" },
  { value: "new", label: "Новая" },
  { value: "assigned", label: "Назначена" },
  { value: "in_progress", label: "В работе" },
  { value: "waiting_customer", label: "Ждём клиента" },
  { value: "waiting_third_party", label: "Ждём третью сторону" },
  { value: "resolved", label: "Решена" },
  { value: "closed", label: "Закрыта" },
  { value: "cancelled", label: "Отменена" },
];

const PRIORITY_OPTIONS: { value: Priority | ""; label: string }[] = [
  { value: "", label: "Любой приоритет" },
  { value: "P1", label: "P1" },
  { value: "P2", label: "P2" },
  { value: "P3", label: "P3" },
  { value: "P4", label: "P4" },
];

export function TicketsPage() {
  const [searchParams] = useSearchParams();
  const initialOrgId = searchParams.get("organization_id");

  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<Priority | "">("");
  const [organizationFilter, setOrganizationFilter] = useState<number | "">(initialOrgId ? Number(initialOrgId) : "");
  const [assigneeFilter, setAssigneeFilter] = useState<number | "">("");
  const [slaRiskFilter, setSlaRiskFilter] = useState<"" | "warning" | "breached">("");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"list" | "kanban">("list");
  const [page, setPage] = useState(0);

  // Search moved server-side along with paging: filtering the fetched array
  // would only ever search the page in hand. Debounced so typing doesn't
  // fire a request per keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => clearTimeout(timer);
  }, [search]);

  const filters = [statusFilter, priorityFilter, organizationFilter, assigneeFilter, slaRiskFilter, debouncedSearch];
  // Any filter change invalidates the current page number - staying on page 5
  // of a result set that now has two pages would show an empty screen.
  useEffect(() => setPage(0), filters);

  // The Kanban board is a board of work in flight, so it needs the whole
  // (filtered) set at once rather than the list view's page.
  const pageSize = view === "kanban" ? 200 : 25;

  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const ticketsQuery = useQuery({
    queryKey: ["tickets", ...filters, view, page],
    queryFn: () =>
      listTickets({
        status_filter: statusFilter || undefined,
        priority: priorityFilter || undefined,
        organization_id: organizationFilter || undefined,
        assigned_engineer_id: assigneeFilter || undefined,
        sla_risk: slaRiskFilter || undefined,
        q: debouncedSearch || undefined,
        limit: pageSize,
        offset: view === "kanban" ? 0 : page * pageSize,
      }),
    refetchInterval: 30_000,
    // Keeps the previous page visible while the next one loads, instead of
    // collapsing the table to a spinner on every page step.
    placeholderData: keepPreviousData,
  });

  const orgsById = new Map((orgsQuery.data ?? []).map((o) => [o.id, o]));
  const usersById = new Map((usersQuery.data ?? []).map((u) => [u.id, u]));

  const filtered = ticketsQuery.data?.items ?? [];
  const total = ticketsQuery.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Очередь заявок
        </h1>
        <div className="spacer" />
        <div className="view-toggle">
          <button className={view === "list" ? "active" : ""} onClick={() => setView("list")}>
            Список
          </button>
          <button className={view === "kanban" ? "active" : ""} onClick={() => setView("kanban")}>
            Канбан
          </button>
        </div>
        <Link to="/tickets/new" className="btn btn-primary">
          Новая заявка
        </Link>
      </div>

      <div className="filter-bar">
        <input
          type="text"
          placeholder="Поиск по теме или номеру…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="filter-search"
        />
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as TicketStatus | "")}>
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value as Priority | "")}>
          {PRIORITY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          value={organizationFilter}
          onChange={(e) => setOrganizationFilter(e.target.value ? Number(e.target.value) : "")}
        >
          <option value="">Все организации</option>
          {(orgsQuery.data ?? []).map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <select
          value={assigneeFilter}
          onChange={(e) => setAssigneeFilter(e.target.value ? Number(e.target.value) : "")}
        >
          <option value="">Все исполнители</option>
          {(usersQuery.data ?? []).map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name}
            </option>
          ))}
        </select>
        <select value={slaRiskFilter} onChange={(e) => setSlaRiskFilter(e.target.value as "" | "warning" | "breached")}>
          {SLA_RISK_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {ticketsQuery.isLoading && <Loading />}
      {ticketsQuery.isError && <ErrorBanner message={(ticketsQuery.error as Error).message} />}
      {ticketsQuery.isSuccess && filtered.length === 0 && <EmptyState text="Заявок по заданным фильтрам не найдено" />}
      {ticketsQuery.isSuccess && filtered.length > 0 && view === "kanban" && (
        <KanbanBoard tickets={filtered} orgsById={orgsById} usersById={usersById} />
      )}
      {ticketsQuery.isSuccess && filtered.length > 0 && view === "list" && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "90px 2fr 1fr 1fr 1fr 1.2fr 1fr 1fr 1fr" }}>
            <span>№</span>
            <span>Тема</span>
            <span>Организация</span>
            <span>Канал</span>
            <span>Приоритет</span>
            <span>Статус</span>
            <span>SLA</span>
            <span>Исполнитель</span>
            <span>Создана</span>
          </div>
          {filtered.map((t) => (
            <Link
              className="list-row"
              style={{ gridTemplateColumns: "90px 2fr 1fr 1fr 1fr 1.2fr 1fr 1fr 1fr" }}
              key={t.id}
              to={`/tickets/${t.id}`}
            >
              <span className="mono">{t.display_number}</span>
              <span className="subject">{t.subject}</span>
              <span className="muted">{orgsById.get(t.organization_id)?.name ?? "—"}</span>
              <span>
                <ChannelTag channel={t.channel} />
              </span>
              <span>
                <PriorityTag priority={t.priority} />
              </span>
              <span>
                <StatusTag status={t.status} />
              </span>
              <span>
                <SlaTag sla={t.sla} />
              </span>
              <span className="muted">
                {t.assigned_engineer_id ? usersById.get(t.assigned_engineer_id)?.full_name ?? "—" : "Не назначено"}
              </span>
              <span className="muted">{formatDateTime(t.created_at)}</span>
            </Link>
          ))}
        </div>
      )}

      {ticketsQuery.isSuccess && view === "list" && total > 0 && (
        <div className="pagination">
          <span className="muted">
            {page * pageSize + 1}–{Math.min((page + 1) * pageSize, total)} из {total}
          </span>
          <div className="spacer" />
          <button className="btn btn-ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            ← Назад
          </button>
          <span className="muted">
            Стр. {page + 1} из {pageCount}
          </span>
          <button
            className="btn btn-ghost"
            disabled={page + 1 >= pageCount}
            onClick={() => setPage((p) => p + 1)}
          >
            Вперёд →
          </button>
        </div>
      )}
      {ticketsQuery.isSuccess && view === "kanban" && total > filtered.length && (
        <p className="muted" style={{ marginTop: 12 }}>
          На доске показаны {filtered.length} из {total} заявок — уточните фильтры, чтобы увидеть остальные.
        </p>
      )}
    </div>
  );
}
