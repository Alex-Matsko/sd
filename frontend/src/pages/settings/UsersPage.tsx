import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createUser, listUsers, updateUser } from "../../api/endpoints";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { USER_ROLE_LABELS } from "../../lib/labels";
import type { UserRole } from "../../api/types";

const ROLES: UserRole[] = ["engineer", "dispatcher", "manager", "admin"];

export function UsersPage() {
  const qc = useQueryClient();
  const { user: currentUser } = useAuth();
  const [showModal, setShowModal] = useState(false);

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

      {users.length === 0 && <EmptyState text="Сотрудников пока нет" />}
      {users.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "1.6fr 1.8fr 1.2fr 1fr 110px" }}>
            <span>Сотрудник</span>
            <span>Email</span>
            <span>Роль</span>
            <span>Telegram</span>
            <span>Статус</span>
          </div>
          {users.map((u) => {
            // The API refuses these for non-admins anyway; disabling here
            // keeps the UI from offering an action that can only 403.
            const locked = u.role === "admin" && !isAdmin;
            return (
              <div className="list-row" style={{ gridTemplateColumns: "1.6fr 1.8fr 1.2fr 1fr 110px" }} key={u.id}>
                <span className="subject">
                  {u.full_name}
                  {u.id === currentUser?.id && <span className="muted"> · это вы</span>}
                </span>
                <span className="muted">{u.email}</span>
                <span>
                  <select
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
              </div>
            );
          })}
        </div>
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
