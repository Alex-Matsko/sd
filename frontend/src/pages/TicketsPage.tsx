import { readTicketFilters, readQueuePage, readQueueView } from "../lib/ticketFilters";
import type { QueueScope, QueueView } from "../lib/ticketFilters";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { createSavedFilter, deleteSavedFilter, listOrganizations, listSavedFilters, listTickets, listUsers } from "../api/endpoints";
import { EmptyState, ErrorBanner, Loading, PriorityTag, SlaTag, StatusTag, ChannelTag } from "../components/ui";
import { formatDateTime, STATUS_LABELS } from "../lib/labels";
import { useAuth } from "../auth/AuthContext";
import { KanbanBoard } from "./KanbanBoard";
import type { Ticket, TicketStatus } from "../api/types";

const STATUS_OPTIONS: TicketStatus[] = ["new", "assigned", "in_progress", "waiting_customer", "waiting_third_party", "resolved", "closed", "cancelled"];
const SCOPES: { value: QueueScope; label: string; description: string }[] = [
  { value: "active", label: "Активные", description: "Текущая работа и заявки, ожидающие подтверждения решения" },
  { value: "archived", label: "Архив", description: "Закрытые и отменённые заявки — вся история остаётся доступной" },
  { value: "all", label: "Все заявки", description: "Активные, закрытые и отменённые заявки" },
];
function ViewIcon({ board }: { board?: boolean }) {
  return <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">{board ? <><rect x="2" y="3" width="4" height="14" rx="1"/><rect x="8" y="3" width="4" height="10" rx="1"/><rect x="14" y="3" width="4" height="12" rx="1"/></> : <><path d="M7 4h11M7 10h11M7 16h11"/><path d="M2 4h1M2 10h1M2 16h1"/></>}</svg>;
}
export function TicketsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const location = useLocation();
  const preferenceKey = `sd-ticket-view:${user?.id ?? "guest"}`;
  const [preferred, setPreferred] = useState(() => { try { return localStorage.getItem(preferenceKey); } catch { return null; } });
  const view = readQueueView(searchParams, preferred);
  const page = readQueuePage(searchParams);
  const { scope, status: statusFilter, priority: priorityFilter, organization: organizationFilter,
    assignee: assigneeFilter, risk: slaRiskFilter, search, openOnly, overdue: overdueOnly } = readTicketFilters(searchParams);
  const sort: "created_desc" | "number_asc" | "number_desc" = searchParams.get("sort") === "number_asc" ? "number_asc" : searchParams.get("sort") === "number_desc" ? "number_desc" : "created_desc";
  const activeFilterCount = [statusFilter, priorityFilter, organizationFilter, assigneeFilter, slaRiskFilter, openOnly && !overdueOnly, overdueOnly, sort !== "created_desc"].filter(Boolean).length;
  const [filtersOpen, setFiltersOpen] = useState(false);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<HTMLDivElement>(null);
  const [debouncedSearch, setDebouncedSearch] = useState(search);
  useEffect(() => { const timer = setTimeout(() => setDebouncedSearch(search.trim()), 300); return () => clearTimeout(timer); }, [search]);
  const qc = useQueryClient();
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const savedFiltersQuery = useQuery({ queryKey: ["saved-filters"], queryFn: listSavedFilters });
  const criteria = { scope, view, status_filter: statusFilter || undefined, priority: priorityFilter || undefined,
    organization_id: organizationFilter || undefined, assigned_engineer_id: assigneeFilter || undefined,
    sla_risk: slaRiskFilter || undefined, q: debouncedSearch || undefined,
    open_only: openOnly ? 1 : undefined, overdue: overdueOnly ? 1 : undefined, sort };
  const saveFilterMutation = useMutation({ mutationFn: (name: string) => createSavedFilter(name, criteria),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-filters"] }) });
  const deleteFilterMutation = useMutation({ mutationFn: deleteSavedFilter,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-filters"] }) });

  function updateUrl(key: string, value: string | number | boolean) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev); next.delete("page");
      if (value === "" || value === false) next.delete(key); else next.set(key, value === true ? "1" : String(value));
      if (key === "status_filter" && (value === "closed" || value === "cancelled")) {
        next.set("scope", "archived"); next.delete("open_only"); next.delete("overdue");
      } else if (key === "status_filter" && value && scope === "archived") next.set("scope", "active");
      if (key === "status_filter" && value === "resolved") { next.delete("open_only"); next.delete("overdue"); }
      return next;
    }, { replace: true });
  }
  function chooseView(next: QueueView) {
    setPreferred(next); try { localStorage.setItem(preferenceKey, next); } catch { /* URL remains sufficient when storage is unavailable. */ }
    updateUrl("view", next);
  }
  function chooseScope(nextScope: QueueScope) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev); next.set("scope", nextScope); next.delete("page");
      const terminal = statusFilter === "closed" || statusFilter === "cancelled";
      if ((nextScope === "active" && terminal) || (nextScope === "archived" && !terminal)) next.delete("status_filter");
      if (nextScope === "archived") { next.delete("open_only"); next.delete("overdue"); }
      return next;
    }, { replace: true });
  }
  function resetFilters() { setSearchParams({ view, scope }, { replace: true }); }
  function applySavedFilter(values: Record<string, string | number | undefined>) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== "") params.set(key, String(value));
    params.delete("page"); setSearchParams(params, { replace: true }); setFiltersOpen(false);
  }
  function choosePage(nextPage: number) {
    setSearchParams((prev) => { const next = new URLSearchParams(prev); if (nextPage === 0) next.delete("page"); else next.set("page", String(nextPage + 1)); return next; }, { replace: true });
  }
  const apiFilters = { scope, sort, status_filter: statusFilter || undefined, priority: priorityFilter || undefined,
    organization_id: organizationFilter || undefined, assigned_engineer_id: assigneeFilter || undefined,
    sla_risk: slaRiskFilter || undefined, q: debouncedSearch || undefined, open_only: openOnly || undefined, overdue: overdueOnly || undefined };
  const key = ["tickets", "queue", scope, statusFilter, priorityFilter, organizationFilter, assigneeFilter, slaRiskFilter, debouncedSearch, openOnly, overdueOnly, sort];
  const listKey = [...key, "list"];
  const listQuery = useQuery({ queryKey: [...listKey, page], queryFn: () => listTickets({ ...apiFilters, limit: 25, offset: page * 25 }),
    enabled: view === "list", refetchInterval: 30_000,
    placeholderData: (previous, previousQuery) => JSON.stringify(previousQuery?.queryKey.slice(0, -1)) === JSON.stringify(listKey) ? previous : undefined });
  const boardQuery = useInfiniteQuery({ queryKey: [...key, "kanban"], initialPageParam: 0,
    queryFn: ({ pageParam }) => listTickets({ ...apiFilters, limit: 100, offset: pageParam }),
    getNextPageParam: (last, pages) => { const loaded = pages.reduce((n, p) => n + p.items.length, 0); return last.items.length > 0 && loaded < last.total ? loaded : undefined; },
    enabled: view === "kanban", refetchInterval: 30_000 });
  const ticketsQuery = view === "list" ? listQuery : boardQuery;
  const filtered: Ticket[] = view === "list" ? listQuery.data?.items ?? []
    : [...new Map((boardQuery.data?.pages.flatMap((p) => p.items) ?? []).map((t) => [t.id, t])).values()];
  const total = view === "list" ? listQuery.data?.total ?? 0 : boardQuery.data?.pages[0]?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / 25));
  useEffect(() => {
    if (view !== "list" || !listQuery.isSuccess || listQuery.isPlaceholderData || page < pageCount) return;
    setSearchParams((prev) => { const next = new URLSearchParams(prev); if (pageCount <= 1) next.delete("page"); else next.set("page", String(pageCount)); return next; }, { replace: true });
  }, [view, listQuery.isSuccess, listQuery.isPlaceholderData, page, pageCount, setSearchParams]);
  const orgsById = new Map((orgsQuery.data ?? []).map((o) => [o.id, o]));
  const usersById = new Map((usersQuery.data ?? []).map((u) => [u.id, u]));
  useLayoutEffect(() => {
    const root = workspaceRef.current, controls = controlsRef.current;
    if (!root || !controls || view !== "kanban" || !ticketsQuery.isSuccess) return;
    const fitBoard = () => {
      const board = root.querySelector(".kanban-board");
      if (!board) return;
      const height = Math.max(240, Math.min(window.innerHeight - 90, window.innerHeight - board.getBoundingClientRect().top - 48));
      root.style.setProperty("--queue-board-height", `${height}px`);
    };
    const observer = new ResizeObserver(fitBoard);
    observer.observe(controls); window.addEventListener("resize", fitBoard); fitBoard();
    return () => { observer.disconnect(); window.removeEventListener("resize", fitBoard); };
  }, [view, ticketsQuery.isSuccess]);
  const activeFilters: { key: string; label: string }[] = [];
  if (organizationFilter) activeFilters.push({ key: "organization_id", label: orgsById.get(organizationFilter)?.name ?? "Организация" });
  if (assigneeFilter) activeFilters.push({ key: "assigned_engineer_id", label: usersById.get(assigneeFilter)?.full_name ?? "Исполнитель" });
  if (statusFilter) activeFilters.push({ key: "status_filter", label: STATUS_LABELS[statusFilter] });
  if (priorityFilter) activeFilters.push({ key: "priority", label: priorityFilter });
  if (slaRiskFilter) activeFilters.push({ key: "sla_risk", label: slaRiskFilter === "warning" ? "Риск SLA" : "SLA нарушен" });
  if (overdueOnly) activeFilters.push({ key: "overdue", label: "Просроченные" });
  else if (openOnly) activeFilters.push({ key: "open_only", label: "Незавершённые" });
  if (sort !== "created_desc") activeFilters.push({ key: "sort", label: sort === "number_asc" ? "Номер ↑" : "Номер ↓" });
  const queueReturn = `/tickets?${new URLSearchParams({ ...Object.fromEntries(searchParams), view, scope }).toString()}`;

  return <div ref={workspaceRef} className="view ticket-workspace">
    <div ref={controlsRef} className="queue-controls">
      <div className="queue-workbar"><h1 className="view-title">Заявки <span className="queue-total" role="status">{ticketsQuery.isSuccess ? total : "…"}</span></h1>
        <div className="queue-tabs" role="group" aria-label="Показывать заявки">{SCOPES.map((item) => <button type="button" key={item.value} title={item.description} className={scope === item.value ? "active" : ""} aria-pressed={scope === item.value} onClick={() => chooseScope(item.value)}>{item.label}</button>)}</div>
        <div className="spacer" /><Link to="/tickets/new" className="btn btn-primary queue-create">+ Новая заявка</Link>
      </div>
      <div className="queue-tools"><div className="view-toggle" role="group" aria-label="Вид заявок"><button type="button" className={view === "list" ? "active" : ""} aria-pressed={view === "list"} onClick={() => chooseView("list")}><ViewIcon />Список</button><button type="button" className={view === "kanban" ? "active" : ""} aria-pressed={view === "kanban"} onClick={() => chooseView("kanban")}><ViewIcon board />Канбан</button></div>
        <input type="search" placeholder={scope === "archived" ? "Поиск в архиве…" : "Поиск заявок…"} value={search} onChange={(e) => updateUrl("q", e.target.value)} aria-label="Поиск заявок" />
        <button type="button" className={`btn btn-ghost queue-filter-button ${activeFilterCount ? "has-filters" : ""}`} title="Фильтры и сортировка" aria-expanded={filtersOpen} aria-controls="queue-filters" onClick={() => setFiltersOpen((v) => !v)}>Фильтры{activeFilterCount > 0 && <span>{activeFilterCount}</span>}</button>
      </div>
      {!filtersOpen && activeFilters.length > 0 && <div className="queue-active-filters" aria-label="Применённые фильтры">{activeFilters.slice(0, 2).map((filter) => <button type="button" className="queue-filter-pill" key={filter.key} title={`Убрать фильтр: ${filter.label}`} onClick={() => updateUrl(filter.key, "")}><span>{filter.label}</span><span aria-hidden="true">×</span></button>)}{activeFilters.length > 2 && <button type="button" className="btn-link" onClick={() => setFiltersOpen(true)}>Ещё {activeFilters.length - 2}</button>}<button type="button" className="btn-link" onClick={resetFilters}>Сбросить</button></div>}
      {filtersOpen && <div id="queue-filters" className="queue-filter-panel"><div className="filter-bar">
        <label>Статус<select value={statusFilter} onChange={(e) => updateUrl("status_filter", e.target.value)} aria-label="Статус"><option value="">Все статусы</option>{STATUS_OPTIONS.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}</select></label>
        <label>Приоритет<select value={priorityFilter} onChange={(e) => updateUrl("priority", e.target.value)} aria-label="Приоритет"><option value="">Любой приоритет</option>{["P1", "P2", "P3", "P4"].map((p) => <option key={p}>{p}</option>)}</select></label>
        <label>Организация<select value={organizationFilter} onChange={(e) => updateUrl("organization_id", e.target.value)} aria-label="Организация"><option value="">Все организации</option>{(orgsQuery.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
        <label>Исполнитель<select value={assigneeFilter} onChange={(e) => updateUrl("assigned_engineer_id", e.target.value)} aria-label="Исполнитель"><option value="">Все исполнители</option>{(usersQuery.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></label>
        <label>Сортировка<select aria-label="Сортировка заявок" value={sort} onChange={(e) => updateUrl("sort", e.target.value)}><option value="created_desc">Сначала новые</option><option value="number_asc">Номер: по возрастанию</option><option value="number_desc">Номер: по убыванию</option></select></label>
        <label>SLA<select value={slaRiskFilter} onChange={(e) => updateUrl("sla_risk", e.target.value)} aria-label="SLA"><option value="">Любой SLA</option><option value="warning">Риск нарушения</option><option value="breached">Нарушен</option></select></label>
      </div><div className="queue-extra-filters"><label><input type="checkbox" checked={openOnly} disabled={scope === "archived"} onChange={(e) => updateUrl("open_only", e.target.checked)} />Только незавершённые</label>{overdueOnly && <span className="status-tag status-waiting">Просрочен срок решения</span>}<button type="button" className="btn-link" onClick={resetFilters}>Сбросить фильтры</button></div></div>}
      {filtersOpen && <div className="queue-filter-summary"><div className="saved-filters">{(savedFiltersQuery.data ?? []).map((f) => <span className="saved-filter-chip" key={f.id}><button type="button" onClick={() => applySavedFilter(f.criteria)}>{f.name}</button><button type="button" className="saved-filter-remove" title={`Удалить фильтр ${f.name}`} disabled={deleteFilterMutation.isPending} onClick={() => deleteFilterMutation.mutate(f.id)}>×</button></span>)}<button type="button" className="btn-link" disabled={saveFilterMutation.isPending} onClick={() => { const name = window.prompt("Название фильтра"); if (name?.trim()) saveFilterMutation.mutate(name.trim()); }}>Сохранить фильтр</button></div></div>}
    </div>
    {(saveFilterMutation.isError || deleteFilterMutation.isError) && <ErrorBanner message={(saveFilterMutation.error ?? deleteFilterMutation.error)?.message ?? "Не удалось изменить фильтр"} />}
    {ticketsQuery.isLoading && <Loading />}{ticketsQuery.isError && <ErrorBanner message={ticketsQuery.error?.message ?? "Не удалось загрузить заявки"} />}
    {ticketsQuery.isSuccess && filtered.length === 0 && <div className="queue-empty"><EmptyState text={scope === "archived" && !search && !activeFilterCount ? "В архиве пока нет заявок" : "Заявок по заданным условиям не найдено"} />{scope === "active" && <button type="button" className="btn btn-ghost" onClick={() => chooseScope("archived")}>Посмотреть в архиве</button>}</div>}
    {ticketsQuery.isSuccess && view === "kanban" && <KanbanBoard tickets={filtered} scope={scope} queueReturn={queueReturn} backgroundLocation={location} orgsById={orgsById} usersById={usersById} />}
    {ticketsQuery.isSuccess && filtered.length > 0 && view === "list" && <div className="list ticket-list"><div className="list-head">{["№", "Тема", "Организация", "Канал", "Приоритет", "Статус", "SLA", "Исполнитель", "Создана"].map((name) => <span key={name}>{name}</span>)}</div>
      {filtered.map((t) => <Link className="list-row" key={t.id} to={`/tickets/${t.id}`} state={{ queueReturn, backgroundLocation: location }}><span className="mono">{t.display_number}</span><span className="subject">{t.subject}</span><span className="muted">{orgsById.get(t.organization_id)?.name ?? "—"}</span><span><ChannelTag channel={t.channel} /></span><span><PriorityTag priority={t.priority} /></span><span><StatusTag status={t.status} /></span><span><SlaTag sla={t.sla} /></span><span className="muted">{t.assigned_engineer_id ? usersById.get(t.assigned_engineer_id)?.full_name ?? "—" : "Не назначено"}</span><span className="muted">{formatDateTime(t.created_at)}</span></Link>)}
    </div>}
    {ticketsQuery.isSuccess && view === "list" && total > 0 && <div className="pagination"><span className="muted">{page * 25 + 1}–{Math.min((page + 1) * 25, total)} из {total}</span><div className="spacer" /><button type="button" className="btn btn-ghost" disabled={page === 0 || listQuery.isPlaceholderData} onClick={() => choosePage(page - 1)}>← Назад</button><span className="muted">Стр. {page + 1} из {pageCount}</span><button type="button" className="btn btn-ghost" disabled={page + 1 >= pageCount || listQuery.isPlaceholderData} onClick={() => choosePage(page + 1)}>Вперёд →</button></div>}
    {ticketsQuery.isSuccess && view === "kanban" && <div className="queue-board-pagination"><span className="muted">На доске {filtered.length} из {total} заявок</span>{boardQuery.hasNextPage && <button type="button" className="btn btn-ghost" disabled={boardQuery.isFetchingNextPage} onClick={() => boardQuery.fetchNextPage()}>{boardQuery.isFetchingNextPage ? "Загрузка…" : "Загрузить ещё"}</button>}</div>}
  </div>;
}
