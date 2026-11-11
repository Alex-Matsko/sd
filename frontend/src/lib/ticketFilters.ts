import type { Priority, TicketStatus } from "../api/types";

export function positiveId(value: string | null): number | "" {
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : "";
}

export function readTicketFilters(params: URLSearchParams) {
  const statuses: TicketStatus[] = ["new", "assigned", "in_progress", "waiting_customer", "waiting_third_party", "resolved", "closed", "cancelled"];
  const status = params.get("status_filter") as TicketStatus;
  const priority = params.get("priority") as Priority;
  const risk = params.get("sla_risk");
  const chosenScope = params.get("scope");
  const scope: QueueScope = chosenScope === "active" || chosenScope === "archived" || chosenScope === "all" ? chosenScope
    : status === "closed" || status === "cancelled" ? "archived" : params.get("open_only") === "0" ? "all" : "active";
  return {
    scope,
    status: statuses.includes(status) ? status : "" as const,
    priority: (["P1", "P2", "P3", "P4"] as string[]).includes(priority) ? priority : "" as const,
    organization: positiveId(params.get("organization_id")),
    assignee: positiveId(params.get("assigned_engineer_id")),
    risk: (risk === "warning" || risk === "breached" ? risk : "") as "" | "warning" | "breached",
    search: params.get("q") ?? "",
    openOnly: scope !== "archived" && (params.get("open_only") === "1" || params.get("overdue") === "1"),
    overdue: scope !== "archived" && params.get("overdue") === "1",
  };
}

export type QueueScope = "active" | "archived" | "all";
export type QueueView = "list" | "kanban";
export function readQueueView(params: URLSearchParams, preferred: string | null): QueueView {
  const requested = params.get("view");
  if (requested === "list" || requested === "kanban") return requested;
  return preferred === "list" ? "list" : "kanban";
}
export function readQueuePage(params: URLSearchParams): number {
  const page = Number(params.get("page"));
  return Number.isSafeInteger(page) && page > 0 && page <= 1000000 ? page - 1 : 0;
}

export function kanbanColumns(scope: QueueScope): TicketStatus[] {
  const active: TicketStatus[] = ["new", "assigned", "in_progress", "waiting_customer", "waiting_third_party", "resolved"];
  const archived: TicketStatus[] = ["closed", "cancelled"];
  return scope === "archived" ? archived : scope === "all" ? [...active, ...archived] : active;
}
