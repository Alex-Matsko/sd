import { apiRequest } from "./client";
import type {
  Asset,
  AuditLogEntry,
  BusinessCalendar,
  Category,
  Channel,
  Contact,
  Contract,
  ImpactUrgencyRule,
  Message,
  Notification,
  Organization,
  OrganizationUsage,
  Priority,
  RoutingRule,
  Tariff,
  TariffSlaRule,
  Team,
  TicketStatus,
  Ticket,
  TimeEntry,
  User,
} from "./types";

// --- Organizations ---
export function listOrganizations() {
  return apiRequest<Organization[]>("/organizations");
}
export function getOrganization(id: number) {
  return apiRequest<Organization>(`/organizations/${id}`);
}
export function createOrganization(payload: {
  name: string;
  legal_name?: string | null;
  account_manager_id?: number | null;
  email_domains?: string[];
}) {
  return apiRequest<Organization>("/organizations", { method: "POST", body: payload });
}
export function updateOrganization(id: number, payload: Partial<Organization>) {
  return apiRequest<Organization>(`/organizations/${id}`, { method: "PATCH", body: payload });
}
export function getOrganizationUsage(id: number, year?: number, month?: number) {
  return apiRequest<OrganizationUsage>(`/organizations/${id}/usage`, { query: { year, month } });
}

// --- Contacts ---
export function listContacts(organizationId?: number) {
  return apiRequest<Contact[]>("/contacts", { query: { organization_id: organizationId } });
}
export function createContact(payload: {
  organization_id: number;
  full_name: string;
  position?: string | null;
  is_vip?: boolean;
  can_view_org_tickets?: boolean;
  emails?: string[];
  phones?: string[];
}) {
  return apiRequest<Contact>("/contacts", { method: "POST", body: payload });
}
export function updateContact(id: number, payload: Partial<Contact>) {
  return apiRequest<Contact>(`/contacts/${id}`, { method: "PATCH", body: payload });
}

// --- Contracts ---
export function listContracts(organizationId?: number) {
  return apiRequest<Contract[]>("/contracts", { query: { organization_id: organizationId } });
}
export function createContract(payload: {
  organization_id: number;
  tariff_id: number;
  number: string;
  start_date: string;
  end_date?: string | null;
  included_hours_per_month: number;
  overage_rate_per_hour: number;
}) {
  return apiRequest<Contract>("/contracts", { method: "POST", body: payload });
}
export function updateContract(id: number, payload: Partial<Contract>) {
  return apiRequest<Contract>(`/contracts/${id}`, { method: "PATCH", body: payload });
}

// --- Tariffs ---
export function listTariffs() {
  return apiRequest<Tariff[]>("/tariffs");
}
export function createTariff(payload: { code: string; name: string; description?: string | null; business_calendar_id: number }) {
  return apiRequest<Tariff>("/tariffs", { method: "POST", body: payload });
}
export function updateTariff(id: number, payload: Partial<Tariff>) {
  return apiRequest<Tariff>(`/tariffs/${id}`, { method: "PATCH", body: payload });
}
export function replaceSlaRules(tariffId: number, rules: Omit<TariffSlaRule, "id">[]) {
  return apiRequest<Tariff>(`/tariffs/${tariffId}/sla-rules`, { method: "PUT", body: rules });
}

// --- Categories ---
export function listCategories() {
  return apiRequest<Category[]>("/categories");
}
export function createCategory(payload: { name: string; parent_id?: number | null }) {
  return apiRequest<Category>("/categories", { method: "POST", body: payload });
}
export function updateCategory(id: number, payload: Partial<Category>) {
  return apiRequest<Category>(`/categories/${id}`, { method: "PATCH", body: payload });
}
export function deleteCategory(id: number) {
  return apiRequest<void>(`/categories/${id}`, { method: "DELETE" });
}

// --- Assets ---
export function listAssets(organizationId?: number) {
  return apiRequest<Asset[]>("/assets", { query: { organization_id: organizationId } });
}
export function createAsset(payload: { organization_id: number; type: string; name: string; description?: string | null }) {
  return apiRequest<Asset>("/assets", { method: "POST", body: payload });
}
export function updateAsset(id: number, payload: Partial<Asset>) {
  return apiRequest<Asset>(`/assets/${id}`, { method: "PATCH", body: payload });
}
export function deleteAsset(id: number) {
  return apiRequest<void>(`/assets/${id}`, { method: "DELETE" });
}

