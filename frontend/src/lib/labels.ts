import type {
  AssetType,
  Channel,
  ContractStatus,
  ImpactUrgencyLevel,
  MessageDirection,
  NotificationType,
  OrganizationStatus,
  Priority,
  SlaTimerState,
  TicketStatus,
  TicketType,
  UserRole,
} from "../api/types";

export const STATUS_LABELS: Record<TicketStatus, string> = {
  new: "Новая",
  assigned: "Назначена",
  in_progress: "В работе",
  waiting_customer: "Ждём клиента",
  waiting_third_party: "Ждём третью сторону",
  resolved: "Решена",
  closed: "Закрыта",
  cancelled: "Отменена",
};

// Mirrors backend ALLOWED_TRANSITIONS in app/services/tickets.py — keep in sync.
export const STATUS_TRANSITIONS: Record<TicketStatus, TicketStatus[]> = {
  new: ["assigned", "in_progress", "cancelled"],
  assigned: ["in_progress", "waiting_customer", "waiting_third_party", "cancelled"],
  in_progress: ["waiting_customer", "waiting_third_party", "resolved", "cancelled"],
  waiting_customer: ["in_progress", "resolved", "cancelled"],
  waiting_third_party: ["in_progress", "resolved", "cancelled"],
  resolved: ["closed", "in_progress"],
  closed: [],
  cancelled: [],
};

export const CHANNEL_LABELS: Record<Channel, string> = {
  telegram: "Telegram",
  max: "MAX",
  email: "Email",
  phone: "Телефон",
  portal: "Портал",
  whatsapp: "WhatsApp",
};

export const PRIORITY_LABELS: Record<Priority, string> = {
  P1: "P1 — critical",
  P2: "P2 — high",
  P3: "P3 — medium",
  P4: "P4 — low",
};

export const IMPACT_URGENCY_LABELS: Record<ImpactUrgencyLevel, string> = {
  high: "Высокий",
  medium: "Средний",
  low: "Низкий",
};

export const TICKET_TYPE_LABELS: Record<TicketType, string> = {
  incident: "Инцидент",
  service_request: "Запрос на обслуживание",
};

export const MESSAGE_DIRECTION_LABELS: Record<MessageDirection, string> = {
  inbound: "От клиента",
  outbound: "Клиенту",
  internal_note: "Внутренняя заметка",
};

export const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  server: "Сервер",
  workstation: "Рабочая станция",
  "1c_database": "База 1С",
  rented_resource: "Арендованный ресурс",
  network_device: "Сетевое устройство",
};

export const CONTRACT_STATUS_LABELS: Record<ContractStatus, string> = {
  draft: "Черновик",
  active: "Активен",
  suspended: "Приостановлен",
  expired: "Истёк",
};

export const ORGANIZATION_STATUS_LABELS: Record<OrganizationStatus, string> = {
  active: "Активна",
  suspended: "Приостановлена",
  archived: "В архиве",
};

export const USER_ROLE_LABELS: Record<UserRole, string> = {
  engineer: "Инженер",
  dispatcher: "Диспетчер",
  manager: "Менеджер",
  admin: "Администратор",
};

export const SLA_STATE_LABELS: Record<SlaTimerState, string> = {
  no_rule: "Без SLA",
  ok: "В норме",
  warning: "Риск (75%+)",
  breached: "Нарушен",
  met: "Выполнен",
  paused: "На паузе",
};

export const NOTIFICATION_TYPE_LABELS: Record<NotificationType, string> = {
  sla_reaction_warning: "Риск по реакции",
  sla_reaction_breach: "Нарушение реакции",
  sla_resolution_warning: "Риск по решению",
  sla_resolution_breach: "Нарушение решения",
};

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function formatMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m} мин`;
  if (m === 0) return `${h} ч`;
  return `${h} ч ${m} мин`;
}

export function displayTicketId(displayNumber: string): string {
  return displayNumber;
}
