import { useState } from "react";
import { createOrganization } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ui";

export function NewOrganizationModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [legalName, setLegalName] = useState("");
  const [emailDomains, setEmailDomains] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!name.trim()) {
      setError("Укажите название организации");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createOrganization({
        name: name.trim(),
        legal_name: legalName.trim() || null,
        email_domains: emailDomains
          .split(",")
          .map((d) => d.trim().toLowerCase())
          .filter(Boolean),
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось создать организацию");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Новая организация</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}
          <div className="form-row">
            <label className="form-label">Название</label>
            <input type="text" style={{ width: "100%" }} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="form-row">
            <label className="form-label">Юридическое лицо</label>
            <input type="text" style={{ width: "100%" }} value={legalName} onChange={(e) => setLegalName(e.target.value)} />
          </div>
          <div className="form-row">
            <label className="form-label">Домены почты (через запятую)</label>
            <input
              type="text"
              style={{ width: "100%" }}
              placeholder="example.com, example.ru"
              value={emailDomains}
              onChange={(e) => setEmailDomains(e.target.value)}
            />
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
