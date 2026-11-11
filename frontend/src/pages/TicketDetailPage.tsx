import { TicketPlanning } from "../components/TicketPlanning";
import { MessageComposer } from "../components/MessageComposer";
import { MessageContent } from "../components/MessageContent";
import { ticketProjects } from "../api/work";
import { PROJECT_LABELS } from "../lib/work";
import { DeliveryStatus } from "../components/DeliveryStatus";
import { localDate } from "../lib/dates";
import { useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  changeTicketClient,
  createTimeEntry,
  deleteTimeEntry,
  getContact,
  getOrganizationUsage,
  getTicket,
  getTicketHistory,
  listContacts,
  listMessages,
  listOrganizations,
  listTeams,
  listRelatedTickets,
  listResponseTemplates,
  listTicketCalls,
  listTimeEntries,
  listUsers,
  updateTicket,
} from "../api/endpoints";
import { formatCallDuration } from "./CallsPage";
import { TicketTimer } from "../components/TicketTimer";
import { StatusPipeline } from "../components/StatusPipeline";
import { useAuth } from "../auth/AuthContext";
import { ErrorBanner, Loading, PriorityTag, SlaTimerBadge, StatusTag, ChannelTag, WhoMini } from "../components/ui";
import {
  CHANNEL_LABELS,
  MESSAGE_DIRECTION_LABELS,
  formatDateTime,
  formatMinutes,
} from "../lib/labels";
import type { Message } from "../api/types";

function truncate(text: string, max: number): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > max ? `${collapsed.slice(0, max)}…` : collapsed;
}

