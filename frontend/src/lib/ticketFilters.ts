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
  return {
    status: statuses.includes(status) ? status : "" as const,
    priority: (["P1", "P2", "P3", "P4"] as string[]).includes(priority) ? priority : "" as const,
    organization: positiveId(params.get("organization_id")),
    assignee: positiveId(params.get("assigned_engineer_id")),
    risk: (risk === "warning" || risk === "breached" ? risk : "") as "" | "warning" | "breached",
    search: params.get("q") ?? "",
    openOnly: params.get("open_only") === "1" || params.get("overdue") === "1",
    overdue: params.get("overdue") === "1",
  };
}
