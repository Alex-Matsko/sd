import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PortalTicket,
  consumeMagicLink,
  createPortalTicket,
  fetchPortalMe,
  fetchPortalUsage,
  getPortalTicket,
  getPortalToken,
  listPortalTickets,
  portalLogin,
  ratePortalTicket,
  replyToPortalTicket,
  requestMagicLink,
  setPortalToken,
} from "./api";

const STATUS_LABELS: Record<string, string> = {
  new: "Новая",
  assigned: "Назначена",
  in_progress: "В работе",
  waiting_customer: "Ждём вашего ответа",
  waiting_third_party: "Ждём третью сторону",
  resolved: "Решена",
  closed: "Закрыта",
  cancelled: "Отменена",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

export function PortalApp() {
  const [authed, setAuthed] = useState(!!getPortalToken());
  const [openTicketId, setOpenTicketId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  // A magic link lands on /portal?token=… - consume it once, then strip the
  // token from the address bar so it isn't left in history or copied out.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (!token) return;
    consumeMagicLink(token)
      .then(() => setAuthed(true))
      .catch(() => setAuthed(false))
      .finally(() => window.history.replaceState({}, "", window.location.pathname));
  }, []);

  if (!authed) return <PortalLogin onAuthed={() => setAuthed(true)} />;
  if (creating) return <PortalNewTicket onDone={() => setCreating(false)} />;
  if (openTicketId !== null) return <PortalTicketView id={openTicketId} onBack={() => setOpenTicketId(null)} />;

  return (
    <PortalTicketList
      onOpen={setOpenTicketId}
      onCreate={() => setCreating(true)}
      onLogout={() => {
        setPortalToken(null);
        setAuthed(false);
      }}
    />
  );
}

function PortalShell({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="portal">
      <header className="portal-header">
        <div className="portal-brand">
          <span className="brand-mark">ОГ</span>
          <span>Поддержка «Открытые Горизонты»</span>
        </div>
      </header>
      <main className="portal-main">
        <div className="portal-title-row">
          <h1>{title}</h1>
          {action}
        </div>
        {children}
      </main>
    </div>
  );
}

