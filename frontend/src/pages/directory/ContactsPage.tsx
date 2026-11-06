import { useAuth } from "../../auth/AuthContext";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContact,
  listContacts,
  listOrganizations,
  mergeContact,
  revokePortalAccess,
  setPortalPassword,
  updateContact,
} from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import type { Contact } from "../../api/types";

export function ContactsPage() {
  const { user } = useAuth();
  const canManage = user?.role === "manager" || user?.role === "admin";
  const canEdit = canManage || user?.role === "dispatcher";
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [portalContact, setPortalContact] = useState<Contact | null>(null);
  const [mergingContact, setMergingContact] = useState<Contact | null>(null);
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const contactsQuery = useQuery({ queryKey: ["contacts-all"], queryFn: () => listContacts() });

  if (contactsQuery.isLoading || orgsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (contactsQuery.isError) return <div className="view"><ErrorBanner message={(contactsQuery.error as Error).message} /></div>;

  const orgsById = new Map((orgsQuery.data ?? []).map((o) => [o.id, o]));
  const contacts = contactsQuery.data ?? [];

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Контакты
        </h1>
        <div className="spacer" />
        {canEdit && <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          Добавить контакт
        </button>}
      </div>

      {contacts.length === 0 && <EmptyState text="Контактов пока нет" />}
      {contacts.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "1.7fr 1.4fr 1.4fr 1fr 150px 200px" }}>
            <span>Контакт</span>
            <span>Организация</span>
            <span>Email</span>
            <span>Телефон</span>
            <span>Личный кабинет</span>
            <span></span>
          </div>
          {contacts.map((c) => (
            <div className="list-row" style={{ gridTemplateColumns: "1.7fr 1.4fr 1.4fr 1fr 150px 200px" }} key={c.id}>
              <span className="subject">
                {c.full_name}
                {c.position && <span className="muted"> · {c.position}</span>}
                {!c.is_confirmed && <span className="muted"> · не подтверждён</span>}
              </span>
              <span>{orgsById.get(c.organization_id)?.name ?? "—"}</span>
              <span className="muted">{c.emails[0]?.email ?? "—"}</span>
              <span className="muted">{c.phones[0]?.phone ?? "—"}</span>
              <span className={c.has_portal_access ? "sent-mark" : "muted"}>
                {c.has_portal_access ? "доступ есть" : "нет доступа"}
              </span>
              <span style={{ display: "flex", gap: 10 }}>
                {canEdit && <button className="btn-link" onClick={() => setPortalContact(c)}>
                  Кабинет
                </button>}
                {canEdit && <button className="btn-link" onClick={() => setMergingContact(c)}>
                  Объединить
                </button>}
              </span>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <NewContactModal
          organizations={orgsQuery.data ?? []}
          onClose={() => setShowModal(false)}
          onCreated={() => {
            setShowModal(false);
            qc.invalidateQueries({ queryKey: ["contacts-all"] });
          }}
        />
      )}

      {portalContact && (
        <PortalAccessModal
          contact={portalContact}
          onClose={() => setPortalContact(null)}
          onChanged={() => {
            setPortalContact(null);
            // Список контактов живёт под ключом contacts-all; сброс
            // «contacts» его не касается, и строка оставалась со старым
            // признаком доступа. Сбрасываются оба: под «contacts» лежат
            // выборки по организации, которые тоже показывают этот признак.
            qc.invalidateQueries({ queryKey: ["contacts-all"] });
            qc.invalidateQueries({ queryKey: ["contacts"] });
          }}
        />
      )}

      {mergingContact && (
        <MergeContactModal
          contact={mergingContact}
          candidates={contacts.filter((c) => c.id !== mergingContact.id)}
          onClose={() => setMergingContact(null)}
          onMerged={() => {
            setMergingContact(null);
            qc.invalidateQueries({ queryKey: ["contacts-all"] });
          }}
        />
      )}
    </div>
  );
}

function MergeContactModal({
  contact,
  candidates,
  onClose,
  onMerged,
}: {
  contact: Contact;
  candidates: Contact[];
  onClose: () => void;
  onMerged: () => void;
}) {
  const [targetId, setTargetId] = useState<number | null>(candidates[0]?.id ?? null);

  const mergeMutation = useMutation({
    mutationFn: () => mergeContact(contact.id, targetId!),
    onSuccess: onMerged,
  });

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Объединить контакт</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <p className="muted">
            Заявки, сообщения и переписка контакта «{contact.full_name}» будут перенесены на выбранный контакт, а сам
            он — удалён. Действие необратимо.
          </p>
          {mergeMutation.isError && <ErrorBanner message={(mergeMutation.error as Error).message} />}
          <div className="form-row">
            <label className="form-label">Объединить с</label>
            <select value={targetId ?? ""} onChange={(e) => setTargetId(Number(e.target.value))}>
              {candidates.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.full_name} {c.emails[0] ? `(${c.emails[0].email})` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn-primary" disabled={!targetId || mergeMutation.isPending} onClick={() => mergeMutation.mutate()}>
            Объединить
          </button>
        </div>
      </div>
    </div>
  );
}

