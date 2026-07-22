import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContact, listContacts, listOrganizations } from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";

export function ContactsPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
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
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          Добавить контакт
        </button>
      </div>

      {contacts.length === 0 && <EmptyState text="Контактов пока нет" />}
      {contacts.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "1.8fr 1.6fr 1.4fr 1fr 90px" }}>
            <span>Контакт</span>
            <span>Организация</span>
            <span>Email</span>
            <span>Телефон</span>
            <span>VIP</span>
          </div>
          {contacts.map((c) => (
            <div className="list-row" style={{ gridTemplateColumns: "1.8fr 1.6fr 1.4fr 1fr 90px" }} key={c.id}>
              <span className="subject">
                {c.full_name}
                {c.position && <span className="muted"> · {c.position}</span>}
              </span>
              <span>{orgsById.get(c.organization_id)?.name ?? "—"}</span>
              <span className="muted">{c.emails[0]?.email ?? "—"}</span>
              <span className="muted">{c.phones[0]?.phone ?? "—"}</span>
              <span>{c.is_vip ? "★" : ""}</span>
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
    </div>
  );
}

function NewContactModal({
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
  const [isVip, setIsVip] = useState(false);
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
        is_vip: isVip,
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
          <div className="form-row form-row-inline">
            <label>
              <input type="checkbox" checked={isVip} onChange={(e) => setIsVip(e.target.checked)} /> VIP-контакт
            </label>
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
