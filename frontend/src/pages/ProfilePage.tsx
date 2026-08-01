import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { changeOwnPassword, fetchCurrentUser, requestTelegramLinkCode, unlinkTelegram } from "../api/auth";
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

      <div className="panel" style={{ maxWidth: 520 }}>
        <div className="panel-head">
          <h2>Уведомления в Telegram</h2>
        </div>
        <p className="muted">
          Привяжите личный Telegram, чтобы получать уведомления о нарушении SLA по вашим заявкам напрямую в мессенджер
          — в дополнение к колокольчику в панели.
        </p>

        {user.telegram_id ? (
          <>
            <p>
              <span className="status-tag status-resolved">Привязан</span>
            </p>
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
