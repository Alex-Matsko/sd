import { getAccessToken } from "./client";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";

export interface RealtimeNotification {
  user_id: number;
  type: string;
  title: string;
  ticket_id: number | null;
}

/** Live notification feed (ТЗ р. 8).
 *
 * Reconnects with a backoff, and the caller keeps its periodic polling as a
 * fallback - so if websockets are blocked by a proxy the bell still updates
 * on the old 30-second cadence instead of going silent. */
export function connectNotifications(onMessage: (n: RealtimeNotification) => void): () => void {
  let socket: WebSocket | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let closed = false;

  function open() {
    const token = getAccessToken();
    if (!token || closed) return;

    // The browser WebSocket API can't set headers, so the token goes in the
    // query string - matches what the server expects.
    // Адрес API бывает относительным (/api — через тот же домен, что и
    // панель): WebSocket принимает только полный адрес.
    const base = new URL(API_BASE_URL, window.location.origin).href.replace(/\/$/, "");
    const url = `${base.replace(/^http/, "ws")}/ws/notifications?token=${encodeURIComponent(token)}`;
    socket = new WebSocket(url);

    socket.onopen = () => {
      attempt = 0;
    };
    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        // A frame we can't parse isn't worth tearing the socket down for.
      }
    };
    socket.onclose = (event) => {
      socket = null;
      if (closed) return;
      // 1008 means the server refused the token. Usually that's simply an
      // expired access token, which the REST layer refreshes on its next
      // 401 - so this retries, just slowly, instead of giving up (which
      // would leave the feed dead until a page reload) or hot-looping.
      if (event.code === 1008) {
        retryTimer = setTimeout(open, 60_000);
        return;
      }
      attempt += 1;
      const delay = Math.min(1000 * 2 ** attempt, 30_000);
      retryTimer = setTimeout(open, delay);
    };
  }

  open();

  return () => {
    closed = true;
    if (retryTimer) clearTimeout(retryTimer);
    socket?.close();
  };
}
