import { ProjectApprovals } from "./ProjectApprovals";
import { BrandMark } from "../components/BrandMark";
import { useDraftRequestId } from "../lib/useDraftRequestId";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
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
  fetchPortalUpdates,
  markPortalUpdatesSeen,
  downloadMyReport,
  downloadPortalFile,
  changePortalPassword,
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
  const qc = useQueryClient();
  const [authed, setAuthed] = useState(!!getPortalToken());
  const [openTicketId, setOpenTicketId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const magicRequest = useRef<Promise<unknown> | null>(null);

  useEffect(() => {
    function endSession() {
      setAuthed(false);
      setOpenTicketId(null);
      setCreating(false);
      qc.clear();
    }
    window.addEventListener("sd:portal-session-ended", endSession);
    return () => window.removeEventListener("sd:portal-session-ended", endSession);
  }, [qc]);

  // A magic link lands on /portal?token=… - consume it once, then strip the
  // token from the address bar so it isn't left in history or copied out.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (!token) return;
    magicRequest.current ??= consumeMagicLink(token);
    magicRequest.current
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
          <BrandMark />
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
          <BrandMark />
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
  const [changingPassword, setChangingPassword] = useState(false);
  const [search, setSearch] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  // Поиск отправляется не на каждое нажатие клавиши: иначе запрос уходит на
  // каждую букву, а список дёргается под пальцами.
  const [appliedSearch, setAppliedSearch] = useState("");

  const meQuery = useQuery({ queryKey: ["portal-me"], queryFn: fetchPortalMe });
  const ticketsQuery = useQuery({
    queryKey: ["portal-tickets", appliedSearch, openOnly],
    queryFn: () => listPortalTickets({ q: appliedSearch || undefined, open_only: openOnly }),
    refetchInterval: 30_000,
  });
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
          <button className="portal-link" onClick={() => setChangingPassword(true)} style={{ marginLeft: 12 }}>
            Сменить пароль
          </button>
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

      {changingPassword && <PortalPasswordForm onClose={() => setChangingPassword(false)} />}

      <PortalUpdatesBanner onOpen={onOpen} />

      <div className="portal-filters">
        <input
          type="search"
          placeholder="Поиск по обращениям и номеру"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setAppliedSearch(search.trim())}
        />
        <button className="portal-btn portal-btn-compact" onClick={() => setAppliedSearch(search.trim())}>
          Найти
        </button>
        <label className="portal-checkbox">
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
          только открытые
        </label>
        {appliedSearch && (
          <button
            className="portal-link"
            onClick={() => {
              setSearch("");
              setAppliedSearch("");
            }}
          >
            сбросить
          </button>
        )}
      </div>

      <ProjectApprovals />
      {meQuery.data?.can_view_org_tickets && <PortalReportLink />}

      {ticketsQuery.isLoading && <p className="portal-muted">Загрузка…</p>}
      {tickets.length === 0 && !ticketsQuery.isLoading && (
        <p className="portal-muted">
          {appliedSearch || openOnly
            ? "По этим условиям ничего не нашлось."
            : "Обращений пока нет. Нажмите «Новое обращение», чтобы написать нам."}
        </p>
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
  const [files, setFiles] = useState<File[]>([]);

  const [downloadError, setDownloadError] = useState<string | null>(null);
  const ticketQuery = useQuery({
    queryKey: ["portal-ticket", id],
    queryFn: () => getPortalTicket(id),
    refetchInterval: 15_000,
  });

  const requestId = useDraftRequestId(JSON.stringify([reply, files.map((file) => [file.name, file.size, file.lastModified])]));
  const replyMutation = useMutation({
    mutationFn: () => replyToPortalTicket(id, reply.trim(), files, requestId),
    onSuccess: () => {
      setReply("");
      setFiles([]);
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
            {/* Кто ведёт заявку: в мессенджерах мы это сообщаем, а в кабинете
                было не видно — клиент не знал, к кому обращаться. */}
            {ticket.assigned_engineer_name && (
              <span className="portal-muted portal-small" style={{ marginLeft: 10 }}>
                · ведёт {ticket.assigned_engineer_name}
              </span>
            )}
          </p>

          <div className="portal-thread">
            {ticket.messages.map((m) => (
              <div key={m.id} className={`portal-message ${m.is_from_support ? "from-support" : "from-me"}`}>
                <div className="portal-message-author">{m.is_from_support ? "Поддержка" : "Вы"}</div>
                <div className="portal-message-body">{m.body}</div>
                {m.attachments?.length > 0 && (
                  <div className="portal-attachments">
                    {m.attachments.map((a) => (
                      <button
                        key={a.id}
                        className="portal-link portal-small"
                        onClick={() =>
                          downloadPortalFile(`/tickets/${id}/attachments/${a.id}`, a.filename).catch((error: Error) => setDownloadError(error.message))
                        }
                      >
                        {a.filename} ({Math.max(1, Math.round(a.size_bytes / 1024))} КБ)
                      </button>
                    ))}
                  </div>
                )}
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
              disabled={replyMutation.isPending}
              aria-label="Текст сообщения"
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              placeholder="Написать в поддержку…"
            />
            <div className="portal-reply-files">
              <label className="portal-link portal-small">
                Приложить файл
                <input
                  type="file"
                  multiple
                  style={{ display: "none" }}
                  onChange={(e) => {
                    // Список читается до сброса значения: после очистки
                    // input.files уже пуст.
                    const picked = Array.from(e.target.files ?? []);
                    e.target.value = "";
                    setFiles((current) => [...current, ...picked]);
                  }}
                />
              </label>
              {files.map((file, index) => (
                <span className="portal-file-chip" key={`${file.name}${index}`}>
                  {file.name}
                  <button
                    className="portal-link"
                    onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            {downloadError && <div className="portal-error" role="alert">{downloadError}</div>}
            {replyMutation.isError && <div className="portal-error">{(replyMutation.error as Error).message}</div>}
            <button
              className="portal-btn portal-btn-primary"
              disabled={(!reply.trim() && files.length === 0) || replyMutation.isPending}
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


/** «Что нового» — сводка изменений с прошлого визита.
 *
 *  Клиент бывает в кабинете изредка: без сводки он узнаёт об ответе, только
 *  если сам откроет заявку и заметит новое сообщение. Опрос раз в двадцать
 *  секунд, живого соединения тут нет намеренно — см. комментарий в
 *  /portal/updates на сервере.
 */
function PortalUpdatesBanner({ onOpen }: { onOpen: (id: number) => void }) {
  const qc = useQueryClient();
  const updatesQuery = useQuery({
    queryKey: ["portal-updates"],
    queryFn: fetchPortalUpdates,
    refetchInterval: 20_000,
  });

  const seenMutation = useMutation({
    mutationFn: markPortalUpdatesSeen,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portal-updates"] });
      qc.invalidateQueries({ queryKey: ["portal-tickets"] });
    },
  });

  const updates = updatesQuery.data;
  if (!updates || updates.tickets.length === 0) return null;

  return (
    <div className="portal-updates">
      <div className="portal-updates-head">
        <strong>Что нового</strong>
        <button className="portal-link" onClick={() => seenMutation.mutate()}>
          отметить прочитанным
        </button>
      </div>
      {updates.tickets.map((u) => (
        <button className="portal-update" key={u.ticket_id} onClick={() => onOpen(u.ticket_id)}>
          <span className="portal-number">{u.display_number}</span>
          <span className="portal-update-text">
            {u.subject}
            <span className="portal-muted portal-small">
              {[
                u.new_messages > 0 ? `новых сообщений: ${u.new_messages}` : null,
                u.status_changed ? `статус: ${STATUS_LABELS[u.status] ?? u.status}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}

/** Свой отчёт за прошлый месяц: тот же документ, что присылает менеджер. */
function PortalReportLink() {
  const [error, setError] = useState<string | null>(null);
  const previous = new Date();
  previous.setMonth(previous.getMonth() - 1);
  const year = previous.getFullYear();
  const month = previous.getMonth() + 1;
  const label = previous.toLocaleString("ru-RU", { month: "long", year: "numeric" });

  return (
    <p className="portal-muted portal-small portal-report-line">
      <button
        className="portal-link"
        onClick={() =>
          downloadMyReport(year, month).catch((e) =>
            setError(e instanceof Error ? e.message : "Не удалось скачать отчёт")
          )
        }
      >
        Скачать отчёт за {label}
      </button>
      {error && <span className="portal-error-inline"> {error}</span>}
    </p>
  );
}


/** Смена выданного пароля.
 *
 *  Пароль клиенту диктует диспетчер — значит, его знает посторонний человек
 *  и, скорее всего, он где-то записан. Возможности сменить его не было.
 */
function PortalPasswordForm({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [done, setDone] = useState(false);

  const changeMutation = useMutation({
    mutationFn: () => changePortalPassword(current, next),
    onSuccess: () => setDone(true),
  });

  if (done) {
    return (
      <div className="portal-panel">
        <p className="portal-note">Пароль изменён.</p>
        <button className="portal-link" onClick={onClose}>
          Закрыть
        </button>
      </div>
    );
  }

  return (
    <div className="portal-panel">
      <strong>Смена пароля</strong>
      <input
        type="password"
        placeholder="Текущий пароль"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
      />
      <input
        type="password"
        placeholder="Новый пароль, не менее 8 символов"
        value={next}
        onChange={(e) => setNext(e.target.value)}
      />
      {changeMutation.isError && <div className="portal-error">{(changeMutation.error as Error).message}</div>}
      <div className="portal-panel-actions">
        <button className="portal-link" onClick={onClose}>
          Отмена
        </button>
        <button
          className="portal-btn portal-btn-primary portal-btn-compact"
          disabled={!current || next.length < 8 || changeMutation.isPending}
          onClick={() => changeMutation.mutate()}
        >
          Сменить
        </button>
      </div>
    </div>
  );
}
