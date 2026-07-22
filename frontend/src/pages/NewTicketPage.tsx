import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  createTicket,
  listAssets,
  listCategories,
  listContacts,
  listOrganizations,
} from "../api/endpoints";
import { ErrorBanner } from "../components/ui";
import { IMPACT_URGENCY_LABELS, PRIORITY_LABELS, TICKET_TYPE_LABELS, CHANNEL_LABELS } from "../lib/labels";
import type { Channel, ImpactUrgencyLevel, Priority, TicketType } from "../api/types";

type PriorityMode = "matrix" | "manual";

export function NewTicketPage() {
  const navigate = useNavigate();
  const [organizationId, setOrganizationId] = useState<number | "">("");
  const [contactId, setContactId] = useState<number | "">("");
  const [type, setType] = useState<TicketType>("incident");
  const [channel, setChannel] = useState<Channel>("portal");
  const [subject, setSubject] = useState("");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [assetId, setAssetId] = useState<number | "">("");
  const [priorityMode, setPriorityMode] = useState<PriorityMode>("matrix");
  const [impact, setImpact] = useState<ImpactUrgencyLevel>("medium");
  const [urgency, setUrgency] = useState<ImpactUrgencyLevel>("medium");
  const [manualPriority, setManualPriority] = useState<Priority>("P3");
  const [manualReason, setManualReason] = useState("");
  const [initialMessage, setInitialMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const contactsQuery = useQuery({
    queryKey: ["contacts", organizationId],
    queryFn: () => listContacts(organizationId ? Number(organizationId) : undefined),
    enabled: organizationId !== "",
  });
  const categoriesQuery = useQuery({ queryKey: ["categories"], queryFn: listCategories });
  const assetsQuery = useQuery({
    queryKey: ["assets", organizationId],
    queryFn: () => listAssets(organizationId ? Number(organizationId) : undefined),
    enabled: organizationId !== "",
  });

  async function handleSubmit() {
    if (!contactId) {
      setError("Выберите организацию и контакт");
      return;
    }
    if (!subject.trim()) {
      setError("Укажите тему заявки");
      return;
    }
    if (priorityMode === "manual" && !manualReason.trim()) {
      setError("При ручном приоритете нужно указать причину");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const ticket = await createTicket({
        contact_id: Number(contactId),
        type,
        channel,
        subject: subject.trim(),
        category_id: categoryId ? Number(categoryId) : null,
        asset_id: assetId ? Number(assetId) : null,
        impact: priorityMode === "matrix" ? impact : null,
        urgency: priorityMode === "matrix" ? urgency : null,
        manual_priority: priorityMode === "manual" ? manualPriority : null,
        manual_priority_reason: priorityMode === "manual" ? manualReason.trim() : null,
        initial_message: initialMessage.trim() || null,
      });
      navigate(`/tickets/${ticket.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось создать заявку");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="view">
      <h1 className="view-title">Новая заявка</h1>

      <div className="panel form-panel">
        {error && <ErrorBanner message={error} />}

        <div className="form-grid">
          <div className="form-row">
            <label className="form-label">Организация</label>
            <select
              value={organizationId}
              onChange={(e) => {
                setOrganizationId(e.target.value ? Number(e.target.value) : "");
                setContactId("");
              }}
            >
              <option value="">Выберите организацию</option>
              {(orgsQuery.data ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label">Контакт</label>
            <select value={contactId} onChange={(e) => setContactId(e.target.value ? Number(e.target.value) : "")} disabled={!organizationId}>
              <option value="">Выберите контакт</option>
              {(contactsQuery.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.full_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="form-grid">
          <div className="form-row">
            <label className="form-label">Тип</label>
            <select value={type} onChange={(e) => setType(e.target.value as TicketType)}>
              {Object.entries(TICKET_TYPE_LABELS).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label">Канал</label>
            <select value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
              {Object.entries(CHANNEL_LABELS).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="form-row">
          <label className="form-label">Тема</label>
          <input type="text" style={{ width: "100%" }} value={subject} onChange={(e) => setSubject(e.target.value)} />
        </div>

        <div className="form-grid">
          <div className="form-row">
            <label className="form-label">Категория</label>
            <select value={categoryId} onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Без категории</option>
              {(categoriesQuery.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label">Актив</label>
            <select value={assetId} onChange={(e) => setAssetId(e.target.value ? Number(e.target.value) : "")} disabled={!organizationId}>
              <option value="">Без привязки к активу</option>
              {(assetsQuery.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="priority-source">
          <div className="form-row-inline">
            <label>
              <input type="radio" checked={priorityMode === "matrix"} onChange={() => setPriorityMode("matrix")} /> Impact / Urgency
            </label>
            <label>
              <input type="radio" checked={priorityMode === "manual"} onChange={() => setPriorityMode("manual")} /> Приоритет вручную
            </label>
          </div>

          {priorityMode === "matrix" ? (
            <div className="form-grid">
              <div className="form-row">
                <label className="form-label">Impact</label>
                <select value={impact} onChange={(e) => setImpact(e.target.value as ImpactUrgencyLevel)}>
                  {Object.entries(IMPACT_URGENCY_LABELS).map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">Urgency</label>
                <select value={urgency} onChange={(e) => setUrgency(e.target.value as ImpactUrgencyLevel)}>
                  {Object.entries(IMPACT_URGENCY_LABELS).map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ) : (
            <>
              <div className="form-row">
                <label className="form-label">Приоритет</label>
                <select value={manualPriority} onChange={(e) => setManualPriority(e.target.value as Priority)}>
                  {Object.entries(PRIORITY_LABELS).map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">Причина ручного приоритета</label>
                <input type="text" style={{ width: "100%" }} value={manualReason} onChange={(e) => setManualReason(e.target.value)} />
              </div>
            </>
          )}
        </div>

        <div className="form-row">
          <label className="form-label">Первое сообщение</label>
          <textarea rows={4} value={initialMessage} onChange={(e) => setInitialMessage(e.target.value)} />
        </div>

        <div className="modal-foot" style={{ padding: 0, borderTop: "none" }}>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? "Создаём…" : "Создать заявку"}
          </button>
        </div>
      </div>
    </div>
  );
}
