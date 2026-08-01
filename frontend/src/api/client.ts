const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";

let accessToken: string | null = localStorage.getItem("sd_access_token");
let refreshToken: string | null = localStorage.getItem("sd_refresh_token");

export function setTokens(access: string | null, refresh: string | null) {
  accessToken = access;
  refreshToken = refresh;
  if (access) localStorage.setItem("sd_access_token", access);
  else localStorage.removeItem("sd_access_token");
  if (refresh) localStorage.setItem("sd_refresh_token", refresh);
  else localStorage.removeItem("sd_refresh_token");
}

export function getAccessToken() {
  return accessToken;
}

export function getRefreshToken() {
  return refreshToken;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let refreshPromise: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshToken) return false;
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = await res.json();
        setTokens(data.access_token, data.refresh_token);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}, retry = true): Promise<T> {
  const url = new URL(`${API_BASE_URL}${path}`);
  if (options.query) {
    for (const [key, value] of Object.entries(options.query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  const res = await fetch(url.toString(), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (res.status === 401 && retry) {
    const refreshed = await tryRefresh();
    if (refreshed) return apiRequest<T>(path, options, false);
    setTokens(null, null);
    throw new ApiError(401, "Сессия истекла, войдите снова");
  }

  if (!res.ok) {
    let message = `Ошибка запроса (${res.status})`;
    try {
      const data = await res.json();
      message = data.detail ?? message;
    } catch {
      // ignore body parse failure
    }
    throw new ApiError(res.status, typeof message === "string" ? message : JSON.stringify(message));
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

/** Shared auth/refresh handling for the non-JSON calls below (file upload and
 * download), which can't go through `apiRequest` - it forces a JSON
 * Content-Type and parses every response as JSON. */
async function authorizedFetch(path: string, init: RequestInit, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (res.status === 401 && retry) {
    const refreshed = await tryRefresh();
    if (refreshed) return authorizedFetch(path, init, false);
    setTokens(null, null);
    throw new ApiError(401, "Сессия истекла, войдите снова");
  }
  if (!res.ok) {
    let message = `Ошибка запроса (${res.status})`;
    try {
      const data = await res.json();
      message = data.detail ?? message;
    } catch {
      // ignore body parse failure
    }
    throw new ApiError(res.status, typeof message === "string" ? message : JSON.stringify(message));
  }
  return res;
}

export interface Page<T> {
  items: T[];
  total: number;
}

/** GET for paged endpoints: the body stays a plain array, the full match
 * count comes back in `X-Total-Count` (see the tickets router). */
export async function apiPage<T>(
  path: string,
  query: Record<string, string | number | boolean | undefined | null> = {}
): Promise<Page<T>> {
  const url = new URL(`${API_BASE_URL}${path}`);
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  const res = await authorizedFetch(url.pathname + url.search, { method: "GET" });
  const items = (await res.json()) as T[];
  const header = res.headers.get("X-Total-Count");
  return { items, total: header === null ? items.length : Number(header) };
}

export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  // Content-Type is deliberately left unset: the browser adds it together
  // with the multipart boundary, which we can't compute here.
  const res = await authorizedFetch(path, { method: "POST", body: form });
  return res.json();
}

/** Fetches a file through the API (so the Authorization header is sent - a
 * plain <a href> can't carry it) and hands it to the browser as a download. */
export async function apiDownload(path: string, filename: string): Promise<void> {
  const res = await authorizedFetch(path, { method: "GET" });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
