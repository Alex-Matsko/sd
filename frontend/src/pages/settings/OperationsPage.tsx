import { useState } from "react";
import { Link } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDownload, apiPage, apiRequest } from "../../api/client";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { CHANNEL_LABELS, formatDateTime } from "../../lib/labels";
import type { Channel } from "../../api/types";

interface Pulse {
  component: string; state: string; last_error: string | null;
  started_at: string | null; succeeded_at: string | null; failed_at: string | null;
}
interface Job {
  id: number; kind: string; channel: Channel; state: string; attempts: number;
  last_error: string | null; ticket_id: number | null; created_at: string; available_at: string; summary: string; source_available: boolean;
}
interface SystemStatus { storage_free_bytes: number | null; workers: Pulse[]; queues: Record<string, Record<string, number>> }
const COMPONENTS: Record<string, string> = {
  watchdog: "Контроль фоновых процессов", storage: "Хранилище вложений", retention: "Очистка журнала",
  main: "Основной процесс", inbound: "Обработка входящих", outbound: "Отправка сообщений",
  email: "Приём почты", max: "Приём MAX", telegram: "Приём Telegram", sla: "Контроль SLA",
  automation: "Автоматизация", schedules: "Плановые заявки", client_reports: "Отчёты клиентам",
};
const STATES: Record<string, string> = {
  ok: "Работает", disabled: "Отключено", missing: "Не запущено", stale: "Нет сигнала", error: "Ошибка",
  pending: "В очереди", processing: "Обрабатывается", retry: "Ожидает повтора", failed: "Нужна проверка",
  sent: "Принято каналом", processed: "Обработано", discarded: "Пропущено",
};