export function NewContactModal({
  organizations,
  onClose,
  onCreated,
}: {
  organizations: { id: number; name: string }[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [organizationId, setOrganizationId] = useState<number | null>(organizations[0]?.id ?? null);
  const [fullName, setFullName] = useState("");
  const [position, setPosition] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!organizationId || !fullName.trim()) {
      setError("Укажите организацию и ФИО контакта");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createContact({
        organization_id: organizationId,
        full_name: fullName.trim(),
        position: position.trim() || null,
        emails: email.trim() ? [email.trim()] : [],
        phones: phone.trim() ? [phone.trim()] : [],
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось создать контакт");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Новый контакт</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}
          <div className="form-row">
            <label className="form-label">Организация</label>
            <select value={organizationId ?? ""} onChange={(e) => setOrganizationId(Number(e.target.value))}>
              {organizations.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-grid">
            <div className="form-row">
              <label className="form-label">ФИО</label>
              <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div className="form-row">
              <label className="form-label">Должность</label>
              <input type="text" value={position} onChange={(e) => setPosition(e.target.value)} />
            </div>
          </div>
          <div className="form-grid">
            <div className="form-row">
              <label className="form-label">Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="form-row">
              <label className="form-label">Телефон</label>
              <input type="text" value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            Создать
          </button>
        </div>
      </div>
    </div>
  );
}


/** Доступ клиента в личный кабинет (ТЗ р. 7).
 *
 *  Логином служит email контакта, поэтому без адреса доступ выдать нельзя —
 *  форма говорит об этом прямо, а не отдаёт отказ сервера.
 */
function PortalAccessModal({
  contact,
  onClose,
  onChanged,
}: {
  contact: Contact;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [password, setPassword] = useState("");
  const [seesOrgTickets, setSeesOrgTickets] = useState(contact.can_view_org_tickets);
  const [error, setError] = useState<string | null>(null);

  const email = contact.emails.find((e) => e.is_primary)?.email ?? contact.emails[0]?.email ?? null;

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (password) await setPortalPassword(contact.id, password);
      if (seesOrgTickets !== contact.can_view_org_tickets) {
        await updateContact(contact.id, { can_view_org_tickets: seesOrgTickets });
      }
    },
    onSuccess: onChanged,
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось сохранить"),
  });

  const revokeMutation = useMutation({
    mutationFn: () => revokePortalAccess(contact.id),
    onSuccess: onChanged,
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось отозвать доступ"),
  });

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Личный кабинет — {contact.full_name}</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}

          {email === null ? (
            <p className="muted">
              У контакта нет email, а он служит логином в кабинете. Добавьте адрес — тогда можно будет выдать
              доступ.
            </p>
          ) : (
            <>
              <div className="form-row">
                <label className="form-label">Логин</label>
                <input type="text" readOnly value={email} className="mono" />
              </div>

              <div className="form-row">
                <label className="form-label">
                  {contact.has_portal_access ? "Новый пароль" : "Пароль"}
                </label>
                <input
                  type="text"
                  placeholder={contact.has_portal_access ? "оставьте пустым, чтобы не менять" : "не менее 8 символов"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <span className="muted" style={{ fontSize: 12 }}>
                  Пароль показан открыто, чтобы его можно было передать клиенту. Дальше он сможет входить и по
                  ссылке на почту, не запоминая его.
                </span>
              </div>

              <div className="form-row form-row-inline">
                <input
                  id="sees-org"
                  type="checkbox"
                  checked={seesOrgTickets}
                  onChange={(e) => setSeesOrgTickets(e.target.checked)}
                />
                <label htmlFor="sees-org">
                  Видит обращения всей организации
                  <span className="muted"> — иначе только свои</span>
                </label>
              </div>

              <p className="muted">
                {contact.has_portal_access
                  ? "Доступ выдан. Отзыв снимает пароль и неиспользованные ссылки для входа — это то, что нужно сделать, когда сотрудник клиента уволился."
                  : "Доступа нет. Задайте пароль — это и есть выдача доступа, в том числе повторная после отзыва."}
              </p>
            </>
          )}
        </div>
        <div className="modal-foot">
          {contact.has_portal_access && (
            <button
              className="btn-link"
              disabled={revokeMutation.isPending}
              onClick={() => {
                if (window.confirm(`Отозвать доступ в кабинет у ${contact.full_name}?`)) revokeMutation.mutate();
              }}
            >
              Отозвать доступ
            </button>
          )}
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn btn-primary"
            disabled={
              email === null ||
              saveMutation.isPending ||
              (password.length > 0 && password.length < 8) ||
              (!password && seesOrgTickets === contact.can_view_org_tickets)
            }
            onClick={() => saveMutation.mutate()}
          >
            {contact.has_portal_access ? "Сохранить" : "Выдать доступ"}
          </button>
        </div>
      </div>
    </div>
  );
}
