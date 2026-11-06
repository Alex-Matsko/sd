import { useRef } from "react";

function newId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

/** Keep the same identity after a lost HTTP response, change it when the draft changes. */
export function useDraftRequestId(key: string) {
  const draft = useRef<{ key: string; id: string } | null>(null);
  if (!draft.current || draft.current.key !== key) draft.current = { key, id: newId() };
  return draft.current.id;
}
