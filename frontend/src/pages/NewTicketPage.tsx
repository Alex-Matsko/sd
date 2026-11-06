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

      <form className="panel form-panel" onSubmit={(event) => { event.preventDefault(); void handleSubmit(); }}>
        {error && <ErrorBanner message={error} />}

        <div className="form-grid">
          <div className="form-row">
            <label className="form-label" htmlFor="new-ticket-1">Организация</label>
            <select id="new-ticket-1"
              required
              value={organizationId}
              onChange={(e) => {
                setOrganizationId(e.target.value ? Number(e.target.value) : "");
                setContactId("");
                setAssetId("");
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
            <label className="form-label" htmlFor="new-ticket-2">Контакт</label>
            <select id="new-ticket-2" required value={contactId} onChange={(e) => setContactId(e.target.value ? Number(e.target.value) : "")} disabled={!organizationId}>
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
            <label className="form-label" htmlFor="new-ticket-3">Тип</label>
            <select id="new-ticket-3" value={type} onChange={(e) => setType(e.target.value as TicketType)}>
              {Object.entries(TICKET_TYPE_LABELS).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label" htmlFor="new-ticket-4">Канал</label>
            <select id="new-ticket-4" value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
              {Object.entries(CHANNEL_LABELS).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="form-row">
          <label className="form-label" htmlFor="new-ticket-5">Тема</label>
          <input id="new-ticket-5" type="text" required maxLength={500} style={{ width: "100%" }} value={subject} onChange={(e) => setSubject(e.target.value)} />
        </div>

        <div className="form-grid">
          <div className="form-row">
            <label className="form-label" htmlFor="new-ticket-6">Категория</label>
            <select id="new-ticket-6" value={categoryId} onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Без категории</option>
              {(categoriesQuery.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label" htmlFor="new-ticket-7">Актив</label>
            <select id="new-ticket-7" value={assetId} onChange={(e) => setAssetId(e.target.value ? Number(e.target.value) : "")} disabled={!organizationId}>
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
              <input type="radio" checked={priorityMode === "matrix"} onChange={() => setPriorityMode("matrix")} /> По влиянию и срочности
            </label>
            <label>
              <input type="radio" checked={priorityMode === "manual"} onChange={() => setPriorityMode("manual")} /> Приоритет вручную
            </label>
          </div>

          {priorityMode === "matrix" ? (
            <div className="form-grid">
              <div className="form-row">
                <label className="form-label" htmlFor="new-ticket-8">Влияние</label>
                <select id="new-ticket-8" value={impact} onChange={(e) => setImpact(e.target.value as ImpactUrgencyLevel)}>
                  {Object.entries(IMPACT_URGENCY_LABELS).map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label" htmlFor="new-ticket-9">Срочность</label>
                <select id="new-ticket-9" value={urgency} onChange={(e) => setUrgency(e.target.value as ImpactUrgencyLevel)}>
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
                <label className="form-label" htmlFor="new-ticket-10">Приоритет</label>
                <select id="new-ticket-10" value={manualPriority} onChange={(e) => setManualPriority(e.target.value as Priority)}>
                  {Object.entries(PRIORITY_LABELS).map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label" htmlFor="new-ticket-11">Причина ручного приоритета</label>
                <input id="new-ticket-11" type="text" style={{ width: "100%" }} value={manualReason} onChange={(e) => setManualReason(e.target.value)} />
              </div>
            </>
          )}
        </div>

        <div className="form-row">
          <label className="form-label" htmlFor="new-ticket-12">Первое сообщение</label>
          <textarea id="new-ticket-12" rows={4} value={initialMessage} onChange={(e) => setInitialMessage(e.target.value)} />
        </div>

        <div className="modal-foot" style={{ padding: 0, borderTop: "none" }}>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? "Создаём…" : "Создать заявку"}
          </button>
        </div>
      </form>
    </div>
  );
}
