import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createMessage,
  createTimeEntry,
  deleteTimeEntry,
  downloadAttachment,
  getOrganizationUsage,
  getTicket,
  getTicketHistory,
  listMessages,
  listOrganizations,
  listTeams,
  listRelatedTickets,
  listResponseTemplates,
  listTicketCalls,
  listTimeEntries,
  listUsers,
  updateTicket,
  uploadAttachment,
} from "../api/endpoints";
import { formatCallDuration } from "./CallsPage";
import { TicketTimer } from "../components/TicketTimer";
import { ErrorBanner, Loading, PriorityTag, SlaTimerBadge, StatusTag, ChannelTag, WhoMini } from "../components/ui";
import {
  CHANNEL_LABELS,
  MESSAGE_DIRECTION_LABELS,
  STATUS_LABELS,
  STATUS_TRANSITIONS,
  formatDateTime,
  formatMinutes,
} from "../lib/labels";
import type { Message, MessageDirection, TicketStatus } from "../api/types";

function truncate(text: string, max: number): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > max ? `${collapsed.slice(0, max)}…` : collapsed;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

export function TicketDetailPage() {
  const { ticketId } = useParams();
  const id = Number(ticketId);
  const qc = useQueryClient();
  const [replyBody, setReplyBody] = useState("");
  const [replyDirection, setReplyDirection] = useState<MessageDirection>("outbound");
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [timeMinutes, setTimeMinutes] = useState(30);
  const [timeComment, setTimeComment] = useState("");

  const ticketQuery = useQuery({
    queryKey: ["ticket", id],
    queryFn: () => getTicket(id),
    enabled: Number.isFinite(id),
    refetchInterval: 30_000,
  });
  const messagesQuery = useQuery({
    queryKey: ["ticket", id, "messages"],
    queryFn: () => listMessages(id),
    enabled: Number.isFinite(id),
    refetchInterval: 5_000,
  });
  const timeEntriesQuery = useQuery({ queryKey: ["ticket", id, "time"], queryFn: () => listTimeEntries(id), enabled: Number.isFinite(id) });
  const historyQuery = useQuery({ queryKey: ["ticket", id, "history"], queryFn: () => getTicketHistory(id), enabled: Number.isFinite(id) });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const relatedQuery = useQuery({
    queryKey: ["ticket", id, "related"],
    queryFn: () => listRelatedTickets(id),
    enabled: Number.isFinite(id),
  });
  const callsQuery = useQuery({
    queryKey: ["ticket", id, "calls"],
    queryFn: () => listTicketCalls(id),
    enabled: Number.isFinite(id),
  });
  const teamsQuery = useQuery({ queryKey: ["teams"], queryFn: listTeams });
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });

  const ticket = ticketQuery.data;

  const usageQuery = useQuery({
    queryKey: ["organization-usage", ticket?.organization_id],
    queryFn: () => getOrganizationUsage(ticket!.organization_id),
    enabled: !!ticket && !ticket.has_no_active_contract,
    retry: false,
  });

  const templatesQuery = useQuery({
    queryKey: ["response-templates", ticket?.category_id ?? null],
    queryFn: () => listResponseTemplates({ category_id: ticket?.category_id ?? undefined }),
    enabled: !!ticket,
  });

  const updateMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => updateTicket(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ticket", id] }),
  });

  const messageMutation = useMutation({
    mutationFn: async () => {
      const message = await createMessage(id, {
        direction: replyDirection,
        body: replyBody.trim(),
        reply_to_message_id: replyTo?.id ?? null,
      });
      // Attachments hang off a message, so the file can only go up once the
      // message exists - hence upload-after-create rather than one request.
      for (const file of pendingFiles) {
        await uploadAttachment(id, message.id, file);
      }
      return message;
    },
    onSuccess: () => {
      setReplyBody("");
      setReplyTo(null);
      setPendingFiles([]);
      qc.invalidateQueries({ queryKey: ["ticket", id, "messages"] });
      qc.invalidateQueries({ queryKey: ["ticket", id] });
    },
  });

  const deleteTimeMutation = useMutation({
    mutationFn: (entryId: number) => deleteTimeEntry(id, entryId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ticket", id, "time"] });
      qc.invalidateQueries({ queryKey: ["organization-usage"] });
      qc.invalidateQueries({ queryKey: ["ticket", id, "history"] });
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
          {ticket.sla && (
            <div className="panel">
              <div className="panel-head">
                <h2>SLA</h2>
              </div>
              <div className="tag-row">
                <SlaTimerBadge label="Реакция" timer={ticket.sla.reaction} />
                <SlaTimerBadge label="Решение" timer={ticket.sla.resolution} />
              </div>
              <dl className="props-list">
                <dt>Срок реакции</dt>
                <dd>{formatDateTime(ticket.sla_reaction_due_at)}</dd>
                <dt>Срок решения</dt>
                <dd>{formatDateTime(ticket.sla_resolution_due_at)}</dd>
              </dl>
            </div>
          )}

          {(callsQuery.data ?? []).length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Звонок</h2>
              </div>
              {(callsQuery.data ?? []).map((call) => (
                <dl className="props-list" key={call.id}>
                  <dt>Номер</dt>
                  <dd className="mono">{call.from_number}</dd>
                  <dt>Время</dt>
                  <dd>{formatDateTime(call.started_at ?? call.created_at)}</dd>
                  <dt>Длительность</dt>
                  <dd>{formatCallDuration(call.duration_seconds)}</dd>
                  <dt>Запись разговора</dt>
                  <dd>
                    {call.recording_url ? (
                      <a className="link" href={call.recording_url} target="_blank" rel="noreferrer">
                        Прослушать
                      </a>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </dd>
                </dl>
              ))}
            </div>
          )}

          <div className="panel">
            <div className="panel-head">
              <h2>Переписка</h2>
            </div>
            <div className="message-thread">
              {(messagesQuery.data ?? []).map((m) => {
                const quoted = m.reply_to_message_id
                  ? (messagesQuery.data ?? []).find((candidate) => candidate.id === m.reply_to_message_id)
                  : undefined;
                return (
                  <div key={m.id} className={`message message-${m.direction}`}>
                    <div className="message-head">
                      <span className="message-direction">{MESSAGE_DIRECTION_LABELS[m.direction]}</span>
                      <span className="muted">{CHANNEL_LABELS[m.channel]}</span>
                      <span className="spacer" />
                      <span className="muted">{formatDateTime(m.created_at)}</span>
                      <button className="btn-link" onClick={() => setReplyTo(m)}>
                        Ответить
                      </button>
                    </div>
                    {quoted && (
                      <div className="message-quote">
                        <span className="message-quote-label">{MESSAGE_DIRECTION_LABELS[quoted.direction]}:</span>{" "}
                        {truncate(quoted.body, 140)}
                      </div>
                    )}
                    <div className="message-body">{m.body}</div>
                    {m.attachments.length > 0 && (
                      <div className="message-attachments">
                        {m.attachments.map((a) => (
                          <button key={a.id} className="attachment-chip" onClick={() => downloadAttachment(id, a)}>
                            <span className="attachment-name">{a.filename}</span>
                            <span className="muted">{formatFileSize(a.size_bytes)}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
              {messagesQuery.isSuccess && (messagesQuery.data ?? []).length === 0 && <p className="muted">Сообщений пока нет</p>}
            </div>

            <div className="reply-box">
              {replyTo && (
                <div className="message-quote message-quote-active">
                  <span className="message-quote-label">Ответ на «{MESSAGE_DIRECTION_LABELS[replyTo.direction]}»:</span>{" "}
                  {truncate(replyTo.body, 140)}
                  <button className="btn-link" onClick={() => setReplyTo(null)}>
                    ✕
                  </button>
                </div>
              )}
              <div className="form-row-inline">
                <label>
                  <input type="radio" checked={replyDirection === "outbound"} onChange={() => setReplyDirection("outbound")} /> Ответ клиенту
                </label>
                <label>
                  <input type="radio" checked={replyDirection === "internal_note"} onChange={() => setReplyDirection("internal_note")} /> Внутренняя заметка
                </label>
              </div>
              {(templatesQuery.data ?? []).length > 0 && (
                <select
                  value=""
                  onChange={(e) => {
                    const template = (templatesQuery.data ?? []).find((t) => t.id === Number(e.target.value));
                    if (!template) return;
                    // Append rather than replace: an engineer often types a
                    // sentence of context first, then drops in the boilerplate.
                    setReplyBody((body) => (body.trim() ? `${body.trimEnd()}\n\n${template.body}` : template.body));
                    e.target.value = "";
                  }}
                >
                  <option value="">Вставить шаблон ответа…</option>
                  {(templatesQuery.data ?? []).map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              )}
              <textarea rows={3} value={replyBody} onChange={(e) => setReplyBody(e.target.value)} placeholder="Введите текст сообщения…" />
              {pendingFiles.length > 0 && (
                <div className="message-attachments">
                  {pendingFiles.map((file, index) => (
                    <span className="attachment-chip" key={`${file.name}-${index}`}>
                      <span className="attachment-name">{file.name}</span>
                      <span className="muted">{formatFileSize(file.size)}</span>
                      <button
                        className="btn-link"
                        onClick={() => setPendingFiles((files) => files.filter((_, i) => i !== index))}
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                </div>
              )}
              {messageMutation.isError && <ErrorBanner message={(messageMutation.error as Error).message} />}
              <div className="modal-foot" style={{ padding: 0, borderTop: "none" }}>
                <label className="btn btn-ghost" style={{ cursor: "pointer" }}>
                  Прикрепить файл
                  <input
                    type="file"
                    multiple
                    style={{ display: "none" }}
                    onChange={(e) => {
                      // Read the FileList before resetting the input: the
                      // state updater below runs later, by which point
                      // clearing `value` has already emptied `e.target.files`.
                      // (Resetting is what lets the same file be picked twice.)
                      const chosen = Array.from(e.target.files ?? []);
                      e.target.value = "";
                      setPendingFiles((files) => [...files, ...chosen]);
                    }}
                  />
                </label>
                <div className="spacer" />
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
              <TicketTimer ticketId={id} />
            </div>
            <div className="time-entries">
              {(timeEntriesQuery.data ?? []).map((entry) => (
                <div className="time-entry-row" key={entry.id}>
                  <span className="mono">{formatMinutes(entry.duration_minutes)}</span>
                  <span className="muted">{entry.comment ?? "—"}</span>
                  <span className="muted">{formatDateTime(entry.entry_date)}</span>
                  {/* Списание, заведённое не на ту заявку, попадает в счёт
                      клиенту — убрать его должно быть можно. */}
                  <button
                    className="btn-link"
                    title="Удалить запись"
                    disabled={deleteTimeMutation.isPending}
                    onClick={() => {
                      if (window.confirm("Удалить запись о времени? Она исчезнет из отчёта клиенту.")) {
                        deleteTimeMutation.mutate(entry.id);
                      }
                    }}
                  >
                    Удалить
                  </button>
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
              <dt>Решена</dt>
              <dd>{formatDateTime(ticket.resolved_at)}</dd>
              {ticket.reopen_count > 0 && (
                <>
                  <dt>Переоткрывалась</dt>
                  {/* Доля возвратов — показатель качества решения; на карточке
                      это подсказка, что случай стоит разобрать глубже. */}
                  <dd className="reopen-mark">{ticket.reopen_count} раз(а)</dd>
                </>
              )}
              <dt>Повторяющаяся</dt>
              <dd>
                {/* ТЗ р. 4: Problem Management здесь — метка «повторяющаяся
                    проблема» плюс связь заявок parent/child. */}
                <label className="form-row-inline" style={{ marginBottom: 0, gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={ticket.is_recurring_problem}
                    onChange={(e) => updateMutation.mutate({ is_recurring_problem: e.target.checked })}
                  />
                  <span className="muted">случай не разовый</span>
                </label>
              </dd>
              <dt>Оценка клиента</dt>
              <dd>
                {ticket.csat_rating ? (
                  <>
                    {"★".repeat(ticket.csat_rating)}
                    <span className="muted">{"★".repeat(5 - ticket.csat_rating)}</span>{" "}
                    <span className="muted">{ticket.csat_rating}/5</span>
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </dd>
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

          {(relatedQuery.data ?? []).length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Связанные заявки</h2>
              </div>
              <div className="list">
                {(relatedQuery.data ?? []).map((r) => (
                  <Link className="related-ticket" key={r.id} to={`/tickets/${r.id}`}>
                    <span className="mono">{r.display_number}</span>
                    <span className="subject">{r.subject}</span>
                    <StatusTag status={r.status} />
                  </Link>
                ))}
              </div>
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
