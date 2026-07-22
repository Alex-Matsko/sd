import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createTariff, listCalendars, listTariffs } from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { PRIORITY_LABELS } from "../../lib/labels";

export function TariffsPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const tariffsQuery = useQuery({ queryKey: ["tariffs"], queryFn: listTariffs });
  const calendarsQuery = useQuery({ queryKey: ["calendars"], queryFn: listCalendars });

  if (tariffsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (tariffsQuery.isError) return <div className="view"><ErrorBanner message={(tariffsQuery.error as Error).message} /></div>;

  const tariffs = tariffsQuery.data ?? [];

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Тарифы и SLA
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          Добавить тариф
        </button>
      </div>

      {tariffs.length === 0 && <EmptyState text="Тарифов пока нет" />}
      {tariffs.map((t) => (
        <div className="panel" key={t.id}>
          <div className="panel-head">
            <h2>
              {t.name} <span className="muted mono">({t.code})</span>
            </h2>
          </div>
          {t.description && <p className="muted">{t.description}</p>}
          <table className="matrix-table">
            <thead>
              <tr>
                <th>Приоритет</th>
                <th>Время реакции</th>
                <th>Время решения</th>
              </tr>
            </thead>
            <tbody>
              {t.sla_rules.map((rule) => (
                <tr key={rule.id}>
                  <td>{PRIORITY_LABELS[rule.priority]}</td>
                  <td className="mono">{rule.reaction_time_minutes} мин</td>
                  <td className="mono">{rule.resolution_time_minutes} мин</td>
                </tr>
              ))}
              {t.sla_rules.length === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    Правила SLA не заданы
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ))}

      {showModal && (
        <NewTariffModal
          calendars={calendarsQuery.data ?? []}
          onClose={() => setShowModal(false)}
          onCreated={() => {
            setShowModal(false);
            qc.invalidateQueries({ queryKey: ["tariffs"] });
          }}
        />
      )}
    </div>
  );
}

function NewTariffModal({
  calendars,
  onClose,
  onCreated,
}: {
  calendars: { id: number; name: string }[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [calendarId, setCalendarId] = useState<number | "">(calendars[0]?.id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!code.trim() || !name.trim() || !calendarId) {
      setError("Заполните код, название и рабочий календарь");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createTariff({ code: code.trim(), name: name.trim(), description: description.trim() || null, business_calendar_id: Number(calendarId) });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось создать тариф");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Новый тариф</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}
          <div className="form-grid">
            <div className="form-row">
              <label className="form-label">Код</label>
              <input type="text" value={code} onChange={(e) => setCode(e.target.value)} />
            </div>
            <div className="form-row">
              <label className="form-label">Название</label>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          </div>
          <div className="form-row">
            <label className="form-label">Рабочий календарь</label>
            <select value={calendarId} onChange={(e) => setCalendarId(e.target.value ? Number(e.target.value) : "")}>
              {calendars.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label">Описание</label>
            <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <p className="muted">Правила SLA по приоритетам можно настроить после создания тарифа.</p>
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
