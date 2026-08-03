import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getMonitoringSettings,
  listContacts,
  listMonitoringAlerts,
  listOrganizations,
  updateMonitoringSettings,
  type MonitoringSettings,
} from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { formatDateTime } from "../../lib/labels";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? window.location.origin;

/** Подписи к полям входящего JSON. Ключ — то, что нужно SD; значение —
 *  как поле называется в присланном событии. */
const FIELD_LABELS: Record<string, string> = {
  external_id: "Идентификатор события",
  subject: "Тема",
  body: "Описание",
  severity: "Важность",
  host: "Узел",
  organization: "Организация",
  status: "Статус (проблема / восстановление)",
};

const SEVERITY_HINT = [
  ["disaster, critical", "P1"],
  ["high", "P2"],
  ["average, warning", "P3"],
  ["information", "P4"],
];

export function MonitoringPage() {
  const settingsQuery = useQuery({ queryKey: ["monitoring-settings"], queryFn: getMonitoringSettings });

  if (settingsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (settingsQuery.isError) {
    return <div className="view"><ErrorBanner message={(settingsQuery.error as Error).message} /></div>;
  }

  return (
    <div className="view">
      <h1 className="view-title">Мониторинг</h1>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Zabbix (или другая система) присылает событие вебхуком — SD заводит по нему заявку в общую очередь.
        Восстановление переводит заявку в «Решена». Подробная инструкция по настройке на стороне Zabbix — в{" "}
        <code>docs/monitoring.md</code>.
      </p>

      {/* key по updated_at: после сохранения форма пересоздаётся с сервера,
          иначе поля остались бы с тем, что успел натыкать пользователь. */}
      <MonitoringForm key={settingsQuery.data!.updated_at} settings={settingsQuery.data!} />
      <RecentAlerts />
    </div>
  );
}

function MonitoringForm({ settings }: { settings: MonitoringSettings }) {
  const qc = useQueryClient();
  const [isEnabled, setIsEnabled] = useState(settings.is_enabled);
  const [autoResolve, setAutoResolve] = useState(settings.auto_resolve);
  const [fieldMap, setFieldMap] = useState(settings.field_map);
  const [secret, setSecret] = useState("");
  const [secretCleared, setSecretCleared] = useState(false);
  const [orgId, setOrgId] = useState<number | "">("");
  const [contactId, setContactId] = useState<number | "">(settings.default_contact_id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: () => listOrganizations() });
  // Контакт по умолчанию выбирается через организацию: списка всех контактов
  // по всем клиентам одним селектом не выбрать.
  const contactsQuery = useQuery({
    queryKey: ["contacts", orgId],
    queryFn: () => listContacts(orgId as number),
    enabled: orgId !== "",
  });
  const currentContactQuery = useQuery({
    queryKey: ["contact-name", settings.default_contact_id],
    queryFn: () => listContacts(),
    enabled: settings.default_contact_id !== null,
  });
  const currentContactName = (currentContactQuery.data ?? []).find(
    (c) => c.id === settings.default_contact_id
  )?.full_name;

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: Parameters<typeof updateMonitoringSettings>[0] = {
        is_enabled: isEnabled,
        auto_resolve: autoResolve,
        field_map: fieldMap,
        default_contact_id: contactId === "" ? null : contactId,
      };
      // Ключ вообще не передаётся, когда секрет не трогали: иначе сохранение
      // формы стирало бы уже заданный секрет.
      if (secretCleared) payload.webhook_secret = null;
      else if (secret) payload.webhook_secret = secret;
      return updateMonitoringSettings(payload);
    },
    onSuccess: () => {
      setError(null);
      setSaved(true);
      qc.invalidateQueries({ queryKey: ["monitoring-settings"] });
    },
    onError: (e) => {
      setSaved(false);
      setError(e instanceof Error ? e.message : "Не удалось сохранить настройки");
    },
  });

  const webhookUrl = `${API_BASE}/webhooks/monitoring`;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Приём событий</h2>
        <div className="spacer" />
        <label className="form-row-inline" style={{ marginBottom: 0 }}>
          <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} />
          Интеграция включена
        </label>
      </div>
      <p className="muted">Изменено: {formatDateTime(settings.updated_at)}</p>

      {error && <ErrorBanner message={error} />}
      {saved && !error && <div className="success-banner">Настройки сохранены</div>}

      <div className="form-row">
        <label className="form-label">Адрес вебхука (указать в Zabbix)</label>
        <input type="text" readOnly value={webhookUrl} className="mono" />
      </div>

      <div className="form-row">
        <label className="form-label">Секрет вебхука (заголовок X-Webhook-Secret)</label>
        <div className="form-row-inline" style={{ marginBottom: 0 }}>
          <input
            type="password"
            style={{ flex: 1 }}
            placeholder={
              secretCleared
                ? "будет снят при сохранении"
                : settings.webhook_secret_set
                  ? "•••• (задан, оставьте пустым чтобы не менять)"
                  : "не задан — вебхук открыт для всех"
            }
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
          />
          {settings.webhook_secret_set && !secretCleared && (
            <button type="button" className="btn-link" onClick={() => setSecretCleared(true)}>
              Снять
            </button>
          )}
        </div>
        <span className="muted" style={{ fontSize: 12 }}>
          Только латиница, цифры и знаки препинания: секрет передаётся HTTP-заголовком, где кириллица не проходит.
        </span>
      </div>

      <div className="form-row form-row-inline" style={{ alignItems: "center" }}>
        <input
          id="auto-resolve"
          type="checkbox"
          checked={autoResolve}
          onChange={(e) => setAutoResolve(e.target.checked)}
        />
        <label htmlFor="auto-resolve">Переводить заявку в «Решена» при восстановлении</label>
      </div>

      <h3 className="form-section">Контакт по умолчанию</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        На него вешаются алерты, для которых не удалось определить организацию. Если не задан — такие заявки уходят
        в очередь «Неизвестные» на служебный контакт «Система мониторинга».
        {currentContactName && ` Сейчас: ${currentContactName}.`}
      </p>
      <div className="form-row-inline">
        <div className="form-row" style={{ flex: 1 }}>
          <label className="form-label">Организация</label>
          <select
            value={orgId}
            onChange={(e) => {
              setOrgId(e.target.value ? Number(e.target.value) : "");
              setContactId("");
            }}
          >
            <option value="">Не выбрана</option>
            {(orgsQuery.data ?? []).map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </div>
        <div className="form-row" style={{ flex: 1 }}>
          <label className="form-label">Контакт</label>
          <select
            value={contactId}
            disabled={orgId === ""}
            onChange={(e) => setContactId(e.target.value ? Number(e.target.value) : "")}
          >
            <option value="">{orgId === "" ? "Сначала выберите организацию" : "Очередь «Неизвестные»"}</option>
            {(contactsQuery.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.full_name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <h3 className="form-section">Имена полей в событии</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Слева — что нужно SD, справа — как это поле называется в вашем JSON. Меняйте, только если шаблон Zabbix
        присылает поля под другими именами.
      </p>
      <div className="form-grid">
        {Object.entries(FIELD_LABELS).map(([key, label]) => (
          <div className="form-row" key={key}>
            <label className="form-label">{label}</label>
            <input
              type="text"
              className="mono"
              value={fieldMap[key] ?? ""}
              onChange={(e) => setFieldMap({ ...fieldMap, [key]: e.target.value })}
            />
          </div>
        ))}
      </div>

      <h3 className="form-section">Как трактуется важность</h3>
      <div className="severity-hint">
        {SEVERITY_HINT.map(([from, to]) => (
          <span key={from}>
            <code>{from}</code> → {to}
          </span>
        ))}
        <span className="muted">незнакомая или пустая → P3</span>
      </div>

      <div className="form-row-inline" style={{ justifyContent: "flex-end", marginTop: 18 }}>
        <button className="btn btn-primary" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
          Сохранить
        </button>
      </div>
    </div>
  );
}

function RecentAlerts() {
  const alertsQuery = useQuery({
    queryKey: ["monitoring-alerts"],
    queryFn: () => listMonitoringAlerts({ limit: 15 }),
    refetchInterval: 60_000,
  });

  const alerts = alertsQuery.data?.items ?? [];
  const columns = "1.3fr 1fr 100px 2fr 120px 150px";

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Последние события</h2>
        <span className="muted">
          {alertsQuery.data ? `всего ${alertsQuery.data.total}` : ""}
        </span>
      </div>
      {alerts.length === 0 && (
        <EmptyState text="Событий пока не было — проверьте, что вебхук настроен на стороне Zabbix" />
      )}
      {alerts.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: columns }}>
            <span>Событие</span>
            <span>Узел</span>
            <span>Важность</span>
            <span>Тема</span>
            <span>Заявка</span>
            <span>Состояние</span>
          </div>
          {alerts.map((a) => (
            <div className="list-row" style={{ gridTemplateColumns: columns }} key={a.id}>
              <span className="mono">{a.external_id}</span>
              <span className="muted">{a.host ?? "—"}</span>
              <span className="muted">{a.severity ?? "—"}</span>
              <span className="subject">{a.subject}</span>
              <span>
                {a.ticket_id ? (
                  <Link className="link" to={`/tickets/${a.ticket_id}`}>
                    открыть
                  </Link>
                ) : (
                  <span className="muted">—</span>
                )}
              </span>
              <span className="muted">
                {a.resolved_at ? `восстановлено ${formatDateTime(a.resolved_at)}` : "проблема"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