export function OperationsPage() {
  const qc = useQueryClient();
  const [kind, setKind] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(true);
  const [page, setPage] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const status = useQuery({ queryKey: ["operations-status"], queryFn: () => apiRequest<SystemStatus>("/operations/status"), refetchInterval: 15_000 });
  const jobs = useQuery({ queryKey: ["operations-jobs", kind, errorsOnly, page],
    queryFn: () => apiPage<Job>("/operations/jobs", { kind, errors_only: errorsOnly, limit: 25, offset: page * 25 }),
    refetchInterval: 15_000, placeholderData: keepPreviousData });
  const action = useMutation({
    mutationFn: ({ id, operation, reason }: { id: number; operation: string; reason?: string }) =>
      apiRequest(`/operations/jobs/${id}/${operation}`, { method: "POST", body: reason ? { reason } : undefined }),
    onSuccess: () => { setActionError(null); qc.invalidateQueries({ queryKey: ["operations-jobs"] }); qc.invalidateQueries({ queryKey: ["operations-status"] }); },
    onError: (error) => setActionError(error.message),
  });
  return <div className="view">
    <div className="page-heading"><div><p className="eyebrow">Эксплуатация</p><h1 className="view-title">Состояние системы</h1>
      <p className="view-description">Фоновая обработка, очередь сообщений и события, которым нужна помощь.</p></div></div>
    {status.isLoading && <Loading />}
    {status.isError && <ErrorBanner message={status.error.message} />}
    {status.data && <>
      <div className="stat-grid operations-stats">
        {([['inbound', 'Входящие'], ['outbound', 'Исходящие']] as const).map(([queue, title]) => {
          const counts = status.data.queues[queue];
          return <div className="stat-card" key={queue}><span className="stat-value">{(counts.pending ?? 0) + (counts.processing ?? 0) + (counts.retry ?? 0)}</span>
            <span className="stat-label">{title}: в обработке</span><span className={(counts.failed ?? 0) ? "text-danger" : "muted"}>Нужна проверка: {counts.failed ?? 0}</span></div>;
        })}
      </div>
      <div className="panel"><div className="panel-head"><h2>Фоновая обработка</h2><span className="muted">Обновление каждые 15 секунд</span></div>
        <div className="worker-grid">{status.data.workers.map((row) => <div className="worker-card" key={row.component}>
          <strong>{COMPONENTS[row.component] ?? row.component}</strong>
          <span className={`worker-state worker-${row.state}`}>{STATES[row.state] ?? row.state}</span>
          <small className="muted">Успешная проверка: {formatDateTime(row.succeeded_at)}</small>
          {row.last_error && <small className="text-danger">{row.last_error}</small>}
        </div>)}</div>
      </div>
    </>}
    <div className="toolbar"><h2>Журнал каналов</h2><div className="spacer" />
      <select aria-label="Направление событий" value={kind} onChange={(e) => { setKind(e.target.value); setPage(0); }}>
        <option value="">Все направления</option><option value="inbound">Входящие</option><option value="outbound">Исходящие</option>
      </select>
      <label className="queue-scope"><input type="checkbox" checked={errorsOnly} onChange={(e) => { setErrorsOnly(e.target.checked); setPage(0); }} /> Только с ошибками</label>
    </div>
    {actionError && <ErrorBanner message={actionError} />}
    {jobs.isLoading && <Loading />}
    {jobs.isError && <ErrorBanner message={jobs.error.message} />}
    {jobs.data?.items.length === 0 && <EmptyState text={errorsOnly ? "Ошибок обработки нет" : "Событий пока нет"} />}
    {jobs.data && jobs.data.items.length > 0 && <>
      <div className="operations-jobs">{jobs.data.items.map((job) => <article className="panel operation-job" key={job.id}>
        <div className="panel-head"><strong>#{job.id} · {CHANNEL_LABELS[job.channel] ?? job.channel} · {job.kind === "inbound" ? "Входящее" : "Исходящее"}</strong>
          <span className={`worker-state ${["retry", "failed"].includes(job.state) ? "worker-error" : ""}`}>{STATES[job.state] ?? job.state}</span></div>
        {job.summary && <p>{job.summary}</p>}
        {job.last_error && <p className="text-danger">{job.last_error}</p>}
        <div className="operation-meta"><span className="muted">{formatDateTime(job.created_at)} · попыток: {job.attempts}</span>
          {job.state === "retry" && <span className="muted">Следующая: {formatDateTime(job.available_at)}</span>}
          {job.ticket_id && <Link to={`/tickets/${job.ticket_id}`}>Открыть заявку →</Link>}
        </div>
        <div className="operation-actions">
          {["retry", "failed"].includes(job.state) && <button className="btn btn-ghost" disabled={action.isPending} onClick={() => action.mutate({ id: job.id, operation: "retry" })}>Повторить обработку</button>}
          {job.source_available && <button className="btn-link" onClick={() => apiDownload(`/operations/jobs/${job.id}/source`, `event-${job.id}.${job.channel === "email" ? "eml" : "json"}`).catch((error: Error) => setActionError(error.message))}>Скачать исходное событие</button>}
          {["retry", "failed", "pending"].includes(job.state) && <button className="btn-link" disabled={action.isPending} onClick={() => {
            const reason = window.prompt("Событие останется в журнале, но больше не будет обрабатываться. Укажите причину пропуска (от 5 символов).");
            if (reason && reason.trim().length >= 5) action.mutate({ id: job.id, operation: "discard", reason: reason.trim() });
          }}>Пропустить с указанием причины</button>}
        </div>
      </article>)}</div>
      <div className="pagination"><span className="muted">{page * 25 + 1}–{Math.min((page + 1) * 25, jobs.data.total)} из {jobs.data.total}</span><div className="spacer" />
        <button className="btn btn-ghost" disabled={page === 0 || jobs.isPlaceholderData} onClick={() => setPage((p) => p - 1)}>← Назад</button>
        <button className="btn btn-ghost" disabled={(page + 1) * 25 >= jobs.data.total || jobs.isPlaceholderData} onClick={() => setPage((p) => p + 1)}>Вперёд →</button></div>
    </>}
  </div>;
}
