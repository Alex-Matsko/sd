import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { createTicketFromCall, listCalls, listContacts, listOrganizations, markCallHandled } from "../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../components/ui";
import { formatDateTime } from "../lib/labels";
import type { Call } from "../api/types";

const STATUS_LABELS: Record<Call["status"], string> = {
  ringing: "Звонит",
  answered: "Отвечен",
  completed: "Завершён",
  missed: "Пропущен",
  failed: "Ошибка",
};

const STATUS_CLASS: Record<Call["status"], string> = {
  ringing: "status-new",
  answered: "status-in_progress",
  completed: "status-resolved",
  missed: "status-cancelled",
  failed: "status-cancelled",
};

export function formatCallDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "—";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return mins > 0 ? `${mins} мин ${secs} с` : `${secs} с`;
}

export function CallsPage() {
  const qc = useQueryClient();
  const [unhandledOnly, setUnhandledOnly] = useState(true);
  const [ticketForCall, setTicketForCall] = useState<Call | null>(null);

  const callsQuery = useQuery({
    queryKey: ["calls", unhandledOnly],
    queryFn: () => listCalls({ unhandled_only: unhandledOnly, limit: 50 }),
    // Incoming calls have to surface without a page reload; there's no push
    // channel yet (see decisions.md on websockets), so the panel polls.
    refetchInterval: 10_000,
  });
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });

  const handledMutation = useMutation({
    mutationFn: (id: number) => markCallHandled(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["calls"] }),
  });

  if (callsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (callsQuery.isError) return <div className="view"><ErrorBanner message={(callsQuery.error as Error).message} /></div>;

  const calls = callsQuery.data?.items ?? [];
  const orgsById = new Map((orgsQuery.data ?? []).map((o) => [o.id, o]));

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Звонки
        </h1>
        <div className="spacer" />
        <label className="form-row-inline" style={{ marginBottom: 0 }}>
          <input type="checkbox" checked={unhandledOnly} onChange={(e) => setUnhandledOnly(e.target.checked)} />
          Только необработанные
        </label>
      </div>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        События поступают от телефонии по вебхуку. Пропущенные звонки автоматически становятся заявками; по
        отвеченному звонку заявку можно создать вручную.
      </p>

      {handledMutation.isError && <ErrorBanner message={(handledMutation.error as Error).message} />}
      {calls.length === 0 && <EmptyState text={unhandledOnly ? "Необработанных звонков нет" : "Звонков пока нет"} />}

      {calls.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "1.2fr 1fr 1.4fr 1fr 1fr 1.4fr" }}>
            <span>Номер</span>
            <span>Статус</span>
            <span>Организация</span>
            <span>Длительность</span>
            <span>Время</span>
            <span></span>
          </div>
          {calls.map((call) => (
            <div className="list-row" style={{ gridTemplateColumns: "1.2fr 1fr 1.4fr 1fr 1fr 1.4fr" }} key={call.id}>
              <span className="mono">{call.from_number}</span>
              <span>
                <span className={`status-tag ${STATUS_CLASS[call.status]}`}>{STATUS_LABELS[call.status]}</span>
              </span>
              <span className="muted">
                {call.organization_id ? orgsById.get(call.organization_id)?.name ?? "—" : "Номер не опознан"}
              </span>
              <span className="muted">{formatCallDuration(call.duration_seconds)}</span>
              <span className="muted">{formatDateTime(call.started_at ?? call.created_at)}</span>
              <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
                {call.ticket_id ? (
                  <Link className="btn-link" to={`/tickets/${call.ticket_id}`}>
                    К заявке
                  </Link>
                ) : (
                  <button className="btn-link" onClick={() => setTicketForCall(call)}>
                    Создать заявку
                  </button>
                )}
                {!call.handled_at && (
                  <button className="btn-link" onClick={() => handledMutation.mutate(call.id)}>
                    Обработан
                  </button>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {ticketForCall && (
        <NewTicketFromCallModal
          call={ticketForCall}
          onClose={() => setTicketForCall(null)}
          onCreated={() => {
            setTicketForCall(null);
            qc.invalidateQueries({ queryKey: ["calls"] });
          }}
        />
      )}
    </div>
  );
}

function NewTicketFromCallModal({
  call,
  onClose,
  onCreated,
}: {
  call: Call;
  onClose: () => void;
  onCreated: () => void;
}) {
  const navigate = useNavigate();
  const [subject, setSubject] = useState(`Обращение по звонку с ${call.from_number}`);
  const [contactId, setContactId] = useState<number | "">(call.contact_id ?? "");

  // Only needed when the number wasn't recognized - otherwise the call
  // already carries the contact and the dispatcher just confirms the subject.
  const contactsQuery = useQuery({
    queryKey: ["contacts-all"],
    queryFn: () => listContacts(),
    enabled: call.contact_id === null,
  });

  const createMutation = useMutation({
    mutationFn: () => createTicketFromCall(call.id, { subject: subject.trim(), contact_id: contactId || null }),
    onSuccess: (ticket) => {
      onCreated();
      navigate(`/tickets/${ticket.id}`);
    },
  });

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Заявка по звонку</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {createMutation.isError && <ErrorBanner message={(createMutation.error as Error).message} />}
          <dl className="props-list">
            <dt>Номер</dt>
            <dd className="mono">{call.from_number}</dd>
            <dt>Время</dt>
            <dd>{formatDateTime(call.started_at ?? call.created_at)}</dd>
            <dt>Длительность</dt>
            <dd>{formatCallDuration(call.duration_seconds)}</dd>
          </dl>
          {call.contact_id === null && (
            <div className="form-row">
              <label className="form-label">Контакт (номер не опознан)</label>
              <select value={contactId} onChange={(e) => setContactId(e.target.value ? Number(e.target.value) : "")}>
                <option value="">Выберите контакт…</option>
                {(contactsQuery.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.full_name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="form-row">
            <label className="form-label">Тема заявки</label>
            <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn btn-primary"
            disabled={!subject.trim() || (call.contact_id === null && !contactId) || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Создать заявку
          </button>
        </div>
      </div>
    </div>
  );
}
