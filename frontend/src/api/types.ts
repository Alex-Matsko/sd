export type UserRole = "engineer" | "dispatcher" | "manager" | "admin";

export type TicketType = "incident" | "service_request";

export type TicketStatus =
  | "new"
  | "assigned"
  | "in_progress"
  | "waiting_customer"
  | "waiting_third_party"
  | "resolved"
  | "closed"
  | "cancelled";

export type Channel = "telegram" | "max" | "email" | "phone" | "portal" | "whatsapp";

export type MessageDirection = "inbound" | "outbound" | "internal_note";

export type Priority = "P1" | "P2" | "P3" | "P4";

export type ImpactUrgencyLevel = "high" | "medium" | "low";

export type AssetType = "server" | "workstation" | "1c_database" | "rented_resource" | "network_device";

export type ContractStatus = "draft" | "active" | "suspended" | "expired";

export type RoutingRuleType = "organization_to_engineer" | "category_to_team";

export type OrganizationStatus = "active" | "suspended" | "archived";

export type SlaTimerState = "no_rule" | "ok" | "warning" | "breached" | "met" | "paused";

export type NotificationType =
  | "sla_reaction_warning"
  | "sla_reaction_breach"
  | "sla_resolution_warning"
  | "sla_resolution_breach";

export interface User {
  id: number;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  telegram_id: string | null;
}

export interface OrganizationEmailDomain {
  id: number;
  domain: string;
}

export interface Organization {
  id: number;
  name: string;
  legal_name: string | null;
  status: OrganizationStatus;
  account_manager_id: number | null;
  email_domains: OrganizationEmailDomain[];
}

export interface ContactEmail {
  id: number;
  email: string;
  is_primary: boolean;
}

export interface ContactPhone {
  id: number;
  phone: string;
  is_primary: boolean;
}

export interface Contact {
  id: number;
  organization_id: number;
  full_name: string;
  position: string | null;
  telegram_id: string | null;
  max_id: string | null;
  is_vip: boolean;
  can_view_org_tickets: boolean;
  is_confirmed: boolean;
  emails: ContactEmail[];
  phones: ContactPhone[];
}

export interface TariffSlaRule {
  id: number;
  priority: Priority;
  reaction_time_minutes: number;
  resolution_time_minutes: number;
}

export interface Tariff {
  id: number;
  code: string;
  name: string;
  description: string | null;
  business_calendar_id: number;
  sla_rules: TariffSlaRule[];
}

export interface Contract {
  id: number;
  organization_id: number;
  number: string;
  start_date: string;
  end_date: string | null;
  tariff_id: number;
  included_hours_per_month: number;
  overage_rate_per_hour: number;
  status: ContractStatus;
}

export interface Category {
  id: number;
  name: string;
  parent_id: number | null;
}

export interface Asset {
  id: number;
  organization_id: number;
  type: AssetType;
  name: string;
  description: string | null;
}

export interface Team {
  id: number;
  name: string;
  lead_user_id: number | null;
  member_user_ids: number[];
}

export interface RoutingRule {
  id: number;
  order: number;
  rule_type: RoutingRuleType;
  is_active: boolean;
  organization_id: number | null;
  category_id: number | null;
  target_engineer_id: number | null;
  target_team_id: number | null;
}

export interface CalendarWindow {
  id: number;
  weekday: number;
  start_time: string;
  end_time: string;
}

export interface BusinessCalendar {
  id: number;
  name: string;
  timezone: string;
  is_24x7: boolean;
  observes_holidays: boolean;
  windows: CalendarWindow[];
}

export interface ImpactUrgencyRule {
  id: number;
  impact: ImpactUrgencyLevel;
  urgency: ImpactUrgencyLevel;
  priority: Priority;
}

export interface SlaTimerView {
  due_at: string | null;
  met: boolean | null;
  state: SlaTimerState;
  progress_pct: number | null;
}

export interface TicketSlaView {
  reaction: SlaTimerView;
  resolution: SlaTimerView;
  paused: boolean;
}

export interface Ticket {
  id: number;
  number: number;
  display_number: string;
  type: TicketType;
  channel: Channel;
  subject: string;
  organization_id: number;
  contact_id: number;
  contract_id: number | null;
  tariff_id: number;
  has_no_active_contract: boolean;
  asset_id: number | null;
  category_id: number | null;
  impact: ImpactUrgencyLevel | null;
  urgency: ImpactUrgencyLevel | null;
  priority: Priority;
  priority_override_reason: string | null;
  status: TicketStatus;
  assigned_engineer_id: number | null;
  team_id: number | null;
  parent_ticket_id: number | null;
  sla_reaction_due_at: string | null;
  sla_resolution_due_at: string | null;
  sla_paused_at: string | null;
  first_response_at: string | null;
  sla_reaction_met: boolean | null;
  resolved_at: string | null;
  sla_resolution_met: boolean | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  sla: TicketSlaView | null;
}

export interface Notification {
  id: number;
  ticket_id: number | null;
  type: NotificationType;
  title: string;
  created_at: string;
  read_at: string | null;
}

export interface IntegrationSetting {
  channel: Channel;
  is_enabled: boolean;
  config: Record<string, unknown>;
  secret_keys_set: string[];
  updated_at: string;
}

export interface EmailChannelConfig {
  imap_host?: string;
  imap_port?: number;
  imap_use_ssl?: boolean;
  imap_username?: string;
  imap_folder?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_use_tls?: boolean;
  smtp_username?: string;
  from_address?: string;
  from_display_name?: string;
  poll_interval_seconds?: number;
}

export interface MaxChannelConfig {
  base_url?: string;
  poll_timeout_seconds?: number;
}

export interface Attachment {
  id: number;
  filename: string;
  size_bytes: number;
  mime_type: string | null;
  created_at: string;
}

export interface Message {
  id: number;
  ticket_id: number;
  direction: MessageDirection;
  channel: Channel;
  author_user_id: number | null;
  author_contact_id: number | null;
  body: string;
  created_at: string;
  attachments: Attachment[];
}

export interface TimeEntry {
  id: number;
  ticket_id: number;
  engineer_id: number;
  entry_date: string;
  duration_minutes: number;
  comment: string | null;
  is_billable: boolean;
  billed_package_minutes: number;
  billed_overage_minutes: number;
}

export interface AuditLogEntry {
  id: number;
  entity_type: string;
  entity_id: number;
  action: string;
  user_id: number | null;
  changes: Record<string, unknown> | null;
  created_at: string;
}

export interface OrganizationUsage {
  organization_id: number;
  year: number;
  month: number;
  package_total_minutes: number;
  package_used_minutes: number;
  package_remaining_minutes: number;
  overage_minutes: number;
  overage_cost: number;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}
