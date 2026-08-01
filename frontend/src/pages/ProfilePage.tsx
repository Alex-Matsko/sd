import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchCurrentUser, requestTelegramLinkCode, unlinkTelegram } from "../api/auth";
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
