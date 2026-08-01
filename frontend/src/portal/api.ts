/** Client-portal HTTP layer.
 *
 * Deliberately separate from `api/client.ts`: the portal stores its own token
 * under its own key, so a client session and a staff session can coexist in
 * one browser without either overwriting the other - and a bug in one can't
 * hand its token to the other. */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";
const TOKEN_KEY = "sd_portal_token";

export function getPortalToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setPortalToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class PortalError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getPortalToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE_URL}/portal${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
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
  id: number;
  display_number: string;
  subject: string;
  status: string;
  priority: string;
  created_at: string;
  resolved_at: string | null;
  closed_at: string | null;
  csat_rating: number | null;
}

export interface PortalMessage {
  id: number;
  body: string;
  is_from_support: boolean;
  created_at: string;
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

export const fetchPortalMe = () => request<PortalMe>("/me");
export const listPortalTickets = () => request<PortalTicket[]>("/tickets");
export const getPortalTicket = (id: number) => request<PortalTicketDetail>(`/tickets/${id}`);
export const fetchPortalUsage = () => request<PortalUsage>("/usage");

export const createPortalTicket = (payload: { subject: string; body: string }) =>
  request<PortalTicket>("/tickets", { method: "POST", body: payload });

export const replyToPortalTicket = (id: number, body: string) =>
  request<PortalMessage>(`/tickets/${id}/messages`, { method: "POST", body: { body } });

export const ratePortalTicket = (id: number, rating: number) =>
  request<PortalTicket>(`/tickets/${id}/rating`, { method: "POST", body: { rating } });
