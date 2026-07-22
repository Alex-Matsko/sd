import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listOrganizations } from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { ORGANIZATION_STATUS_LABELS } from "../../lib/labels";
import { NewOrganizationModal } from "./NewOrganizationModal";

export function OrganizationsPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });

  if (orgsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (orgsQuery.isError) return <div className="view"><ErrorBanner message={(orgsQuery.error as Error).message} /></div>;

  const organizations = orgsQuery.data ?? [];

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Организации
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          Добавить организацию
        </button>
      </div>

      {organizations.length === 0 && <EmptyState text="Организаций пока нет" />}
      {organizations.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "2fr 1.6fr 1fr 1.4fr" }}>
            <span>Название</span>
            <span>Юр. лицо</span>
            <span>Статус</span>
            <span>Домены почты</span>
          </div>
          {organizations.map((o) => (
            <div className="list-row" style={{ gridTemplateColumns: "2fr 1.6fr 1fr 1.4fr" }} key={o.id}>
              <span className="subject">{o.name}</span>
              <span>{o.legal_name ?? "—"}</span>
              <span>
                <span className={`status-tag ${o.status === "active" ? "status-resolved" : "status-new"}`}>
                  <span className="dot" />
                  {ORGANIZATION_STATUS_LABELS[o.status]}
                </span>
              </span>
              <span className="muted">{o.email_domains.map((d) => d.domain).join(", ") || "—"}</span>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <NewOrganizationModal
          onClose={() => setShowModal(false)}
          onCreated={() => {
            setShowModal(false);
            qc.invalidateQueries({ queryKey: ["organizations"] });
          }}
        />
      )}
    </div>
  );
}
