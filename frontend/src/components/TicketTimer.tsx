import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getActiveTimer, startTimer, stopTimer } from "../api/endpoints";
import type { TicketStatus } from "../api/types";
import { formatMinutes } from "../lib/labels";

function elapsedLabel(startedAt: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const hh = Math.floor(seconds / 3600);
  const mm = Math.floor((seconds % 3600) / 60);
  const ss = seconds % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return hh > 0 ? `${hh}:${pad(mm)}:${pad(ss)}` : `${pad(mm)}:${pad(ss)}`;
}

/** Starting work changes the ticket status and starts one personal timer.
 * Switching tickets banks the previous timer in its original ticket. */
export function TicketTimer({ ticketId, status }: { ticketId: number; status: TicketStatus }) {
  const qc = useQueryClient();
  const [now, setNow] = useState(() => Date.now());
  const [notice, setNotice] = useState<string | null>(null);
  const timerQuery = useQuery({ queryKey: ["active-timer"], queryFn: getActiveTimer, refetchInterval: 30_000 });
  const timer = timerQuery.data;
  const runningHere = Boolean(timer?.running && timer.ticket_id === ticketId);
  const runningElsewhere = Boolean(timer?.running && timer.ticket_id !== ticketId);
  const canStart = status !== "closed" && status !== "cancelled";

  useEffect(() => {
    if (!timer?.running) return;
    const handle = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, [timer?.running]);

  function refresh() {
    qc.invalidateQueries({ queryKey: ["active-timer"] });
    qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
    if (timer?.ticket_id && timer.ticket_id !== ticketId) qc.invalidateQueries({ queryKey: ["ticket", timer.ticket_id] });
    qc.invalidateQueries({ queryKey: ["tickets"] });
    qc.invalidateQueries({ queryKey: ["ticket-stats"] });
    qc.invalidateQueries({ queryKey: ["organization-usage"] });
  }
  const startMutation = useMutation({ mutationFn: () => startTimer(ticketId),
    onSuccess: () => { setNotice(null); stopMutation.reset(); refresh(); },
    onError: () => { refresh(); } });
  const stopMutation = useMutation({ mutationFn: stopTimer,
    onSuccess: entry => {
      startMutation.reset();
      setNotice(entry ? `Время учтено: ${formatMinutes(entry.duration_minutes)}` : "Таймер работал меньше минуты — время не списано");
      refresh();
    } });
  const pending = startMutation.isPending || stopMutation.isPending;
  const ready = timerQuery.isSuccess && !pending;
  const title = !canStart ? (status === "closed" ? "Заявка закрыта" : "Заявка отменена")
    : status === "resolved" ? "Работы завершены" : status === "waiting_customer" || status === "waiting_third_party" ? "Работа ожидает возобновления"
    : runningHere ? "Работа по заявке начата" : status === "in_progress" ? "Заявка в работе" : "Можно начать работу";
  const description = runningElsewhere && canStart ? `Таймер по ${timer?.display_number ?? "другой заявке"} остановится, время будет учтено в ней.`
    : !canStart ? "Новый таймер для этой заявки недоступен."
    : runningHere ? (status === "in_progress" ? "Время учитывается по этой заявке." : "Кнопка вернёт заявку в работу. Текущий таймер продолжит отсчёт.")
    : status === "resolved" ? "Возобновление вернёт заявку в работу и запустит таймер."
    : status === "in_progress" ? "Запустите таймер, чтобы учитывать время выполнения." : "Одно нажатие переведёт заявку в «В работе» и запустит таймер.";
  return <section className={`ticket-workbar ${runningHere ? "ticket-workbar-running" : ""}`} aria-label="Работа по заявке" aria-busy={pending}>
    <div className="ticket-workbar-summary"><span className="ticket-workbar-icon" aria-hidden="true"><svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="13" r="8" /><path d="M12 9v4l2.5 1.5M9 2h6M12 2v3" /></svg></span><div><strong>{title}</strong><p>{description}</p></div></div>
    <div className="ticket-workbar-actions">
      {runningHere && <span className="timer-elapsed mono" aria-label="Время работы">{elapsedLabel(timer!.started_at!, now)}</span>}
      {runningHere && <button type="button" className="btn btn-ghost" disabled={!ready} onClick={() => stopMutation.mutate()}>
        {stopMutation.isPending ? "Остановка…" : "Остановить таймер"}</button>}
      {canStart && (!runningHere || status !== "in_progress") && <button type="button" className="btn btn-primary ticket-start-work" disabled={!ready} onClick={() => startMutation.mutate()}>
          <svg width="16" height="16" viewBox="0 0 20 20" aria-hidden="true" fill="currentColor"><path d="M6 3.5v13L16 10z" /></svg>
          {startMutation.isPending ? "Запуск…" : status === "resolved" || status === "waiting_customer" || status === "waiting_third_party" ? "Возобновить работу" : "Начать работу"}
        </button>}
      {timerQuery.isPending && <span className="muted" role="status">Проверка таймера…</span>}
    </div>
    {notice && <p className="ticket-workbar-notice" role="status">{notice}</p>}
    {timerQuery.isError && <div className="ticket-workbar-error" role="alert">Не удалось проверить таймер. <button type="button" className="btn-link" onClick={() => timerQuery.refetch()}>Повторить</button></div>}
    {(startMutation.isError || stopMutation.isError) && <p className="ticket-workbar-error" role="alert">{(startMutation.error ?? stopMutation.error)?.message}</p>}
  </section>;
}
