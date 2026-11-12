import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { changeOwnPassword, fetchCurrentUser, requestTelegramLinkCode, unlinkTelegram, requestMaxLinkCode, unlinkMax, updateMaxNotifications, updateTelegramNotifications } from "../api/auth";
import { ErrorBanner, Loading } from "../components/ui";
import { USER_ROLE_LABELS, formatDateTime } from "../lib/labels";

export function ProfilePage() {
  const qc = useQueryClient();
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: fetchCurrentUser,
    // Poll while waiting for the client to send the code to the bot - stops
    // being useful (and stops firing) once telegram_id is set or the code
    // panel is closed, so this isn't a permanent background poll.
    refetchInterval: code ? 4_000 : false,
  });

  const codeMutation = useMutation({
    mutationFn: requestTelegramLinkCode,
    onSuccess: setCode,
  });

  const unlinkMutation = useMutation({
    mutationFn: unlinkTelegram,
    onSuccess: () => {
      setCode(null);
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });

  const telegramPreference = useMutation({ mutationFn: updateTelegramNotifications,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }) });

  if (meQuery.isLoading) return <div className="view"><Loading /></div>;
  if (meQuery.isError || !meQuery.data) {
    return <div className="view"><ErrorBanner message={(meQuery.error as Error)?.message ?? "Не удалось загрузить профиль"} /></div>;
  }

  const user = meQuery.data;
  if (user.telegram_id && code) setCode(null);

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Профиль
        </h1>
      </div>

      <div className="panel" style={{ maxWidth: 520 }}>
        <div className="panel-head">
          <h2>Учётная запись</h2>
        </div>
        <dl className="props-list">
          <dt>ФИО</dt>
          <dd>{user.full_name}</dd>
          <dt>Email</dt>
          <dd>{user.email}</dd>
          <dt>Роль</dt>
          <dd>{USER_ROLE_LABELS[user.role]}</dd>
        </dl>
      </div>

      <PasswordPanel />
      <MaxNotificationPanel />

      <div className="panel" style={{ maxWidth: 520 }}>
        <div className="panel-head">
          <h2>Уведомления в Telegram</h2>
        </div>
        <p className="muted">
          Новые заявки, назначения, ответы клиентов и риски SLA — прямо в Telegram. Выберите все заявки или только назначенные лично вам.
        </p>

        {user.telegram_id ? (
          <>
            <p>
              <span className="status-tag status-resolved">Привязан</span>
            </p>
            <label className="form-row">Какие заявки присылать<select aria-label="Уведомления Telegram" disabled={telegramPreference.isPending} value={telegramPreference.isPending ? telegramPreference.variables : user.role === "engineer" && user.telegram_notification_scope === "all" ? "assigned" : user.telegram_notification_scope} onChange={(event) => telegramPreference.mutate(event.target.value as "all" | "assigned" | "off")}>
              {user.role !== "engineer" && <option value="all">Все заявки, включая неразобранные</option>}<option value="assigned">Только назначенные мне</option><option value="off">Уведомления выключены</option>
            </select></label>
            {telegramPreference.isError && <ErrorBanner message={telegramPreference.error.message} />}
            {unlinkMutation.isError && <ErrorBanner message={(unlinkMutation.error as Error).message} />}
            <div className="modal-foot" style={{ padding: 0, borderTop: "none", justifyContent: "flex-start" }}>
              <button className="btn btn-ghost" disabled={unlinkMutation.isPending} onClick={() => unlinkMutation.mutate()}>
                Отвязать
              </button>
            </div>
          </>
        ) : (
          <>
            {codeMutation.isError && <ErrorBanner message={(codeMutation.error as Error).message} />}
            {code ? (
              <div className="panel" style={{ background: "var(--bg-sunken)" }}>
                <p>
                  Отправьте боту в Telegram сообщение: <code className="mono">/link {code.code}</code>
                </p>
                <p className="muted">Код действителен до {formatDateTime(code.expires_at)}. Ждём подтверждения…</p>
              </div>
            ) : (
              <div className="modal-foot" style={{ padding: 0, borderTop: "none", justifyContent: "flex-start" }}>
                <button className="btn btn-primary" disabled={codeMutation.isPending} onClick={() => codeMutation.mutate()}>
                  Получить код для привязки
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
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
    <div className="panel" style={{ maxWidth: 520 }}>
      <div className="panel-head">
        <h2>Смена пароля</h2>
      </div>
      {error && <ErrorBanner message={error} />}
      {done && <p className="muted">Пароль изменён. Другие ваши сессии завершены.</p>}
      <div className="form-row">
        <label className="form-label">Текущий пароль</label>
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
      </div>
      <div className="form-grid">
        <div className="form-row">
          <label className="form-label">Новый пароль</label>
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
        </div>
        <div className="form-row">
          <label className="form-label">Повторите новый</label>
          <input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} />
        </div>
      </div>
      <div className="modal-foot" style={{ padding: 0, borderTop: "none", justifyContent: "flex-start" }}>
        <button className="btn btn-primary" disabled={!current || !next || passwordMutation.isPending} onClick={submit}>
          Сменить пароль
        </button>
      </div>
    </div>
  );
}


function MaxNotificationPanel() {
  const qc = useQueryClient();
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyHelp, setCopyHelp] = useState(false);
  const codeElement = useRef<HTMLElement>(null);
  const me = useQuery({ queryKey: ["me"], queryFn: fetchCurrentUser, refetchInterval: (query) => code && !query.state.data?.max_linked ? 4_000 : false });
  const request = useMutation({ mutationFn: requestMaxLinkCode, onSuccess: (value) => { setCode(value); setCopied(false); setCopyHelp(false); } });
  const unlink = useMutation({ mutationFn: unlinkMax, onSuccess: () => { setCode(null); qc.invalidateQueries({ queryKey: ["me"] }); } });
  const preference = useMutation({ mutationFn: updateMaxNotifications, onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }) });
  const linked = Boolean(me.data?.max_linked);
  const fullQueue = me.data?.role !== "engineer";
  return <section className="panel max-notification-panel" aria-label="Уведомления в MAX">
    <div className="panel-head"><h2>Уведомления в MAX</h2><span className={`status-tag ${linked ? "status-resolved" : "status-closed"}`}>{linked ? "Привязан" : "Не привязан"}</span></div>
    <p className="muted">Получайте номер, тему, приоритет, клиента и ссылку на новую заявку прямо в MAX — из всех каналов service desk.</p>
    {(request.isError || unlink.isError || preference.isError) && <ErrorBanner message={(request.error ?? unlink.error ?? preference.error)?.message ?? "Не удалось изменить настройки"} />}
    {linked ? <>
      <label className="max-notification-option"><input type="checkbox" checked={preference.isPending ? Boolean(preference.variables) : me.data?.max_notify_new_tickets ?? false} disabled={preference.isPending} onChange={(event) => preference.mutate(event.target.checked)} /><span>{fullQueue ? "Уведомлять обо всех новых заявках" : "Уведомлять о новых назначенных мне заявках"}</span></label>
      <p className="muted">Уведомления включаются после привязки. Заявки, которые вы создаёте сами, повторно не присылаются.</p>
      <button type="button" className="btn btn-ghost" disabled={unlink.isPending} onClick={() => unlink.mutate()}>Отвязать MAX</button>
    </> : <>
      <ol className="max-link-steps"><li>Получите одноразовый код.</li><li>Откройте бота вашей службы поддержки в MAX.</li><li>Отправьте ему команду из блока ниже. Уведомления включатся автоматически.</li></ol>
      {code && <div className="max-link-code"><code ref={codeElement}>/link {code.code}</code><button type="button" className="btn btn-ghost" onClick={async () => { try { await navigator.clipboard.writeText(`/link ${code.code}`); setCopied(true); setCopyHelp(false); } catch { const range = document.createRange(); if (codeElement.current) { range.selectNodeContents(codeElement.current); window.getSelection()?.removeAllRanges(); window.getSelection()?.addRange(range); } setCopied(false); setCopyHelp(true); } }}>{copied ? "Скопировано" : "Копировать"}</button>{copyHelp && <p className="muted" role="status">Команда выделена. Скопируйте её через меню браузера или Ctrl/Cmd+C.</p>}<p className="muted">Код действует до {formatDateTime(code.expires_at)}. После отправки статус обновится автоматически.</p></div>}
      <button type="button" className="btn btn-primary" disabled={request.isPending} onClick={() => request.mutate()}>{code ? "Получить новый код" : "Получить код для MAX"}</button>
    </>}
  </section>;
}
