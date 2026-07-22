import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listOrganizations, listTickets, listUsers } from "../api/endpoints";
import { EmptyState, ErrorBanner, Loading, PriorityTag, SlaTag, StatusTag, ChannelTag } from "../components/ui";
import { formatDateTime } from "../lib/labels";
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
  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<Priority | "">("");
  const [organizationFilter, setOrganizationFilter] = useState<number | "">("");
  const [assigneeFilter, setAssigneeFilter] = useState<number | "">("");
  const [slaRiskFilter, setSlaRiskFilter] = useState<"" | "warning" | "breached">("");
  const [search, setSearch] = useState("");

  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const ticketsQuery = useQuery({
    queryKey: ["tickets", statusFilter, priorityFilter, organizationFilter, assigneeFilter, slaRiskFilter],
    queryFn: () =>
      listTickets({
        status_filter: statusFilter || undefined,
        priority: priorityFilter || undefined,
        organization_id: organizationFilter || undefined,
        assigned_engineer_id: assigneeFilter || undefined,
        sla_risk: slaRiskFilter || undefined,
      }),
    refetchInterval: 30_000,
  });

  const orgsById = new Map((orgsQuery.data ?? []).map((o) => [o.id, o]));
  const usersById = new Map((usersQuery.data ?? []).map((u) => [u.id, u]));

  const filtered = useMemo(() => {
    const tickets = ticketsQuery.data ?? [];
    if (!search.trim()) return tickets;
    const q = search.trim().toLowerCase();
    return tickets.filter((t) => t.subject.toLowerCase().includes(q) || t.display_number.toLowerCase().includes(q));
  }, [ticketsQuery.data, search]);

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Очередь заявок
        </h1>
        <div className="spacer" />
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
      {ticketsQuery.isSuccess && filtered.length > 0 && (
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
    </div>
  );
}
