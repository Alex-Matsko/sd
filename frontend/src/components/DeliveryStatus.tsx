import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import type { Delivery } from "../api/types";
import { ErrorBanner } from "./ui";
import { formatDateTime } from "../lib/labels";

const LABELS: Record<string, string> = {
  pending: "В очереди отправки", processing: "Отправляется", retry: "Ожидает повторной отправки",
  failed: "Не отправлено", sent: "Принято каналом", discarded: "Отправка отменена",
};

export function DeliveryStatus({ ticketId, messageId, delivery }: { ticketId: number; messageId: number; delivery: Delivery }) {
  const qc = useQueryClient();
  const retry = useMutation({
    mutationFn: () => apiRequest(`/tickets/${ticketId}/messages/${messageId}/delivery/retry`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ticket", ticketId, "messages"] }),
  });
  const problem = delivery.state === "retry" || delivery.state === "failed";
  return <div className={`delivery-state ${problem ? "delivery-problem" : ""}`} role="status">
    <span>{LABELS[delivery.state] ?? delivery.state}</span>
    {delivery.state === "sent" && <span className="muted" title="Канал подтвердил приём. Это не подтверждение прочтения клиентом.">{formatDateTime(delivery.completed_at)}</span>}
    {problem && <>
      <span>{delivery.last_error}</span>
      <span className="muted">Попыток: {delivery.attempts}{delivery.state === "retry" ? ` · следующая ${formatDateTime(delivery.available_at)}` : ""}</span>
      <button className="btn-link" disabled={retry.isPending} onClick={() => retry.mutate()}>Повторить отправку</button>
    </>}
    {retry.isError && <ErrorBanner message={retry.error.message} />}
  </div>;
}
