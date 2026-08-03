import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getActiveTimer, startTimer, stopTimer } from "../api/endpoints";
import { formatMinutes } from "../lib/labels";

function elapsedLabel(startedAt: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const hh = Math.floor(seconds / 3600);
  const mm = Math.floor((seconds % 3600) / 60);
  const ss = seconds % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return hh > 0 ? `${hh}:${pad(mm)}:${pad(ss)}` : `${pad(mm)}:${pad(ss)}`;
}

/** Кнопка «начать работу» на карточке заявки (ТЗ 8.2).
 *
 *  Таймер один на сотрудника, а не на заявку: инженер физически не работает
 *  над двумя заявками одновременно, и запуск второго таймера на бэкенде
 *  дописывает время в первую заявку. Поэтому здесь обязательно показывать,
 *  что таймер занят другой заявкой, — иначе списание уедет не туда молча. */
export function TicketTimer({ ticketId }: { ticketId: number }) {
  const qc = useQueryClient();
  const [now, setNow] = useState(() => Date.now());
  const [notice, setNotice] = useState<string | null>(null);

  const timerQuery = useQuery({
    queryKey: ["active-timer"],
    queryFn: getActiveTimer,
    // Таймер мог быть запущен в другой вкладке — иначе тут будет висеть
    // «остановлен», пока время капает.
    refetchInterval: 30_000,
  });
  const timer = timerQuery.data;
  const runningHere = timer?.running && timer.ticket_id === ticketId;
  const runningElsewhere = timer?.running && timer.ticket_id !== ticketId;

  useEffect(() => {
    if (!timer?.running) return;
    const handle = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, [timer?.running]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["active-timer"] });
    qc.invalidateQueries({ queryKey: ["ticket", ticketId, "time"] });
    qc.invalidateQueries({ queryKey: ["organization-usage"] });
  };

  const startMutation = useMutation({
    mutationFn: () => startTimer(ticketId),
    onSuccess: () => {
      setNotice(null);
      refresh();
    },
  });

  const stopMutation = useMutation({
    mutationFn: stopTimer,
    onSuccess: (entry) => {
      // null означает, что таймер проработал меньше минуты и запись не создана:
      // это почти всегда случайный клик, и молчаливое «ничего не произошло»
      // выглядело бы как поломка.
      setNotice(
        entry
          ? `Списано ${formatMinutes(entry.duration_minutes)}`
          : "Таймер работал меньше минуты — время не списано"
      );
      refresh();
    },
  });

  const pending = startMutation.isPending || stopMutation.isPending;

  return (
    <div className="ticket-timer">
      {runningHere && <span className="timer-elapsed mono">{elapsedLabel(timer!.started_at!, now)}</span>}
      {runningElsewhere && (
        <span className="muted">Таймер идёт по заявке {timer!.display_number}</span>
      )}
      {timer?.running ? (
        <button className="btn btn-ghost" disabled={pending} onClick={() => stopMutation.mutate()}>
          {runningHere ? "Остановить" : "Остановить и списать туда"}
        </button>
      ) : (
        <button className="btn btn-ghost" disabled={pending} onClick={() => startMutation.mutate()}>
          Начать работу
        </button>
      )}
      {notice && <span className="muted">{notice}</span>}
    </div>
  );
}
