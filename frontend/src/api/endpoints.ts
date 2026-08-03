import { apiDownload, apiPage, apiRequest, apiUpload } from "./client";
import type {
  Asset,
  Attachment,
  Call,
  AuditLogEntry,
  AutomationRule,
  BusinessCalendar,
  Category,
  Channel,
  Contact,
  Contract,
  ImpactUrgencyRule,
  IntegrationSetting,
  Message,
  Notification,
  Organization,
  OrganizationEmailDomain,
  OrganizationUsage,
  Priority,
  ReportsOverview,
  ResponseTemplate,
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
export function addOrganizationEmailDomain(id: number, domain: string) {
  return apiRequest<OrganizationEmailDomain>(`/organizations/${id}/email-domains`, { method: "POST", body: { domain } });
}
export function removeOrganizationEmailDomain(id: number, domainId: number) {
  return apiRequest<void>(`/organizations/${id}/email-domains/${domainId}`, { method: "DELETE" });
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
export function mergeContact(contactId: number, intoContactId: number) {
  return apiRequest<Contact>(`/contacts/${contactId}/merge`, { method: "POST", body: { into_contact_id: intoContactId } });
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
  q?: string;
  limit?: number;
  offset?: number;
}
export function listTickets(filters: TicketFilters = {}) {
  return apiPage<Ticket>("/tickets", filters as Record<string, string | number | undefined>);
}
export interface TicketStats {
  by_status: Record<TicketStatus, number>;
  open_total: number;
  overdue: number;
  /** Заявки, у которых срок решения истекает сегодня, — по ТЗ 8.3 это главное,
   *  на что смотрит руководитель утром. */
  at_risk_today: number;
  week_flow: { date: string; created: number; closed: number }[];
  workload: { engineer_name: string; open_tickets: number }[];
}
export function getTicketStats() {
  return apiRequest<TicketStats>("/tickets/stats");
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
export function createMessage(
  ticketId: number,
  payload: { direction: string; body: string; channel?: string | null; reply_to_message_id?: number | null }
) {
  return apiRequest<Message>(`/tickets/${ticketId}/messages`, { method: "POST", body: payload });
}
export function uploadAttachment(ticketId: number, messageId: number, file: File) {
  return apiUpload<Attachment>(`/tickets/${ticketId}/messages/${messageId}/attachments`, file);
}
export function downloadAttachment(ticketId: number, attachment: Attachment) {
  return apiDownload(`/tickets/${ticketId}/attachments/${attachment.id}`, attachment.filename);
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

// Таймер принадлежит сотруднику, а не заявке: одновременно он может быть
// запущен только один, поэтому «активный таймер» спрашивается без id заявки.
export interface ActiveTimer {
  running: boolean;
  ticket_id?: number;
  display_number?: string;
  started_at?: string;
}
export function getActiveTimer() {
  return apiRequest<ActiveTimer>("/tickets/timer/active");
}
export function startTimer(ticketId: number) {
  return apiRequest<ActiveTimer>(`/tickets/${ticketId}/timer/start`, { method: "POST" });
}
export function stopTimer() {
  return apiRequest<TimeEntry | null>("/tickets/timer/stop", { method: "POST" });
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

// --- Reports ---
export function downloadOverviewXlsx(dateFrom?: string, dateTo?: string, organizationId?: number) {
  const query = new URLSearchParams();
  if (dateFrom) query.set("date_from", dateFrom);
  if (dateTo) query.set("date_to", dateTo);
  if (organizationId) query.set("organization_id", String(organizationId));
  return apiDownload(`/reports/overview.xlsx?${query}`, `otchet_${dateFrom ?? ""}_${dateTo ?? ""}.xlsx`);
}

export function getReportsOverview(filters: { date_from?: string; date_to?: string; organization_id?: number }) {
  return apiRequest<ReportsOverview>("/reports/overview", { query: filters });
}

// --- Automation rules ---
export function listAutomationRules() {
  return apiRequest<AutomationRule[]>("/automation-rules");
}
export function updateAutomationRule(id: number, payload: { threshold_days?: number; is_active?: boolean }) {
  return apiRequest<AutomationRule>(`/automation-rules/${id}`, { method: "PATCH", body: payload });
}

// --- Saved queue filters (ТЗ 8.1) ---
export interface SavedFilter {
  id: number;
  name: string;
  criteria: Record<string, string | number | undefined>;
}
export function listSavedFilters() {
  return apiRequest<SavedFilter[]>("/saved-filters");
}
export function createSavedFilter(name: string, criteria: Record<string, unknown>) {
  return apiRequest<SavedFilter>("/saved-filters", { method: "POST", body: { name, criteria } });
}
export function deleteSavedFilter(id: number) {
  return apiRequest<void>(`/saved-filters/${id}`, { method: "DELETE" });
}

// --- Ticket schedules (плановые заявки) ---
export interface TicketSchedule {
  id: number;
  name: string;
  organization_id: number;
  contact_id: number;
  category_id: number | null;
  assigned_engineer_id: number | null;
  subject: string;
  body: string | null;
  type: string;
  priority: Priority;
  cadence: "daily" | "weekly" | "monthly" | "quarterly";
  day_of_week: number | null;
  day_of_month: number | null;
  is_active: boolean;
  next_run_on: string;
}
export function listTicketSchedules() {
  return apiRequest<TicketSchedule[]>("/ticket-schedules");
}
export function createTicketSchedule(payload: Record<string, unknown>) {
  return apiRequest<TicketSchedule>("/ticket-schedules", { method: "POST", body: payload });
}
export function updateTicketSchedule(id: number, payload: Record<string, unknown>) {
  return apiRequest<TicketSchedule>(`/ticket-schedules/${id}`, { method: "PATCH", body: payload });
}
export function deleteTicketSchedule(id: number) {
  return apiRequest<void>(`/ticket-schedules/${id}`, { method: "DELETE" });
}
export function runTicketScheduleNow(id: number) {
  return apiRequest<TicketSchedule>(`/ticket-schedules/${id}/run-now`, { method: "POST" });
}

// --- Response templates (быстрые ответы, ТЗ 8.2) ---
export function listResponseTemplates(params: { category_id?: number; include_inactive?: boolean } = {}) {
  return apiRequest<ResponseTemplate[]>("/response-templates", {
    query: params as Record<string, string | number | boolean | undefined>,
  });
}
export function createResponseTemplate(payload: { name: string; body: string; category_id?: number | null }) {
  return apiRequest<ResponseTemplate>("/response-templates", { method: "POST", body: payload });
}
export function updateResponseTemplate(id: number, payload: Partial<ResponseTemplate>) {
  return apiRequest<ResponseTemplate>(`/response-templates/${id}`, { method: "PATCH", body: payload });
}
export function deleteResponseTemplate(id: number) {
  return apiRequest<void>(`/response-templates/${id}`, { method: "DELETE" });
}

// --- Related tickets (ТЗ 8.2) ---
export function listRelatedTickets(ticketId: number) {
  return apiRequest<Ticket[]>(`/tickets/${ticketId}/related`);
}

// --- Calls (телефония, раздел 2.4) ---
export function listCalls(params: { unhandled_only?: boolean; limit?: number; offset?: number } = {}) {
  return apiPage<Call>("/calls", params as Record<string, string | number | boolean | undefined>);
}
export function markCallHandled(id: number) {
  return apiRequest<Call>(`/calls/${id}/handled`, { method: "POST" });
}
export function createTicketFromCall(id: number, payload: { subject: string; contact_id?: number | null }) {
  return apiRequest<Ticket>(`/calls/${id}/ticket`, { method: "POST", body: payload });
}
export function listTicketCalls(ticketId: number) {
  return apiRequest<Call[]>(`/tickets/${ticketId}/calls`);
}

// --- Integration settings (Настройки → Каналы) ---
export function listIntegrationSettings() {
  return apiRequest<IntegrationSetting[]>("/settings/integrations");
}
export function updateIntegrationSetting(
  channel: string,
  payload: { is_enabled?: boolean; config?: Record<string, unknown>; secrets?: Record<string, string | null> }
) {
  return apiRequest<IntegrationSetting>(`/settings/integrations/${channel}`, { method: "PUT", body: payload });
}

// --- Мониторинг (Zabbix) ---
// Отдельный ресурс, а не канал: настройки лежат в конфиге канала «Портал»,
// но для интерфейса это деталь реализации.
export interface MonitoringSettings {
  is_enabled: boolean;
  auto_resolve: boolean;
  default_contact_id: number | null;
  field_map: Record<string, string>;
  webhook_secret_set: boolean;
  updated_at: string;
}
export function getMonitoringSettings() {
  return apiRequest<MonitoringSettings>("/settings/monitoring");
}
export function updateMonitoringSettings(payload: {
  is_enabled?: boolean;
  auto_resolve?: boolean;
  default_contact_id?: number | null;
  field_map?: Record<string, string>;
  // Ключ не передан — секрет не меняется; null — снять; строка — записать.
  webhook_secret?: string | null;
}) {
  return apiRequest<MonitoringSettings>("/settings/monitoring", { method: "PUT", body: payload });
}
export function listMonitoringAlerts(params: { unresolved_only?: boolean; limit?: number; offset?: number } = {}) {
  return apiPage<MonitoringAlert>("/monitoring/alerts", params as Record<string, string | number | undefined>);
}
export interface MonitoringAlert {
  id: number;
  external_id: string;
  source: string;
  severity: string | null;
  host: string | null;
  subject: string;
  organization_id: number | null;
  ticket_id: number | null;
  resolved_at: string | null;
  created_at: string;
}

// --- Отчёты клиентам (ТЗ 9.2): готовые снимки за период ---
export interface ClientReportSummary {
  id: number;
  organization_id: number;
  organization_name: string;
  period_start: string;
  period_end: string;
  period_title: string;
  tickets_count: number;
  hours: number;
  source: "manual" | "auto";
  generated_at: string;
  generated_by: string | null;
  sent_at: string | null;
}
export interface ClientReportDetail extends ClientReportSummary {
  data: ClientReportData;
}
export interface ClientReportData {
  organization: string;
  period: { date_from: string; date_to: string };
  totals: { tickets: number; resolved: number; hours: number };
  sla: {
    reaction_met_pct: number | null;
    resolution_met_pct: number | null;
    reaction_total: number;
    resolution_total: number;
    reaction_missed: number;
    resolution_missed: number;
  };
  by_channel: { channel: string; count: number }[];
  by_category: { category: string; count: number }[];
  package: Record<string, number | string>;
  tickets: {
    display_number: string;
    subject: string;
    channel: string;
    status: string;
    created_at: string;
    hours: number;
  }[];
}
export function listClientReports(params: { organization_id?: number; limit?: number; offset?: number } = {}) {
  return apiPage<ClientReportSummary>("/client-reports", params as Record<string, string | number | undefined>);
}
export function generateClientReport(payload: { organization_id: number; period_start: string; period_end: string }) {
  return apiRequest<ClientReportSummary>("/client-reports", { method: "POST", body: payload });
}
export function getStoredClientReport(id: number) {
  return apiRequest<ClientReportDetail>(`/client-reports/${id}`);
}
export function setClientReportSent(id: number, sent: boolean) {
  return apiRequest<ClientReportSummary>(`/client-reports/${id}/sent`, { method: "POST", body: { sent } });
}
export function downloadStoredClientReport(report: ClientReportSummary, format: "pdf" | "xlsx") {
  const name = `Отчёт ${report.organization_name} ${report.period_title}.${format}`;
  return apiDownload(`/client-reports/${report.id}/${format}`, name);
}
