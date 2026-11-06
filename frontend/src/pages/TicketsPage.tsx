import { readTicketFilters } from "../lib/ticketFilters";
import { useEffect, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  createSavedFilter,
  deleteSavedFilter,
  listOrganizations,
  listSavedFilters,
  listTickets,
  listUsers,
} from "../api/endpoints";
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
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    status: statusFilter, priority: priorityFilter, organization: organizationFilter,
    assignee: assigneeFilter, risk: slaRiskFilter, search, openOnly, overdue: overdueOnly,
  } = readTicketFilters(searchParams);
  const [view, setView] = useState<"list" | "kanban">("list");
  const [page, setPage] = useState(0);

  // Search moved server-side along with paging: filtering the fetched array
  // would only ever search the page in hand. Debounced so typing doesn't
  // fire a request per keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState(search);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => clearTimeout(timer);
  }, [search]);

  const filters = [statusFilter, priorityFilter, organizationFilter, assigneeFilter, slaRiskFilter, debouncedSearch, openOnly, overdueOnly];
  // Any filter change invalidates the current page number - staying on page 5
  // of a result set that now has two pages would show an empty screen.
  useEffect(() => setPage(0), [statusFilter, priorityFilter, organizationFilter, assigneeFilter, slaRiskFilter, debouncedSearch, openOnly, overdueOnly]);

  // The Kanban board is a board of work in flight, so it needs the whole
  // (filtered) set at once rather than the list view's page.
  const pageSize = view === "kanban" ? 200 : 25;

  const qc = useQueryClient();
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const savedFiltersQuery = useQuery({ queryKey: ["saved-filters"], queryFn: listSavedFilters });

  const saveFilterMutation = useMutation({
    mutationFn: (name: string) =>
      createSavedFilter(name, {
        status_filter: statusFilter || undefined,
        priority: priorityFilter || undefined,
        organization_id: organizationFilter || undefined,
        assigned_engineer_id: assigneeFilter || undefined,
        sla_risk: slaRiskFilter || undefined,
        q: debouncedSearch || undefined,
        open_only: openOnly ? 1 : undefined,
        overdue: overdueOnly ? 1 : undefined,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-filters"] }),
  });
  const deleteFilterMutation = useMutation({
    mutationFn: (id: number) => deleteSavedFilter(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-filters"] }),
  });

  function updateUrl(key: string, value: string | number | boolean) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value === "" || value === false) next.delete(key);
      else next.set(key, value === true ? "1" : String(value));
      return next;
    }, { replace: true });
  }

  function applySavedFilter(criteria: Record<string, string | number | undefined>) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(criteria)) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    setSearchParams(params, { replace: true });
  }

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
        open_only: view === "list" && openOnly || undefined,
        exclude_archived: view === "kanban" || undefined,
        overdue: overdueOnly || undefined,
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
          <button className={view === "list" ? "active" : ""} aria-pressed={view === "list"} onClick={() => { setView("list"); setPage(0); }}>
            Список
          </button>
          <button className={view === "kanban" ? "active" : ""} aria-pressed={view === "kanban"} onClick={() => { setView("kanban"); setPage(0); }}>
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
          placeholder="Поиск по теме, номеру и переписке…"
          value={search}
          onChange={(e) => { updateUrl("q", e.target.value); }}
          aria-label="Поиск заявок"
          className="filter-search"
        />
        <select value={statusFilter} onChange={(e) => updateUrl("status_filter", e.target.value)} aria-label="Статус">
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select value={priorityFilter} onChange={(e) => updateUrl("priority", e.target.value)} aria-label="Приоритет">
          {PRIORITY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          value={organizationFilter}
          onChange={(e) => updateUrl("organization_id", e.target.value)} aria-label="Организация"
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
          onChange={(e) => updateUrl("assigned_engineer_id", e.target.value)} aria-label="Исполнитель"
        >
          <option value="">Все исполнители</option>
          {(usersQuery.data ?? []).map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name}
            </option>
          ))}
        </select>
        <select value={slaRiskFilter} onChange={(e) => updateUrl("sla_risk", e.target.value)} aria-label="SLA">
          {SLA_RISK_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div className="queue-scope">
        <label><input type="checkbox" checked={openOnly || view === "kanban"} disabled={view === "kanban"} onChange={(e) => updateUrl("open_only", e.target.checked)} /> {view === "kanban" ? "Активные и решённые" : "Только открытые"}</label>
        {overdueOnly && <span className="status-tag status-waiting">Просрочен срок решения</span>}
        <button className="btn-link" onClick={() => setSearchParams({}, { replace: true })}>Сбросить фильтры</button>
        <span className="muted">{ticketsQuery.isSuccess ? `Найдено: ${total}` : ""}</span>
      </div>
      {(saveFilterMutation.isError || deleteFilterMutation.isError) && <ErrorBanner message={(saveFilterMutation.error ?? deleteFilterMutation.error)?.message ?? "Не удалось изменить фильтр"} />}
      <div className="saved-filters">
        {(savedFiltersQuery.data ?? []).map((f) => (
          <span className="saved-filter-chip" key={f.id}>
            <button onClick={() => applySavedFilter(f.criteria)}>{f.name}</button>
            <button
              className="saved-filter-remove"
              title="Удалить фильтр"
              onClick={() => deleteFilterMutation.mutate(f.id)}
            >
              ✕
            </button>
          </span>
        ))}
        <button
          className="btn-link"
          disabled={saveFilterMutation.isPending}
          onClick={() => {
            const name = window.prompt("Название фильтра");
            if (name?.trim()) saveFilterMutation.mutate(name.trim());
          }}
        >
          + Сохранить текущий фильтр
        </button>
      </div>

      {ticketsQuery.isLoading && <Loading />}
      {ticketsQuery.isError && <ErrorBanner message={(ticketsQuery.error as Error).message} />}
      {ticketsQuery.isSuccess && filtered.length === 0 && <EmptyState text="Заявок по заданным фильтрам не найдено" />}
      {ticketsQuery.isSuccess && filtered.length > 0 && view === "kanban" && (
        <KanbanBoard tickets={filtered} orgsById={orgsById} usersById={usersById} />
      )}
      {ticketsQuery.isSuccess && filtered.length > 0 && view === "list" && (
        <div className="list ticket-list">
          <div className="list-head" style={{ gridTemplateColumns: "76px minmax(190px, 2.4fr) minmax(95px, 1fr) 60px 83px 120px 86px 104px 106px" }}>
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
              style={{ gridTemplateColumns: "76px minmax(190px, 2.4fr) minmax(95px, 1fr) 60px 83px 120px 86px 104px 106px" }}
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
          <button className="btn btn-ghost" disabled={page === 0 || ticketsQuery.isPlaceholderData} onClick={() => setPage((p) => p - 1)}>
            ← Назад
          </button>
          <span className="muted">
            Стр. {page + 1} из {pageCount}
          </span>
          <button
            className="btn btn-ghost"
            disabled={page + 1 >= pageCount || ticketsQuery.isPlaceholderData}
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
