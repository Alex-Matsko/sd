import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createAsset, listAssets, listOrganizations } from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { ASSET_TYPE_LABELS } from "../../lib/labels";
import type { AssetType } from "../../api/types";

export function AssetsPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const assetsQuery = useQuery({ queryKey: ["assets-all"], queryFn: () => listAssets() });

  if (assetsQuery.isLoading || orgsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (assetsQuery.isError) return <div className="view"><ErrorBanner message={(assetsQuery.error as Error).message} /></div>;

  const orgsById = new Map((orgsQuery.data ?? []).map((o) => [o.id, o]));
  const assets = assetsQuery.data ?? [];

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Активы
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          Добавить актив
        </button>
      </div>

      {assets.length === 0 && <EmptyState text="Активов пока нет" />}
      {assets.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "2fr 1.2fr 1.6fr" }}>
            <span>Актив</span>
            <span>Тип</span>
            <span>Организация</span>
          </div>
          {assets.map((a) => (
            <div className="list-row" style={{ gridTemplateColumns: "2fr 1.2fr 1.6fr" }} key={a.id}>
              <span className="subject">{a.name}</span>
              <span>{ASSET_TYPE_LABELS[a.type]}</span>
              <span>{orgsById.get(a.organization_id)?.name ?? "—"}</span>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <NewAssetModal
          organizations={orgsQuery.data ?? []}
          onClose={() => setShowModal(false)}
          onCreated={() => {
            setShowModal(false);
            qc.invalidateQueries({ queryKey: ["assets-all"] });
          }}
        />
      )}
    </div>
  );
}

function NewAssetModal({
  organizations,
  onClose,
  onCreated,
}: {
  organizations: { id: number; name: string }[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [organizationId, setOrganizationId] = useState<number | null>(organizations[0]?.id ?? null);
  const [type, setType] = useState<AssetType>("server");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!organizationId || !name.trim()) {
      setError("Укажите организацию и название актива");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createAsset({ organization_id: organizationId, type, name });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось создать актив");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Новый актив</h3>
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
          <div className="form-row">
            <label className="form-label">Тип</label>
            <select value={type} onChange={(e) => setType(e.target.value as AssetType)}>
              {Object.entries(ASSET_TYPE_LABELS).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label">Название</label>
            <input type="text" style={{ width: "100%" }} value={name} onChange={(e) => setName(e.target.value)} />
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
