import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createUser, listUsers, updateUser } from "../../api/endpoints";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { IconEye, IconEyeOff } from "../../components/icons";
import { USER_ROLE_LABELS } from "../../lib/labels";
import type { User, UserRole } from "../../api/types";

const ROLES: UserRole[] = ["engineer", "dispatcher", "manager", "admin"];

export function UsersPage() {
  const qc = useQueryClient();
  const { user: currentUser } = useAuth();
  const [showModal, setShowModal] = useState(false);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [notice, setNotice] = useState("");

  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });

  const toggleActiveMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => updateUser(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
  const roleMutation = useMutation({
    mutationFn: ({ id, role }: { id: number; role: UserRole }) => updateUser(id, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  if (usersQuery.isLoading) return <div className="view"><Loading /></div>;
  if (usersQuery.isError) return <div className="view"><ErrorBanner message={(usersQuery.error as Error).message} /></div>;

  const users = usersQuery.data ?? [];
  const isAdmin = currentUser?.role === "admin";
  const mutationError = (toggleActiveMutation.error ?? roleMutation.error) as Error | null;

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Сотрудники
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          Добавить сотрудника
        </button>
      </div>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Роль администратора назначает только администратор. Деактивированный сотрудник не может войти в систему, но
        остаётся в истории заявок.
      </p>

      {mutationError && <ErrorBanner message={mutationError.message} />}
      {notice && <div className="user-reset-notice" role="status">{notice}</div>}

      {users.length === 0 && <EmptyState text="Сотрудников пока нет" />}
      {users.length > 0 && (
        <div className="list users-list">
          <div className="list-head">
            <span>Сотрудник</span>
            <span>Роль</span>
            <span>Telegram</span>
            <span>Статус</span>
            <span>Действия</span>
          </div>
          {users.map((u) => {
            // The API refuses these for non-admins anyway; disabling here
            // keeps the UI from offering an action that can only 403.
            const locked = u.role === "admin" && !isAdmin;
            return (
              <div className="list-row" key={u.id}>
                <span className="user-identity">
                  <strong>{u.full_name}{u.id === currentUser?.id && <span className="muted"> · это вы</span>}</strong>
                  <span className="muted">{u.email}</span>
                </span>
                <span>
                  <select
                    aria-label={`Роль: ${u.full_name}`}
                    value={u.role}
                    disabled={locked || roleMutation.isPending}
                    onChange={(e) => roleMutation.mutate({ id: u.id, role: e.target.value as UserRole })}
                  >
                    {ROLES.map((role) => (
                      <option key={role} value={role} disabled={role === "admin" && !isAdmin}>
                        {USER_ROLE_LABELS[role]}
                      </option>
                    ))}
                  </select>
                </span>
                <span className="muted">{u.telegram_id ? "привязан" : "—"}</span>
                <span>
                  {u.id === currentUser?.id ? (
                    <span className="muted">активен</span>
                  ) : (
                    <button
                      className="btn-link"
                      disabled={locked || toggleActiveMutation.isPending}
                      onClick={() => toggleActiveMutation.mutate({ id: u.id, is_active: !u.is_active })}
                    >
                      {u.is_active ? "Деактивировать" : "Активировать"}
                    </button>
                  )}
                </span>
                <span>
                  {u.id === currentUser?.id ? <Link to="/profile" className="btn-link">Сменить свой пароль</Link> : !locked && <button type="button" className="btn btn-ghost" aria-label={`Сбросить пароль: ${u.full_name}`} onClick={() => {setNotice(""); setResetTarget(u);}}>Сбросить пароль</button>}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {resetTarget && (
        <ResetPasswordModal
          target={resetTarget}
          onClose={() => setResetTarget(null)}
          onReset={() => {
            setNotice(`Пароль сотрудника «${resetTarget.full_name}» сброшен. Передайте ему новый пароль безопасным способом.`);
            setResetTarget(null);
            qc.invalidateQueries({queryKey: ["users"]});
          }}
        />
      )}

      {showModal && (
        <NewUserModal
          canCreateAdmin={isAdmin}
          onClose={() => setShowModal(false)}
          onCreated={() => {
            setShowModal(false);
            qc.invalidateQueries({ queryKey: ["users"] });
          }}
        />
      )}
    </div>
  );
}

function ResetPasswordModal({target, onClose, onReset}: {target: User; onClose: () => void; onReset: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const passwordInput = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement;
    element?.showModal();
    passwordInput.current?.focus();
    return () => {element?.close(); if(previous instanceof HTMLElement && previous.isConnected) previous.focus();};
  }, []);
  const mutation = useMutation({
    mutationFn: () => updateUser(target.id, {password}),
    onSuccess: () => {setPassword(""); setRepeat(""); onReset();},
    onError: e => setError(e.message),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if(password.length < 8) {setError("Новый пароль должен быть не короче 8 символов"); return;}
    if(new TextEncoder().encode(password).length > 72) {setError("Пароль слишком длинный: максимум 72 байта UTF-8"); return;}
    if(password !== repeat) {setError("Пароль и подтверждение не совпадают"); return;}
    setError("");
    mutation.mutate();
  }
  return <dialog ref={dialog} className="modal user-reset-dialog" aria-labelledby="reset-password-title" onCancel={event => {event.preventDefault(); if(!mutation.isPending) onClose();}}>
    <form onSubmit={submit}>
      <div className="modal-head"><h3 id="reset-password-title">Сброс пароля сотрудника</h3><button type="button" className="icon-btn" aria-label="Закрыть сброс пароля" disabled={mutation.isPending} onClick={onClose}>×</button></div>
      <div className="modal-body">
        <div className="user-reset-target"><strong>{target.full_name}</strong><span className="muted">{target.email}</span></div>
        <p className="muted">Задайте новый пароль вместо прежнего. Текущий пароль сотрудника не требуется.</p>
        {error && <ErrorBanner message={error}/>}
        <div className="form-row"><label className="form-label" htmlFor="reset-user-password">Новый пароль</label><div className="password-control"><input ref={passwordInput} id="reset-user-password" type={visible ? "text" : "password"} value={password} autoComplete="new-password" minLength={8} required disabled={mutation.isPending} onChange={event => {setPassword(event.target.value); setError("");}}/><button type="button" className="password-toggle" aria-label={visible ? "Скрыть новый пароль" : "Показать новый пароль"} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <IconEyeOff size={18}/> : <IconEye size={18}/>}</button></div></div>
        <div className="form-row"><label className="form-label" htmlFor="repeat-user-password">Повторите новый пароль</label><input id="repeat-user-password" type={visible ? "text" : "password"} value={repeat} autoComplete="new-password" minLength={8} required disabled={mutation.isPending} onChange={event => {setRepeat(event.target.value); setError("");}}/></div>
        <p className="muted">После сброса сотрудник сможет войти с новым паролем. Уведомления с паролем автоматически не отправляются.</p>
      </div>
      <div className="modal-foot"><button type="button" className="btn" disabled={mutation.isPending} onClick={onClose}>Отмена</button><button type="submit" className="btn btn-primary" disabled={mutation.isPending || !password || !repeat}>{mutation.isPending ? "Сбрасываем…" : "Сбросить пароль"}</button></div>
    </form>
  </dialog>;
}

function NewUserModal({
  canCreateAdmin,
  onClose,
  onCreated,
}: {
  canCreateAdmin: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("engineer");
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () => createUser({ full_name: fullName.trim(), email: email.trim(), password, role }),
    onSuccess: onCreated,
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось создать сотрудника"),
  });

  function handleSubmit() {
    if (!fullName.trim() || !email.trim() || password.length < 8) {
      setError("Заполните ФИО, email и пароль (не короче 8 символов)");
      return;
    }
    setError(null);
    createMutation.mutate();
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Новый сотрудник</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}
          <div className="form-row">
            <label className="form-label">ФИО</label>
            <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </div>
          <div className="form-row">
            <label className="form-label">Email (логин)</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="form-grid">
            <div className="form-row">
              <label className="form-label">Пароль</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <div className="form-row">
              <label className="form-label">Роль</label>
              <select value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
                {ROLES.map((r) => (
                  <option key={r} value={r} disabled={r === "admin" && !canCreateAdmin}>
                    {USER_ROLE_LABELS[r]}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <p className="muted">Сотрудник сможет сменить пароль сам в разделе «Профиль».</p>
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={createMutation.isPending}>
            Создать
          </button>
        </div>
      </div>
    </div>
  );
}