function PortalLogin({ onAuthed }: { onAuthed: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [linkSent, setLinkSent] = useState(false);

  const loginMutation = useMutation({
    mutationFn: () => portalLogin(email.trim(), password),
    onSuccess: onAuthed,
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось войти"),
  });

  const linkMutation = useMutation({
    mutationFn: () => requestMagicLink(email.trim()),
    onSuccess: () => {
      setError(null);
      setLinkSent(true);
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось отправить ссылку"),
  });

  return (
    <div className="portal portal-centered">
      <div className="portal-card">
        <div className="portal-brand" style={{ marginBottom: 18 }}>
          <span className="brand-mark">ОГ</span>
          <span>Личный кабинет</span>
        </div>

        {error && <div className="portal-error">{error}</div>}
        {linkSent && (
          <div className="portal-note">
            Если такой адрес зарегистрирован, мы отправили на него ссылку для входа. Она действует 30 минут.
          </div>
        )}

        <label className="portal-field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
        </label>
        <label className="portal-field">
          <span>Пароль</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            onKeyDown={(e) => e.key === "Enter" && email && password && loginMutation.mutate()}
          />
        </label>

        <button
          className="portal-btn portal-btn-primary"
          disabled={!email.trim() || !password || loginMutation.isPending}
          onClick={() => loginMutation.mutate()}
        >
          Войти
        </button>
        <button
          className="portal-btn portal-btn-ghost"
          disabled={!email.trim() || linkMutation.isPending}
          onClick={() => linkMutation.mutate()}
        >
          Войти по ссылке на почту
        </button>
        <p className="portal-hint">
          Нет пароля? Запросите ссылку — она придёт на вашу рабочую почту и откроет кабинет без пароля.
        </p>
      </div>
    </div>
  );
}

function PortalTicketList({
  onOpen,
  onCreate,
  onLogout,
}: {
  onOpen: (id: number) => void;
  onCreate: () => void;
  onLogout: () => void;
}) {
  const meQuery = useQuery({ queryKey: ["portal-me"], queryFn: fetchPortalMe });
  const ticketsQuery = useQuery({ queryKey: ["portal-tickets"], queryFn: listPortalTickets, refetchInterval: 30_000 });
  const usageQuery = useQuery({
    queryKey: ["portal-usage"],
    queryFn: fetchPortalUsage,
    // Package figures are organization-wide, so the API refuses them unless
    // this contact is allowed org-wide visibility - don't even ask otherwise.
    enabled: meQuery.data?.can_view_org_tickets === true,
    retry: false,
  });

  const tickets = ticketsQuery.data ?? [];

  return (
    <PortalShell
      title="Мои обращения"
      action={
        <button className="portal-btn portal-btn-primary portal-btn-compact" onClick={onCreate}>
          Новое обращение
        </button>
      }
    >
      {meQuery.data && (
        <p className="portal-sub">
          {meQuery.data.full_name} · {meQuery.data.organization}
          <button className="portal-link" onClick={onLogout} style={{ marginLeft: 12 }}>
            Выйти
          </button>
        </p>
      )}

      {usageQuery.data?.has_contract && (
        <div className="portal-usage">
          <div>
            <strong>{usageQuery.data.package_remaining_hours}</strong>
            <span>ч осталось в пакете</span>
          </div>
          <div>
            <strong>{usageQuery.data.package_used_hours}</strong>
            <span>ч израсходовано</span>
          </div>
          {(usageQuery.data.overage_hours ?? 0) > 0 && (
            <div>
              <strong>{usageQuery.data.overage_hours}</strong>
              <span>ч сверх пакета</span>
            </div>
          )}
        </div>
      )}

      {ticketsQuery.isLoading && <p className="portal-muted">Загрузка…</p>}
      {tickets.length === 0 && !ticketsQuery.isLoading && (
        <p className="portal-muted">Обращений пока нет. Нажмите «Новое обращение», чтобы написать нам.</p>
      )}

      <div className="portal-list">
        {tickets.map((t) => (
          <button className="portal-ticket" key={t.id} onClick={() => onOpen(t.id)}>
            <div className="portal-ticket-head">
              <span className="portal-number">{t.display_number}</span>
              <span className={`portal-status portal-status-${t.status}`}>{STATUS_LABELS[t.status] ?? t.status}</span>
            </div>
            <div className="portal-ticket-subject">{t.subject}</div>
            <div className="portal-muted portal-small">Создано {formatDate(t.created_at)}</div>
          </button>
        ))}
      </div>
    </PortalShell>
  );
}

function PortalNewTicket({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () => createPortalTicket({ subject: subject.trim(), body: body.trim() }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portal-tickets"] });
      onDone();
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось создать обращение"),
  });

  return (
    <PortalShell
      title="Новое обращение"
      action={
        <button className="portal-link" onClick={onDone}>
          Отмена
        </button>
      }
    >
      {error && <div className="portal-error">{error}</div>}
      <label className="portal-field">
        <span>Тема</span>
        <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Не работает почта" />
      </label>
      <label className="portal-field">
        <span>Опишите проблему</span>
        <textarea rows={7} value={body} onChange={(e) => setBody(e.target.value)} />
      </label>
      <button
        className="portal-btn portal-btn-primary"
        disabled={subject.trim().length < 3 || !body.trim() || createMutation.isPending}
        onClick={() => createMutation.mutate()}
      >
        Отправить
      </button>
    </PortalShell>
  );
}

function PortalTicketView({ id, onBack }: { id: number; onBack: () => void }) {
  const qc = useQueryClient();
  const [reply, setReply] = useState("");
  const ticketQuery = useQuery({
    queryKey: ["portal-ticket", id],
    queryFn: () => getPortalTicket(id),
    refetchInterval: 15_000,
  });

  const replyMutation = useMutation({
    mutationFn: () => replyToPortalTicket(id, reply.trim()),
    onSuccess: () => {
      setReply("");
      qc.invalidateQueries({ queryKey: ["portal-ticket", id] });
    },
  });

  const rateMutation = useMutation({
    mutationFn: (rating: number) => ratePortalTicket(id, rating),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portal-ticket", id] }),
  });

  const ticket = ticketQuery.data;
  const canRate = ticket && !ticket.csat_rating && ["resolved", "closed"].includes(ticket.status);

  return (
    <PortalShell
      title={ticket ? ticket.display_number : "Обращение"}
      action={
        <button className="portal-link" onClick={onBack}>
          ← К списку
        </button>
      }
    >
      {ticketQuery.isLoading && <p className="portal-muted">Загрузка…</p>}
      {ticket && (
        <>
          <h2 className="portal-subject">{ticket.subject}</h2>
          <p className="portal-sub">
            <span className={`portal-status portal-status-${ticket.status}`}>
              {STATUS_LABELS[ticket.status] ?? ticket.status}
            </span>
            <span className="portal-muted portal-small" style={{ marginLeft: 10 }}>
              создано {formatDate(ticket.created_at)}
            </span>
          </p>

          <div className="portal-thread">
            {ticket.messages.map((m) => (
              <div key={m.id} className={`portal-message ${m.is_from_support ? "from-support" : "from-me"}`}>
                <div className="portal-message-author">{m.is_from_support ? "Поддержка" : "Вы"}</div>
                <div className="portal-message-body">{m.body}</div>
                <div className="portal-message-time">{formatDate(m.created_at)}</div>
              </div>
            ))}
            {ticket.messages.length === 0 && <p className="portal-muted">Сообщений пока нет</p>}
          </div>

          {canRate && (
            <div className="portal-rate">
              <span>Оцените решение:</span>
              <div className="portal-stars">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button key={n} onClick={() => rateMutation.mutate(n)} disabled={rateMutation.isPending}>
                    ★
                  </button>
                ))}
              </div>
            </div>
          )}
          {ticket.csat_rating && (
            <p className="portal-note">Спасибо за оценку: {"★".repeat(ticket.csat_rating)} ({ticket.csat_rating}/5)</p>
          )}

          <div className="portal-reply">
            <textarea
              rows={3}
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              placeholder="Написать в поддержку…"
            />
            {replyMutation.isError && <div className="portal-error">{(replyMutation.error as Error).message}</div>}
            <button
              className="portal-btn portal-btn-primary"
              disabled={!reply.trim() || replyMutation.isPending}
              onClick={() => replyMutation.mutate()}
            >
              Отправить
            </button>
          </div>
        </>
      )}
    </PortalShell>
  );
}
