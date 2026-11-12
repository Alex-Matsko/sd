import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { changeOwnPassword, fetchCurrentUser, requestTelegramLinkCode, unlinkTelegram, requestMaxLinkCode, unlinkMax, updateMaxNotifications, updateTelegramNotifications } from "../api/auth";
import type { TelegramLinkCode, User } from "../api/types";
import { ErrorBanner, Loading } from "../components/ui";
import { USER_ROLE_LABELS, formatDateTime } from "../lib/labels";

type Messenger = "telegram" | "max";
type NotificationScope = User["telegram_notification_scope"];
const MESSENGER_NAMES: Record<Messenger, string> = { telegram: "Telegram", max: "MAX" };
function isLinked(user: User | undefined, channel: Messenger) {
  return channel === "telegram" ? Boolean(user?.telegram_id) : Boolean(user?.max_linked);
}

export function ProfilePage() {
  const me = useQuery({ queryKey: ["me"], queryFn: fetchCurrentUser });
  if (me.isLoading) return <div className="view"><Loading /></div>;
  if (me.isError || !me.data) return <div className="view"><ErrorBanner message={me.error?.message ?? "Не удалось загрузить профиль"} /></div>;
  const user = me.data;
  return <div className="view profile-page">
    <h1 className="view-title">Профиль</h1>
    <section className="panel profile-account" aria-label="Учётная запись">
      <div className="panel-head"><h2>Учётная запись</h2></div>
      <dl className="profile-account-summary"><div><dt>ФИО</dt><dd>{user.full_name}</dd></div><div><dt>Email</dt><dd>{user.email}</dd></div><div><dt>Роль</dt><dd>{USER_ROLE_LABELS[user.role]}</dd></div></dl>
    </section>
    <section className="panel profile-notifications" aria-label="Уведомления">
      <div className="panel-head"><h2>Уведомления</h2></div>
      <p className="profile-section-description">Подключите удобный мессенджер и выберите, какие заявки получать.</p>
      <div className="notification-channels"><MessengerCard channel="telegram" user={user} /><MessengerCard channel="max" user={user} /></div>
      <p className="notification-link-help">Для подключения получите код и отправьте команду боту службы поддержки в выбранном мессенджере. Статус обновится автоматически.</p>
    </section>
    <PasswordPanel />
  </div>;
}

