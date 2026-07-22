import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContract, listContracts, listOrganizations, listTariffs } from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { CONTRACT_STATUS_LABELS } from "../../lib/labels";

export function ContractsPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const tariffsQuery = useQuery({ queryKey: ["tariffs"], queryFn: listTariffs });
  const contractsQuery = useQuery({ queryKey: ["contracts-all"], queryFn: () => listContracts() });

  if (contractsQuery.isLoading || orgsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (contractsQuery.isError) return <div className="view"><ErrorBanner message={(contractsQuery.error as Error).message} /></div>;

  const orgsById = new Map((orgsQuery.data ?? []).map((o) => [o.id, o]));
  const tariffsById = new Map((tariffsQuery.data ?? []).map((t) => [t.id, t]));
  const contracts = contractsQuery.data ?? [];

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Договоры
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          Добавить договор
        </button>
      </div>

      {contracts.length === 0 && <EmptyState text="Договоров пока нет" />}
      {contracts.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "120px 1.6fr 1fr 1fr 1fr 1fr" }}>
            <span>№ договора</span>
            <span>Организация</span>
            <span>Тариф</span>
            <span>Пакет часов</span>
            <span>Сверх лимита</span>
            <span>Статус</span>
          </div>
          {contracts.map((c) => (
            <div className="list-row" style={{ gridTemplateColumns: "120px 1.6fr 1fr 1fr 1fr 1fr" }} key={c.id}>
              <span className="mono">{c.number}</span>
              <span>{orgsById.get(c.organization_id)?.name ?? "—"}</span>
              <span>{tariffsById.get(c.tariff_id)?.name ?? "—"}</span>
              <span className="mono">{c.included_hours_per_month} ч/мес</span>
              <span className="mono">{c.overage_rate_per_hour} ₽/ч</span>
              <span>
                <span className={`status-tag ${c.status === "active" ? "status-resolved" : "status-new"}`}>
                  <span className="dot" />
                  {CONTRACT_STATUS_LABELS[c.status]}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <NewContractModal
          organizations={orgsQuery.data ?? []}
          tariffs={tariffsQuery.data ?? []}
          onClose={() => setShowModal(false)}
          onCreated={() => {
            setShowModal(false);
            qc.invalidateQueries({ queryKey: ["contracts-all"] });
          }}
        />
      )}
    </div>
  );
}

function NewContractModal({
  organizations,
  tariffs,
  onClose,
  onCreated,
}: {
  organizations: { id: number; name: string }[];
  tariffs: { id: number; name: string }[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [organizationId, setOrganizationId] = useState<number | null>(organizations[0]?.id ?? null);
  const [tariffId, setTariffId] = useState<number | null>(tariffs[0]?.id ?? null);
  const [number, setNumber] = useState("");
  const [hours, setHours] = useState(10);
  const [rate, setRate] = useState(1500);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!organizationId || !tariffId || !number.trim()) {
      setError("Заполните организацию, тариф и номер договора");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createContract({
        organization_id: organizationId,
        tariff_id: tariffId,
        number,
        start_date: new Date().toISOString().slice(0, 10),
        included_hours_per_month: hours,
        overage_rate_per_hour: rate,
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось создать договор");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Новый договор</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}
          <div className="form-grid">
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
            <div className="form-row">
              <label className="form-label">Тариф</label>
              <select value={tariffId ?? ""} onChange={(e) => setTariffId(Number(e.target.value))}>
                {tariffs.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-row">
            <label className="form-label">Номер договора</label>
            <input type="text" style={{ width: "100%" }} value={number} onChange={(e) => setNumber(e.target.value)} />
          </div>
          <div className="form-grid">
            <div className="form-row">
              <label className="form-label">Пакет часов/мес</label>
              <input type="number" value={hours} onChange={(e) => setHours(Number(e.target.value))} />
            </div>
            <div className="form-row">
              <label className="form-label">Ставка сверх лимита (₽/ч)</label>
              <input type="number" value={rate} onChange={(e) => setRate(Number(e.target.value))} />
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
