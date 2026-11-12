import type { AttachmentPreviewData } from "../lib/attachmentPreview";
import type { MessageBlock, MessageUploadBlock } from "../api/types";
/** Client-portal HTTP layer.
 *
 * Deliberately separate from `api/client.ts`: the portal stores its own token
 * under its own key, so a client session and a staff session can coexist in
 * one browser without either overwriting the other - and a bug in one can't
 * hand its token to the other. */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/+$/, "");
const TOKEN_KEY = "sd_portal_token";

export function getPortalToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setPortalToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else {
    localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new Event("sd:portal-session-ended"));
  }
}

export class PortalError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const form = options.body instanceof FormData;
  const headers: Record<string, string> = form ? {} : { "Content-Type": "application/json" };
  const token = getPortalToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE_URL}/portal${path}`, {
    method: options.method ?? "GET",
    headers,
    body: form ? options.body as FormData : options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (res.status === 401) {
    setPortalToken(null);
    throw new PortalError(401, "Сессия истекла, войдите снова");
  }
  if (!res.ok) {
    let message = `Ошибка запроса (${res.status})`;
    try {
      const data = await res.json();
      message = typeof data.detail === "string" ? data.detail : message;
    } catch {
      // ignore body parse failure
    }
    throw new PortalError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface PortalMe {
  contact_id: number;
  full_name: string;
  organization: string;
  can_view_org_tickets: boolean;
}

export interface PortalTicket {
  planned_due_at: string | null;
  estimated_minutes: number | null;
  id: number;
  display_number: string;
  subject: string;
  status: string;
  priority: string;
  created_at: string;
  resolved_at: string | null;
  closed_at: string | null;
  csat_rating: number | null;
  assigned_engineer_name: string | null;
}

export interface PortalMessage {
  content_blocks: MessageBlock[] | null;
  id: number;
  body: string;
  is_from_support: boolean;
  created_at: string;
  attachments: PortalAttachment[];
}

export interface PortalTicketDetail extends PortalTicket {
  messages: PortalMessage[];
}

export interface PortalUsage {
  has_contract: boolean;
  package_total_hours?: number;
  package_used_hours?: number;
  package_remaining_hours?: number;
  overage_hours?: number;
}

export async function portalLogin(email: string, password: string) {
  const data = await request<{ access_token: string }>("/auth/login", {
    method: "POST",
    body: { email, password },
  });
  setPortalToken(data.access_token);
  return data;
}

export function requestMagicLink(email: string) {
  return request<{ sent: boolean }>("/auth/magic-link", { method: "POST", body: { email } });
}

export async function consumeMagicLink(token: string) {
  const data = await request<{ access_token: string }>(
    `/auth/magic-link/consume?token=${encodeURIComponent(token)}`,
    { method: "POST" }
  );
  setPortalToken(data.access_token);
  return data;
}

export interface PortalAttachment {
  mime_type: string | null;
  id: number;
  filename: string;
  size_bytes: number;
}

export interface PortalTicketUpdate {
  ticket_id: number;
  display_number: string;
  subject: string;
  status: string;
  new_messages: number;
  status_changed: boolean;
  at: string;
}

export interface PortalUpdates {
  total_new_messages: number;
  tickets: PortalTicketUpdate[];
}

export interface TicketFilters {
  q?: string;
  open_only?: boolean;
  status_filter?: string;
}

export const fetchPortalMe = () => request<PortalMe>("/me");

export const listPortalTickets = (filters: TicketFilters = {}) => {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.open_only) params.set("open_only", "true");
  if (filters.status_filter) params.set("status_filter", filters.status_filter);
  const query = params.toString();
  return request<PortalTicket[]>(`/tickets${query ? `?${query}` : ""}`);
};

export const fetchPortalUpdates = () => request<PortalUpdates>("/updates");
export const markPortalUpdatesSeen = () => request<void>("/updates/seen", { method: "POST" });

export const changePortalPassword = (current_password: string, new_password: string) =>
  request<void>("/me/password", { method: "POST", body: { current_password, new_password } });

/** Файл к своему сообщению: скриншот — самое частое, что нужно приложить. */
export async function uploadPortalAttachment(ticketId: number, messageId: number, file: File) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE_URL}/portal/tickets/${ticketId}/messages/${messageId}/attachments`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getPortalToken()}` },
    body: form,
  });
  if (res.status === 401) {
    setPortalToken(null);
    throw new PortalError(401, "Сессия истекла, войдите снова");
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Не удалось приложить файл");
  return (await res.json()) as PortalAttachment;
}

/** Скачивание идёт через fetch с токеном: обычная ссылка ушла бы без него. */
export async function downloadPortalFile(path: string, filename: string) {
  const res = await fetch(`${API_BASE_URL}/portal${path}`, {
    headers: { Authorization: `Bearer ${getPortalToken()}` },
  });
  if (res.status === 401) {
    setPortalToken(null);
    throw new PortalError(401, "Сессия истекла, войдите снова");
  }
  if (!res.ok) throw new Error("Не удалось скачать файл");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
export const getPortalTicket = (id: number) => request<PortalTicketDetail>(`/tickets/${id}`);
export const fetchPortalUsage = () => request<PortalUsage>("/usage");

export const createPortalTicket = (payload: { subject: string; body: string }) =>
  request<PortalTicket>("/tickets", { method: "POST", body: payload });

export function replyToPortalTicket(id: number, body: string, files: File[] = [], requestId?: string, blocks?: MessageUploadBlock[]) {
  const form = new FormData();
  form.append("body", body);
  if (blocks) form.append("content_blocks", JSON.stringify(blocks));
  if (requestId) form.append("request_id", requestId);
  files.forEach((file) => form.append("files", file));
  return request<PortalMessage>(`/tickets/${id}/messages/send`, { method: "POST", body: form });
}

export const downloadMyReport = (year: number, month: number) =>
  downloadPortalFile(`/reports/${year}/${month}.pdf`, `Отчёт ${month.toString().padStart(2, "0")}.${year}.pdf`);

export const ratePortalTicket = (id: number, rating: number) =>
  request<PortalTicket>(`/tickets/${id}/rating`, { method: "POST", body: { rating } });

export interface PortalProjectApproval {
  id: number; project_id: number; round: number; state: 'pending' | 'approved' | 'rejected' | 'superseded';
  snapshot: import('../api/work').PlanSnapshot; comment: string; requested_at: string; decided_at: string | null;
  project_version: number; project_status: import('../api/work').ProjectStatus; can_decide: boolean;
}
export const listPortalProjectApprovals = () => request<PortalProjectApproval[]>('/project-approvals');
export const decidePortalProjectApproval = (approval: PortalProjectApproval, decision: 'approved' | 'rejected', comment: string) =>
  request<PortalProjectApproval>(`/project-approvals/${approval.id}/decision`, {method: 'POST', body: {version: approval.project_version, decision, comment}});

export async function portalFileBlob(path: string): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/portal${path}`, { headers: { Authorization: `Bearer ${getPortalToken()}` } });
  if (res.status === 401) { setPortalToken(null); throw new PortalError(401, "Сессия истекла, войдите снова"); }
  if (!res.ok) throw new Error("Не удалось открыть скриншот");
  return res.blob();
}

export const portalAttachmentPreview = (path: string, sheet: number) => request<AttachmentPreviewData>(`${path}/preview?sheet=${sheet}`);