// --- Teams ---
export function listTeams() {
  return apiRequest<Team[]>("/teams");
}
export function createTeam(payload: { name: string; lead_user_id?: number | null; member_user_ids?: number[] }) {
  return apiRequest<Team>("/teams", { method: "POST", body: payload });
}
export function updateTeam(id: number, payload: Partial<Team>) {
  return apiRequest<Team>(`/teams/${id}`, { method: "PATCH", body: payload });
}
export function setTeamMembers(id: number, memberUserIds: number[]) {
  return apiRequest<Team>(`/teams/${id}/members`, { method: "PUT", body: memberUserIds });
}

// --- Routing rules ---
export function listRoutingRules() {
  return apiRequest<RoutingRule[]>("/routing-rules");
}
export function createRoutingRule(payload: Omit<RoutingRule, "id">) {
  return apiRequest<RoutingRule>("/routing-rules", { method: "POST", body: payload });
}
export function updateRoutingRule(id: number, payload: Partial<RoutingRule>) {
  return apiRequest<RoutingRule>(`/routing-rules/${id}`, { method: "PATCH", body: payload });
}
export function deleteRoutingRule(id: number) {
  return apiRequest<void>(`/routing-rules/${id}`, { method: "DELETE" });
}

// --- Priority matrix ---
export function listPriorityMatrix() {
  return apiRequest<ImpactUrgencyRule[]>("/priority-matrix");
}
export function replacePriorityMatrix(rules: { impact: string; urgency: string; priority: Priority }[]) {
  return apiRequest<ImpactUrgencyRule[]>("/priority-matrix", { method: "PUT", body: rules });
}

// --- Calendars ---
export function listCalendars() {
  return apiRequest<BusinessCalendar[]>("/calendars");
}

// --- Users ---
export function listUsers() {
  return apiRequest<User[]>("/users");
}
export function createUser(payload: { full_name: string; email: string; password: string; role: string }) {
  return apiRequest<User>("/users", { method: "POST", body: payload });
}
export function updateUser(id: number, payload: Partial<User> & { password?: string }) {
  return apiRequest<User>(`/users/${id}`, { method: "PATCH", body: payload });
}

// --- Tickets ---
export interface TicketFilters {
  status_filter?: TicketStatus;
  organization_id?: number;
  assigned_engineer_id?: number;
  priority?: Priority;
  channel?: Channel;
  sla_risk?: "warning" | "breached";
}
export function listTickets(filters: TicketFilters = {}) {
  return apiRequest<Ticket[]>("/tickets", { query: filters as Record<string, string | number | undefined> });
}
export function getTicket(id: number) {
  return apiRequest<Ticket>(`/tickets/${id}`);
}
export function createTicket(payload: {
  contact_id: number;
  type: string;
  channel: string;
  subject: string;
  category_id?: number | null;
  asset_id?: number | null;
  impact?: string | null;
  urgency?: string | null;
  manual_priority?: string | null;
  manual_priority_reason?: string | null;
  initial_message?: string | null;
}) {
  return apiRequest<Ticket>("/tickets", { method: "POST", body: payload });
}
export function updateTicket(id: number, payload: Record<string, unknown>) {
  return apiRequest<Ticket>(`/tickets/${id}`, { method: "PATCH", body: payload });
}
export function listMessages(ticketId: number) {
  return apiRequest<Message[]>(`/tickets/${ticketId}/messages`);
}
export function createMessage(ticketId: number, payload: { direction: string; body: string; channel?: string | null }) {
  return apiRequest<Message>(`/tickets/${ticketId}/messages`, { method: "POST", body: payload });
}
export function listTimeEntries(ticketId: number) {
  return apiRequest<TimeEntry[]>(`/tickets/${ticketId}/time-entries`);
}
export function createTimeEntry(
  ticketId: number,
  payload: { entry_date: string; duration_minutes: number; comment?: string | null; is_billable?: boolean }
) {
  return apiRequest<TimeEntry>(`/tickets/${ticketId}/time-entries`, { method: "POST", body: payload });
}
export function updateTimeEntry(ticketId: number, entryId: number, payload: Partial<TimeEntry>) {
  return apiRequest<TimeEntry>(`/tickets/${ticketId}/time-entries/${entryId}`, { method: "PATCH", body: payload });
}
export function getTicketHistory(ticketId: number) {
  return apiRequest<AuditLogEntry[]>(`/tickets/${ticketId}/history`);
}

// --- Notifications ---
export function listNotifications(unreadOnly = false) {
  return apiRequest<Notification[]>("/notifications", { query: { unread_only: unreadOnly } });
}
export function markNotificationRead(id: number) {
  return apiRequest<Notification>(`/notifications/${id}/read`, { method: "POST" });
}
export function markAllNotificationsRead() {
  return apiRequest<void>("/notifications/read-all", { method: "POST" });
}
