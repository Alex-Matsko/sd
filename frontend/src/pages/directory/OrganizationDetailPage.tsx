import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addOrganizationEmailDomain,
  getOrganization,
  getOrganizationUsage,
  listAssets,
  listContacts,
  listContracts,
  listTariffs,
  listTickets,
  listUsers,
  removeOrganizationEmailDomain,
  updateOrganization,
} from "../../api/endpoints";
import { ErrorBanner, Loading, PriorityTag, StatusTag, WhoMini } from "../../components/ui";
import {
  ASSET_TYPE_LABELS,
  CONTRACT_STATUS_LABELS,
  ORGANIZATION_STATUS_LABELS,
  formatDateTime,
  formatMinutes,
} from "../../lib/labels";
import type { OrganizationStatus } from "../../api/types";
import { NewContactModal } from "./ContactsPage";
import { NewContractModal } from "./ContractsPage";
import { NewAssetModal } from "./AssetsPage";

export function OrganizationDetailPage() {
  const { organizationId } = useParams();
  const id = Number(organizationId);
  const qc = useQueryClient();

  const orgQuery = useQuery({ queryKey: ["organization", id], queryFn: () => getOrganization(id), enabled: Number.isFinite(id) });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const contactsQuery = useQuery({ queryKey: ["contacts", id], queryFn: () => listContacts(id), enabled: Number.isFinite(id) });
  const contractsQuery = useQuery({ queryKey: ["contracts", id], queryFn: () => listContracts(id), enabled: Number.isFinite(id) });
  const tariffsQuery = useQuery({ queryKey: ["tariffs"], queryFn: listTariffs });
  const assetsQuery = useQuery({ queryKey: ["assets", id], queryFn: () => listAssets(id), enabled: Number.isFinite(id) });
  const ticketsQuery = useQuery({
    queryKey: ["tickets", "org", id],
    queryFn: () => listTickets({ organization_id: id, limit: 10 }),
    enabled: Number.isFinite(id),
  });
  const usageQuery = useQuery({
    queryKey: ["organization-usage", id],
    queryFn: () => getOrganizationUsage(id),
    enabled: Number.isFinite(id),
    retry: false,
  });

  const org = orgQuery.data;
  const orgTickets = ticketsQuery.data?.items ?? [];

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [legalName, setLegalName] = useState("");
  const [status, setStatus] = useState<OrganizationStatus>("active");
  const [accountManagerId, setAccountManagerId] = useState<number | "">("");
  const [newDomain, setNewDomain] = useState("");

  const [showContactModal, setShowContactModal] = useState(false);
  const [showContractModal, setShowContractModal] = useState(false);
  const [showAssetModal, setShowAssetModal] = useState(false);

  useEffect(() => {
    if (!org) return;
    setName(org.name);
    setLegalName(org.legal_name ?? "");
    setStatus(org.status);
    setAccountManagerId(org.account_manager_id ?? "");
  }, [org]);

  const saveMutation = useMutation({
    mutationFn: () =>
      updateOrganization(id, {
        name: name.trim(),
        legal_name: legalName.trim() || null,
        status,
        account_manager_id: accountManagerId || null,
      }),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["organization", id] });
      qc.invalidateQueries({ queryKey: ["organizations"] });
    },
  });

  const addDomainMutation = useMutation({
    mutationFn: () => addOrganizationEmailDomain(id, newDomain.trim().toLowerCase()),
    onSuccess: () => {
      setNewDomain("");
      qc.invalidateQueries({ queryKey: ["organization", id] });
    },
  });

  const removeDomainMutation = useMutation({
    mutationFn: (domainId: number) => removeOrganizationEmailDomain(id, domainId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["organization", id] }),
  });

  if (orgQuery.isLoading) return <div className="view"><Loading /></div>;
  if (orgQuery.isError || !org) return <div className="view"><ErrorBanner message={(orgQuery.error as Error)?.message ?? "Организация не найдена"} /></div>;

  const usersById = new Map((usersQuery.data ?? []).map((u) => [u.id, u]));
  const accountManager = org.account_manager_id ? usersById.get(org.account_manager_id) : undefined;

  return (
    <div className="view">
      <div className="toolbar">
        <Link to="/directory/organizations" className="link" style={{ fontSize: 12.5 }}>
          ← Организации
        </Link>
      </div>
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          {org.name}
        </h1>
        <span className={`status-tag ${org.status === "active" ? "status-resolved" : "status-new"}`}>
          <span className="dot" />
          {ORGANIZATION_STATUS_LABELS[org.status]}
        </span>
        <div className="spacer" />
        {!editing && (
          <button className="btn btn-ghost" onClick={() => setEditing(true)}>
            Редактировать
          </button>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Реквизиты</h2>
        </div>
        {editing ? (
          <>
            <div className="form-grid">
              <div className="form-row">
                <label className="form-label">Название</label>
                <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="form-row">
                <label className="form-label">Юридическое лицо</label>
                <input type="text" value={legalName} onChange={(e) => setLegalName(e.target.value)} />
              </div>
              <div className="form-row">
                <label className="form-label">Статус</label>
                <select value={status} onChange={(e) => setStatus(e.target.value as OrganizationStatus)}>
                  {Object.entries(ORGANIZATION_STATUS_LABELS).map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">Ответственный менеджер</label>
                <select value={accountManagerId} onChange={(e) => setAccountManagerId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Не назначен</option>
                  {(usersQuery.data ?? []).map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {saveMutation.isError && <ErrorBanner message={(saveMutation.error as Error).message} />}
            <div className="modal-foot" style={{ padding: 0, borderTop: "none", justifyContent: "flex-start" }}>
              <button className="btn btn-primary" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
                Сохранить
              </button>
              <button className="btn btn-ghost" onClick={() => setEditing(false)}>
                Отмена
              </button>
            </div>
          </>
        ) : (
          <dl className="props-list">
            <dt>Юридическое лицо</dt>
            <dd>{org.legal_name ?? "—"}</dd>
            <dt>Ответственный менеджер</dt>
            <dd>{accountManager ? <WhoMini name={accountManager.full_name} /> : "—"}</dd>
          </dl>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Домены почты для автопривязки</h2>
        </div>
        <p className="muted" style={{ marginTop: -6, fontSize: 12.5 }}>
          Письма с этих доменов автоматически привязываются к организации (раздел 2.3 ТЗ); контакт создаётся неподтверждённым.
        </p>
        <div className="tag-row" style={{ marginBottom: 10 }}>
          {org.email_domains.length === 0 && <span className="muted">Доменов не зарегистрировано</span>}
          {org.email_domains.map((d) => (
            <span key={d.id} className="channel-tag" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              {d.domain}
              <button
                className="icon-btn"
                style={{ width: 16, height: 16 }}
                title="Удалить домен"
                onClick={() => removeDomainMutation.mutate(d.id)}
              >
                ×
              </button>
            </span>
          ))}
        </div>
        {addDomainMutation.isError && <ErrorBanner message={(addDomainMutation.error as Error).message} />}
        <div className="form-row-inline">
          <input
            type="text"
            placeholder="example.ru"
            style={{ width: 220 }}
            value={newDomain}
            onChange={(e) => setNewDomain(e.target.value)}
          />
          <button className="btn btn-ghost" disabled={!newDomain.trim() || addDomainMutation.isPending} onClick={() => addDomainMutation.mutate()}>
            Добавить домен
          </button>
        </div>
      </div>

      {usageQuery.data && (
        <div className="panel">
          <div className="panel-head">
            <h2>Расход пакета часов, текущий месяц</h2>
          </div>
          <dl className="props-list">
            <dt>Пакет</dt>
            <dd>{formatMinutes(usageQuery.data.package_total_minutes)}</dd>
            <dt>Использовано</dt>
            <dd>{formatMinutes(usageQuery.data.package_used_minutes)}</dd>
            <dt>Остаток</dt>
            <dd>{formatMinutes(usageQuery.data.package_remaining_minutes)}</dd>
            <dt>Сверх лимита</dt>
            <dd>{formatMinutes(usageQuery.data.overage_minutes)} · {usageQuery.data.overage_cost} ₽</dd>
          </dl>
        </div>
      )}

      <div className="panel">
        <div className="panel-head">
          <h2>Контакты</h2>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={() => setShowContactModal(true)}>
            Добавить контакт
          </button>
        </div>
        {(contactsQuery.data ?? []).length === 0 && <p className="muted">Контактов пока нет</p>}
        {(contactsQuery.data ?? []).length > 0 && (
          <div className="list">
            <div className="list-head" style={{ gridTemplateColumns: "1.8fr 1.4fr 1fr 90px" }}>
              <span>Контакт</span>
              <span>Email</span>
              <span>Телефон</span>
              <span>VIP</span>
            </div>
            {(contactsQuery.data ?? []).map((c) => (
              <div className="list-row" style={{ gridTemplateColumns: "1.8fr 1.4fr 1fr 90px" }} key={c.id}>
                <span className="subject">
                  {c.full_name}
                  {c.position && <span className="muted"> · {c.position}</span>}
                  {!c.is_confirmed && <span className="muted"> (не подтверждён)</span>}
                </span>
                <span className="muted">{c.emails[0]?.email ?? "—"}</span>
                <span className="muted">{c.phones[0]?.phone ?? "—"}</span>
                <span>{c.is_vip ? "★" : ""}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Договоры</h2>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={() => setShowContractModal(true)}>
            Добавить договор
          </button>
        </div>
        {(contractsQuery.data ?? []).length === 0 && <p className="muted">Договоров пока нет</p>}
        {(contractsQuery.data ?? []).length > 0 && (
          <div className="list">
            <div className="list-head" style={{ gridTemplateColumns: "120px 1fr 1fr 1fr 1fr" }}>
              <span>№</span>
              <span>Пакет часов</span>
              <span>Сверх лимита</span>
              <span>Статус</span>
              <span>Начало</span>
            </div>
            {(contractsQuery.data ?? []).map((c) => (
              <div className="list-row" style={{ gridTemplateColumns: "120px 1fr 1fr 1fr 1fr" }} key={c.id}>
                <span className="mono">{c.number}</span>
                <span className="mono">{c.included_hours_per_month} ч/мес</span>
                <span className="mono">{c.overage_rate_per_hour} ₽/ч</span>
                <span>
                  <span className={`status-tag ${c.status === "active" ? "status-resolved" : "status-closed"}`}>
                    <span className="dot" />
                    {CONTRACT_STATUS_LABELS[c.status]}
                  </span>
                </span>
                <span className="muted">{c.start_date}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Активы</h2>
          <div className="spacer" />
          <button className="btn btn-ghost" onClick={() => setShowAssetModal(true)}>
            Добавить актив
          </button>
        </div>
        {(assetsQuery.data ?? []).length === 0 && <p className="muted">Активов пока нет</p>}
        {(assetsQuery.data ?? []).length > 0 && (
          <div className="list">
            <div className="list-head" style={{ gridTemplateColumns: "2fr 1fr" }}>
              <span>Актив</span>
              <span>Тип</span>
            </div>
            {(assetsQuery.data ?? []).map((a) => (
              <div className="list-row" style={{ gridTemplateColumns: "2fr 1fr" }} key={a.id}>
                <span className="subject">{a.name}</span>
                <span className="muted">{ASSET_TYPE_LABELS[a.type]}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Заявки</h2>
          <div className="spacer" />
          <Link className="link" style={{ fontSize: 12.5 }} to={`/tickets?organization_id=${id}`}>
            Вся очередь →
          </Link>
        </div>
        {orgTickets.length === 0 && <p className="muted">Заявок пока нет</p>}
        {orgTickets.length > 0 && (
          <div className="list">
            <div className="list-head" style={{ gridTemplateColumns: "90px 2fr 1fr 1fr" }}>
              <span>№</span>
              <span>Тема</span>
              <span>Приоритет</span>
              <span>Статус</span>
            </div>
            {orgTickets.map((t) => (
              <Link className="list-row" style={{ gridTemplateColumns: "90px 2fr 1fr 1fr" }} key={t.id} to={`/tickets/${t.id}`}>
                <span className="mono">{t.display_number}</span>
                <span className="subject">{t.subject}</span>
                <span>
                  <PriorityTag priority={t.priority} />
                </span>
                <span>
                  <StatusTag status={t.status} />
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>

      {showContactModal && (
        <NewContactModal
          organizations={[{ id: org.id, name: org.name }]}
          onClose={() => setShowContactModal(false)}
          onCreated={() => {
            setShowContactModal(false);
            qc.invalidateQueries({ queryKey: ["contacts", id] });
          }}
        />
      )}
      {showContractModal && (
        <NewContractModal
          organizations={[{ id: org.id, name: org.name }]}
          tariffs={tariffsQuery.data ?? []}
          onClose={() => setShowContractModal(false)}
          onCreated={() => {
            setShowContractModal(false);
            qc.invalidateQueries({ queryKey: ["contracts", id] });
          }}
        />
      )}
      {showAssetModal && (
        <NewAssetModal
          organizations={[{ id: org.id, name: org.name }]}
          onClose={() => setShowAssetModal(false)}
          onCreated={() => {
            setShowAssetModal(false);
            qc.invalidateQueries({ queryKey: ["assets", id] });
          }}
        />
      )}
    </div>
  );
}