export function TicketDetailPage({ embedded = false }: { embedded?: boolean }) {
  const { ticketId } = useParams();
  const location = useLocation();
  const from = location.state?.queueReturn;
  const queueReturn = typeof from === "string" && /^\/tickets(?:\?|$)/.test(from) ? from : "/tickets";
  const id = Number(ticketId);
  const qc = useQueryClient();
  const { user } = useAuth();
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [noteReplyTo, setNoteReplyTo] = useState<Message | null>(null);

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
  const projectsQuery = useQuery({queryKey: ["ticket", id, "projects"], queryFn: () => ticketProjects(id), enabled: Number.isFinite(id)});
  const callsQuery = useQuery({
    queryKey: ["ticket", id, "calls"],
    queryFn: () => listTicketCalls(id),
    enabled: Number.isFinite(id),
  });
  const teamsQuery = useQuery({ queryKey: ["teams"], queryFn: listTeams });
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });

  const ticket = ticketQuery.data;

  const contactQuery = useQuery({
    queryKey: ["contact", ticket?.contact_id],
    queryFn: () => getContact(ticket!.contact_id),
    enabled: !!ticket,
  });
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
    onSuccess: (updated) => {
      qc.setQueryData(["ticket", id], updated);
      qc.invalidateQueries({ queryKey: ["ticket", id] });
      qc.invalidateQueries({ queryKey: ["tickets"] });
      qc.invalidateQueries({ queryKey: ["ticket-stats"] });
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
        entry_date: localDate(),
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
  const canChangeClient = user?.role === "dispatcher" || user?.role === "manager" || user?.role === "admin";
  const assignee = (usersQuery.data ?? []).find((u) => u.id === ticket.assigned_engineer_id);

  return (
    <div className="view ticket-detail">
      {!embedded && <Link to={queueReturn} className="queue-back-link">← К очереди заявок</Link>}
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
                      <button className="btn-link" onClick={() => {
                        const internal = m.direction === "internal_note";
                        if (internal) setNoteReplyTo(m); else setReplyTo(m);
                        document.getElementById(`compose-${internal ? "internal_note" : "outbound"}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
                      }}>
                        Ответить
                      </button>
                    </div>
                    {quoted && (
                      <div className="message-quote">
                        <span className="message-quote-label">{MESSAGE_DIRECTION_LABELS[quoted.direction]}:</span>{" "}
                        {truncate(quoted.body, 140)}
                      </div>
                    )}
                    <MessageContent ticketId={id} body={m.body} blocks={m.content_blocks} attachments={m.attachments} />
                    {m.delivery && <DeliveryStatus ticketId={id} messageId={m.id} delivery={m.delivery} />}
                  </div>
                );
              })}
              {messagesQuery.isSuccess && (messagesQuery.data ?? []).length === 0 && <p className="muted">Сообщений пока нет</p>}
            </div>

            <div className="message-composers">
              <MessageComposer key={`note-${id}`} ticketId={id} direction="internal_note" replyTo={noteReplyTo?.ticket_id === id ? noteReplyTo : null}
                clearReply={() => setNoteReplyTo(null)} templates={[]} recipient="" channel="" />
              <MessageComposer key={`reply-${id}`} ticketId={id} direction="outbound" replyTo={replyTo?.ticket_id === id ? replyTo : null}
                clearReply={() => setReplyTo(null)} templates={templatesQuery.data ?? []}
                recipient={contactQuery.data?.full_name ?? "Клиент заявки"} channel={CHANNEL_LABELS[ticket.channel]} />
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
            <div className="form-row-inline ticket-time-form">
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
          <TicketPlanning key={ticket.id} ticket={ticket} />
          <div className="panel">
            <div className="panel-head">
              <h2>Свойства</h2>
            </div>
            <dl className="props-list">
              <dt>Организация</dt>
              <dd>{org?.name ?? "—"}</dd>
              <dt>Контакт</dt>
              <dd>{contactQuery.data?.full_name ?? "—"}</dd>
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

          {canChangeClient && (
            <ClientPanel
              ticketId={ticket.id}
              organizationId={ticket.organization_id}
              currentContactId={ticket.contact_id}
              contactName={contactQuery.data?.full_name ?? ""}
              organizations={orgsQuery.data ?? []}
            />
          )}

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

          {(projectsQuery.data ?? []).length > 0 && <div className="panel"><div className="panel-head"><h2>Проекты</h2></div><div className="list">{projectsQuery.data?.map(p => <Link key={p.id} className="related-ticket" to={`/projects/${p.id}`}><span className="mono">ПР-{p.id}</span><span className="subject">{p.title}</span><span className="muted">{PROJECT_LABELS[p.status]}</span></Link>)}</div></div>}

          {(relatedQuery.data ?? []).length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Связанные заявки</h2>
              </div>
              <div className="list">
                {(relatedQuery.data ?? []).map((r) => (
                  <Link className="related-ticket" key={r.id} to={`/tickets/${r.id}`} state={{ ...location.state, queueReturn }}>
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
              <h2>Ход заявки</h2>
            </div>
            <StatusPipeline
              status={ticket.status}
              disabled={updateMutation.isPending}
              onChange={(next) => updateMutation.mutate({ status: next })}
            />
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Кто занимается</h2>
              {ticket.assigned_engineer_id !== user?.id && (
                <button
                  className="btn btn-ghost"
                  disabled={updateMutation.isPending}
                  onClick={() => updateMutation.mutate({ assigned_engineer_id: user?.id })}
                >
                  Взять себе
                </button>
              )}
            </div>
            <p className="muted">
              {assignee
                ? `Ведёт ${assignee.full_name}.`
                : ticket.team_id
                  ? "Отдана группе — любой её участник может взять заявку себе."
                  : "Исполнителя нет: заявка в общей очереди, её видят все."}
              {" "}
              Назначение само переводит заявку из «Новой» в «Назначена», а снятие возвращает в очередь.
            </p>
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

/** Организация и контакт заявки. Нужен прежде всего для заявок из бота:
 * незнакомый отправитель попадает в «Неизвестные», и диспетчер относит его
 * к организации. Контакт не подменяется — ответы уходят в бот по контакту,
 * поэтому либо тот же человек переносится, либо объединяется с контактом
 * организации (см. tickets.change_client на сервере). */
function ClientPanel({
  ticketId,
  organizationId,
  currentContactId,
  contactName,
  organizations,
}: {
  ticketId: number;
  organizationId: number;
  currentContactId: number;
  contactName: string;
  organizations: { id: number; name: string }[];
}) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [orgId, setOrgId] = useState<number>(organizationId);
  const [contactId, setContactId] = useState<number | null>(null);
  const contactsQuery = useQuery({
    queryKey: ["contacts", orgId],
    queryFn: () => listContacts(orgId),
    enabled: editing,
  });
  const mutation = useMutation({
    mutationFn: () => changeTicketClient(ticketId, orgId, contactId),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
      qc.invalidateQueries({ queryKey: ["contact"] });
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["tickets"] });
      qc.invalidateQueries({ queryKey: ["organization-usage"] });
    },
  });

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Клиент</h2>
        {!editing && (
          <button
            className="btn-link"
            onClick={() => {
              setOrgId(organizationId);
              setContactId(null);
              mutation.reset();
              setEditing(true);
            }}
          >
            Изменить
          </button>
        )}
      </div>
      {!editing ? (
        <p className="muted" style={{ margin: 0 }}>
          Заявку из бота от незнакомого отправителя можно отнести к организации: договор и SLA пересчитаются, вместе с ней
          переедут и другие его заявки.
        </p>
      ) : (
        <>
          {mutation.isError && <ErrorBanner message={(mutation.error as Error).message} />}
          <div className="form-row">
            <label className="form-label">Организация</label>
            <select
              value={orgId}
              onChange={(e) => {
                setOrgId(Number(e.target.value));
                setContactId(null);
              }}
            >
              {organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label">Контакт</label>
            <select value={contactId ?? ""} onChange={(e) => setContactId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">{contactName || "Тот же контакт"}</option>
              {(contactsQuery.data ?? [])
                .filter((c) => c.id !== currentContactId)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.full_name} — объединить
                  </option>
                ))}
            </select>
          </div>
          <p className="muted" style={{ marginTop: 0 }}>
            {contactId === null
              ? "Контакт переедет в выбранную организацию вместе со своими заявками."
              : "Контакт из бота объединится с выбранным: заявки и переписка в боте перейдут к нему."}
          </p>
          <div className="form-row-inline">
            <button className="btn btn-primary" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
              Сохранить
            </button>
            <button className="btn" onClick={() => setEditing(false)}>
              Отмена
            </button>
          </div>
        </>
      )}
    </div>
  );
}