function MessengerCard({ channel, user }: { channel: Messenger; user: User }) {
  const qc = useQueryClient();
  const name = MESSENGER_NAMES[channel];
  const linked = isLinked(user, channel);
  const fullQueue = user.role !== "engineer";
  const [code, setCode] = useState<TelegramLinkCode | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "selected">("idle");
  const codeElement = useRef<HTMLElement>(null);
  useQuery({ queryKey: ["me"], queryFn: fetchCurrentUser,
    refetchInterval: (query) => code && Date.now() < new Date(code.expires_at).getTime() && !isLinked(query.state.data, channel) ? 4_000 : false });
  const request = useMutation({ mutationFn: channel === "telegram" ? requestTelegramLinkCode : requestMaxLinkCode,
    onSuccess: (value) => { setCode(value); setCopyState("idle"); } });
  const unlink = useMutation({ mutationFn: channel === "telegram" ? unlinkTelegram : unlinkMax,
    onSuccess: () => { setCode(null); return qc.invalidateQueries({ queryKey: ["me"] }); } });
  const preference = useMutation({ mutationFn: (scope: NotificationScope) => channel === "telegram" ? updateTelegramNotifications(scope) : updateMaxNotifications(scope !== "off"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }) });
  const savedScope = channel === "telegram" ? (user.telegram_notification_scope === "all" && !fullQueue ? "assigned" : user.telegram_notification_scope)
    : user.max_notify_new_tickets ? (fullQueue ? "all" : "assigned") : "off";
  const scope = preference.isPending ? preference.variables : savedScope;
  const error = request.error ?? unlink.error ?? preference.error;
  async function copyCommand() {
    if (!code) return;
    try { await navigator.clipboard.writeText(`/link ${code.code}`); setCopyState("copied"); }
    catch {
      if (codeElement.current) { const range = document.createRange(); range.selectNodeContents(codeElement.current); window.getSelection()?.removeAllRanges(); window.getSelection()?.addRange(range); }
      setCopyState("selected");
    }
  }
  return <section className="notification-channel" aria-label={`Уведомления в ${name}`}>
    <header className="notification-channel-header"><h3>{name}</h3><span className={`status-tag ${linked ? "status-resolved" : "status-closed"}`}>{linked ? "Подключён" : "Не подключён"}</span></header>
    <p className="notification-events">{channel === "telegram" ? "Новые заявки, назначения, ответы клиентов и риски SLA." : "Новые заявки из всех каналов service desk."}</p>
    <div className="notification-channel-content">
      {linked ? <>
        <label className="form-row">Какие заявки присылать<select aria-label={`Уведомления ${name}`} value={scope} disabled={preference.isPending || unlink.isPending} onChange={(event) => preference.mutate(event.target.value as NotificationScope)}>
          {fullQueue && <option value="all">{channel === "telegram" ? "Все заявки, включая неразобранные" : "Все новые заявки, включая неразобранные"}</option>}
          {(channel === "telegram" || !fullQueue) && <option value="assigned">Только назначенные мне</option>}
          <option value="off">Уведомления выключены</option>
        </select></label>
        <p className="notification-channel-note">{scope === "off" ? "Доставка приостановлена. Аккаунт остаётся подключённым." : scope === "assigned" ? "Уведомления только по заявкам, назначенным лично вам." : "Включая заявки без исполнителя и назначенные другим сотрудникам."}</p>
      </> : code ? <div className="notification-link-code"><p>Отправьте боту в {name}:</p><div><code ref={codeElement}>/link {code.code}</code><button type="button" className="btn btn-ghost" onClick={copyCommand}>{copyState === "copied" ? "Скопировано" : "Копировать"}</button></div><p className="muted">Код действует до {formatDateTime(code.expires_at)}.</p>{copyState === "selected" && <p className="muted" role="status">Команда выделена. Скопируйте её через меню браузера или Ctrl/Cmd+C.</p>}</div>
        : <p className="notification-channel-note notification-connect-note">Получите одноразовый код, чтобы подключить свой аккаунт {name}.</p>}
      {error && <ErrorBanner message={error.message} />}
    </div>
    <footer className="notification-channel-actions">{linked ? <button type="button" className="btn btn-ghost" disabled={unlink.isPending || preference.isPending} onClick={() => unlink.mutate()}>Отключить аккаунт</button>
      : <button type="button" className="btn btn-primary" disabled={request.isPending} onClick={() => request.mutate()}>{request.isPending ? "Получение кода…" : code ? "Получить новый код" : "Получить код"}</button>}</footer>
  </section>;
}

function PasswordPanel() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const passwordMutation = useMutation({
    mutationFn: () => changeOwnPassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setRepeat("");
      setError(null);
      setDone(true);
    },
    onError: (e) => {
      setDone(false);
      setError(e instanceof Error ? e.message : "Не удалось сменить пароль");
    },
  });

  function submit() {
    if (next.length < 8) {
      setError("Новый пароль должен быть не короче 8 символов");
      return;
    }
    if (next !== repeat) {
      setError("Новый пароль и подтверждение не совпадают");
      return;
    }
    setError(null);
    passwordMutation.mutate();
  }

  return (
    <section className="panel profile-password" aria-label="Смена пароля">
      <div className="panel-head">
        <h2>Смена пароля</h2>
      </div>
      {error && <ErrorBanner message={error} />}
      {done && <p className="muted">Пароль изменён. Другие ваши сессии завершены.</p>}
      <div className="profile-password-fields">
        <label className="form-row">Текущий пароль<input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
        <label className="form-row">Новый пароль<input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></label>
        <label className="form-row">Повторите новый<input type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} /></label>
      </div>
      <div className="modal-foot" style={{ padding: 0, borderTop: "none", justifyContent: "flex-start" }}>
        <button className="btn btn-primary" disabled={!current || !next || passwordMutation.isPending} onClick={submit}>
          Сменить пароль
        </button>
      </div>
    </section>
  );
}
