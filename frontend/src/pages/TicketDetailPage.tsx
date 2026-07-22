import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createMessage,
  createTimeEntry,
  getOrganizationUsage,
  getTicket,
  getTicketHistory,
  listMessages,
  listOrganizations,
  listTeams,
  listTimeEntries,
  listUsers,
  updateTicket,
} from "../api/endpoints";
import { ErrorBanner, Loading, PriorityTag, StatusTag, ChannelTag, WhoMini } from "../components/ui";
import {
  CHANNEL_LABELS,
  MESSAGE_DIRECTION_LABELS,
  STATUS_LABELS,
  STATUS_TRANSITIONS,
  formatDateTime,
  formatMinutes,
} from "../lib/labels";
import type { MessageDirection, TicketStatus } from "../api/types";

export function TicketDetailPage() {
  const { ticketId } = useParams();
  const id = Number(ticketId);
  const qc = useQueryClient();
  const [replyBody, setReplyBody] = useState("");
  const [replyDirection, setReplyDirection] = useState<MessageDirection>("outbound");
  const [timeMinutes, setTimeMinutes] = useState(30);
  const [timeComment, setTimeComment] = useState("");

  const ticketQuery = useQuery({ queryKey: ["ticket", id], queryFn: () => getTicket(id), enabled: Number.isFinite(id) });
  const messagesQuery = useQuery({ queryKey: ["ticket", id, "messages"], queryFn: () => listMessages(id), enabled: Number.isFinite(id) });
  const timeEntriesQuery = useQuery({ queryKey: ["ticket", id, "time"], queryFn: () => listTimeEntries(id), enabled: Number.isFinite(id) });
  const historyQuery = useQuery({ queryKey: ["ticket", id, "history"], queryFn: () => getTicketHistory(id), enabled: Number.isFinite(id) });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const teamsQuery = useQuery({ queryKey: ["teams"], queryFn: listTeams });
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });

  const ticket = ticketQuery.data;

  const usageQuery = useQuery({
    queryKey: ["organization-usage", ticket?.organization_id],
    queryFn: () => getOrganizationUsage(ticket!.organization_id),
    enabled: !!ticket && !ticket.has_no_active_contract,
    retry: false,
  });

  const updateMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => updateTicket(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ticket", id] }),
  });

  const messageMutation = useMutation({
    mutationFn: () => createMessage(id, { direction: replyDirection, body: replyBody.trim() }),
    onSuccess: () => {
      setReplyBody("");
      qc.invalidateQueries({ queryKey: ["ticket", id, "messages"] });
      qc.invalidateQueries({ queryKey: ["ticket", id] });
    },
  });

  const timeMutation = useMutation({
    mutationFn: () =>
      createTimeEntry(id, {
        entry_date: new Date().toISOString().slice(0, 10),
        duration_minutes: timeMinutes,
        comment: timeComment.trim() || null,
      }),
    onSuccess: () => {
      setTimeComment("");
      qc.invalidateQueries({ queryKey: ["ticket", id, "time"] });
      qc.invalidateQueries({ queryKey: ["organization-usage"] });
    },
  });

  if (ticketQuery.isLoading) return <div className="view"><Loading /></div>;
  if (ticketQuery.isError || !ticket) return <div className="view"><ErrorBanner message={(ticketQuery.error as Error)?.message ?? "Заявка не найдена"} /></div>;

  const org = (orgsQuery.data ?? []).find((o) => o.id === ticket.organization_id);
  const assignee = (usersQuery.data ?? []).find((u) => u.id === ticket.assigned_engineer_id);
  const availableTransitions = STATUS_TRANSITIONS[ticket.status] ?? [];

  return (
    <div className="view ticket-detail">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          {ticket.display_number} — {ticket.subject}
        </h1>
        <div className="spacer" />
        <PriorityTag priority={ticket.priority} />
        <StatusTag status={ticket.status} />
      </div>

      <div className="ticket-layout">
        <div className="ticket-main">
          <div className="panel">
            <div className="panel-head">
              <h2>Переписка</h2>
            </div>
            <div className="message-thread">
              {(messagesQuery.data ?? []).map((m) => (
                <div key={m.id} className={`message message-${m.direction}`}>
                  <div className="message-head">
                    <span className="message-direction">{MESSAGE_DIRECTION_LABELS[m.direction]}</span>
                    <span className="muted">{CHANNEL_LABELS[m.channel]}</span>
                    <span className="spacer" />
                    <span className="muted">{formatDateTime(m.created_at)}</span>
                  </div>
                  <div className="message-body">{m.body}</div>
                </div>
              ))}
              {messagesQuery.isSuccess && (messagesQuery.data ?? []).length === 0 && <p className="muted">Сообщений пока нет</p>}
            </div>

            <div className="reply-box">
              <div className="form-row-inline">
                <label>
                  <input type="radio" checked={replyDirection === "outbound"} onChange={() => setReplyDirection("outbound")} /> Ответ клиенту
                </label>
                <label>
                  <input type="radio" checked={replyDirection === "internal_note"} onChange={() => setReplyDirection("internal_note")} /> Внутренняя заметка
                </label>
              </div>
              <textarea rows={3} value={replyBody} onChange={(e) => setReplyBody(e.target.value)} placeholder="Введите текст сообщения…" />
              {messageMutation.isError && <ErrorBanner message={(messageMutation.error as Error).message} />}
              <div className="modal-foot" style={{ padding: 0, borderTop: "none" }}>
                <button
                  className="btn btn-primary"
                  disabled={!replyBody.trim() || messageMutation.isPending}
                  onClick={() => messageMutation.mutate()}
                >
                  Отправить
                </button>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Учёт времени</h2>
            </div>
            <div className="time-entries">
              {(timeEntriesQuery.data ?? []).map((entry) => (
                <div className="time-entry-row" key={entry.id}>
                  <span className="mono">{formatMinutes(entry.duration_minutes)}</span>
                  <span className="muted">{entry.comment ?? "—"}</span>
                  <span className="muted">{formatDateTime(entry.entry_date)}</span>
                </div>
              ))}
              {timeEntriesQuery.isSuccess && (timeEntriesQuery.data ?? []).length === 0 && <p className="muted">Записей о времени нет</p>}
            </div>
            <div className="form-row-inline">
              <input type="number" min={5} step={5} style={{ width: 90 }} value={timeMinutes} onChange={(e) => setTimeMinutes(Number(e.target.value))} />
              <span className="muted">мин</span>
              <input
                type="text"
                placeholder="Комментарий (необязательно)"
                style={{ flex: 1 }}
                value={timeComment}
                onChange={(e) => setTimeComment(e.target.value)}
              />
              <button className="btn btn-ghost" disabled={timeMutation.isPending} onClick={() => timeMutation.mutate()}>
                Добавить время
              </button>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>История изменений</h2>
            </div>
            <div className="history-list">
              {(historyQuery.data ?? []).map((h) => (
                <div className="history-row" key={h.id}>
                  <span className="muted">{formatDateTime(h.created_at)}</span>
                  <span>{h.action}</span>
                </div>
              ))}
              {historyQuery.isSuccess && (historyQuery.data ?? []).length === 0 && <p className="muted">История пуста</p>}
            </div>
          </div>
        </div>

        <div className="ticket-side">
          <div className="panel">
            <div className="panel-head">
              <h2>Свойства</h2>
            </div>
            <dl className="props-list">
              <dt>Организация</dt>
              <dd>{org?.name ?? "—"}</dd>
              <dt>Канал</dt>
              <dd>
                <ChannelTag channel={ticket.channel} />
              </dd>
              <dt>Исполнитель</dt>
              <dd>
                <WhoMini name={assignee?.full_name} />
              </dd>
              <dt>Договор</dt>
              <dd>{ticket.has_no_active_contract ? "Нет активного договора (тариф по умолчанию)" : "Активный договор"}</dd>
              <dt>Срок реакции</dt>
              <dd>{formatDateTime(ticket.sla_reaction_due_at)}</dd>
              <dt>Срок решения</dt>
              <dd>{formatDateTime(ticket.sla_resolution_due_at)}</dd>
              <dt>Решена</dt>
              <dd>{formatDateTime(ticket.resolved_at)}</dd>
            </dl>
          </div>

          {ticket.has_no_active_contract === false && usageQuery.data && (
            <div className="panel">
              <div className="panel-head">
                <h2>Использование пакета</h2>
              </div>
              <dl className="props-list">
                <dt>Пакет</dt>
                <dd>{formatMinutes(usageQuery.data.package_total_minutes)}</dd>
                <dt>Использовано</dt>
                <dd>{formatMinutes(usageQuery.data.package_used_minutes)}</dd>
                <dt>Сверх лимита</dt>
                <dd>{formatMinutes(usageQuery.data.overage_minutes)}</dd>
                <dt>Стоимость сверх лимита</dt>
                <dd>{usageQuery.data.overage_cost} ₽</dd>
              </dl>
            </div>
          )}

          <div className="panel">
            <div className="panel-head">
              <h2>Статус</h2>
            </div>
            <p className="muted">Текущий: {STATUS_LABELS[ticket.status]}</p>
            <div className="status-actions">
              {availableTransitions.map((next: TicketStatus) => (
                <button
                  key={next}
                  className="btn btn-ghost"
                  disabled={updateMutation.isPending}
                  onClick={() => updateMutation.mutate({ status: next })}
                >
                  → {STATUS_LABELS[next]}
                </button>
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Назначение</h2>
            </div>
            <div className="form-row">
              <label className="form-label">Исполнитель</label>
              <select
                value={ticket.assigned_engineer_id ?? ""}
                onChange={(e) => updateMutation.mutate({ assigned_engineer_id: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">Не назначено</option>
                {(usersQuery.data ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <label className="form-label">Команда</label>
              <select
                value={ticket.team_id ?? ""}
                onChange={(e) => updateMutation.mutate({ team_id: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">Без команды</option>
                {(teamsQuery.data ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
