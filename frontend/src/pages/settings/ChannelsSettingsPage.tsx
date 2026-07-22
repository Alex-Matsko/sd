import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listIntegrationSettings, updateIntegrationSetting } from "../../api/endpoints";
import { ErrorBanner, Loading } from "../../components/ui";
import { formatDateTime } from "../../lib/labels";
import type { Channel, EmailChannelConfig, IntegrationSetting } from "../../api/types";

const CHANNEL_TITLES: Partial<Record<Channel, string>> = {
  email: "Email",
  telegram: "Telegram",
  max: "MAX",
  phone: "Телефония (Plusofon)",
};

function SecretField({
  label,
  isSet,
  value,
  onChange,
  onClear,
  cleared,
}: {
  label: string;
  isSet: boolean;
  value: string;
  onChange: (v: string) => void;
  onClear: () => void;
  cleared: boolean;
}) {
  return (
    <div className="form-row">
      <label className="form-label">{label}</label>
      <div className="form-row-inline" style={{ marginBottom: 0 }}>
        <input
          type="password"
          style={{ flex: 1 }}
          placeholder={cleared ? "будет очищен при сохранении" : isSet ? "•••• (задан, оставьте пустым чтобы не менять)" : "не задан"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        {isSet && !cleared && (
          <button type="button" className="btn-link" onClick={onClear}>
            Очистить
          </button>
        )}
      </div>
    </div>
  );
}

function EmailChannelCard({ setting }: { setting: IntegrationSetting }) {
  const qc = useQueryClient();
  const cfg = setting.config as EmailChannelConfig;

  const [isEnabled, setIsEnabled] = useState(setting.is_enabled);
  const [imapHost, setImapHost] = useState(cfg.imap_host ?? "");
  const [imapPort, setImapPort] = useState(cfg.imap_port ?? 993);
  const [imapUseSsl, setImapUseSsl] = useState(cfg.imap_use_ssl ?? true);
  const [imapUsername, setImapUsername] = useState(cfg.imap_username ?? "");
  const [imapFolder, setImapFolder] = useState(cfg.imap_folder ?? "INBOX");
  const [smtpHost, setSmtpHost] = useState(cfg.smtp_host ?? "");
  const [smtpPort, setSmtpPort] = useState(cfg.smtp_port ?? 587);
  const [smtpUseTls, setSmtpUseTls] = useState(cfg.smtp_use_tls ?? true);
  const [smtpUsername, setSmtpUsername] = useState(cfg.smtp_username ?? "");
  const [fromAddress, setFromAddress] = useState(cfg.from_address ?? "");
  const [fromDisplayName, setFromDisplayName] = useState(cfg.from_display_name ?? "Открытые Горизонты");
  const [pollInterval, setPollInterval] = useState(cfg.poll_interval_seconds ?? 30);

  const [imapPassword, setImapPassword] = useState("");
  const [imapPasswordCleared, setImapPasswordCleared] = useState(false);
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpPasswordCleared, setSmtpPasswordCleared] = useState(false);

  const isImapPasswordSet = setting.secret_keys_set.includes("imap_password");
  const isSmtpPasswordSet = setting.secret_keys_set.includes("smtp_password");

  const saveMutation = useMutation({
    mutationFn: () => {
      const secrets: Record<string, string | null> = {};
      if (imapPasswordCleared) secrets.imap_password = null;
      else if (imapPassword) secrets.imap_password = imapPassword;
      if (smtpPasswordCleared) secrets.smtp_password = null;
      else if (smtpPassword) secrets.smtp_password = smtpPassword;

      return updateIntegrationSetting("email", {
        is_enabled: isEnabled,
        config: {
          imap_host: imapHost,
          imap_port: Number(imapPort),
          imap_use_ssl: imapUseSsl,
          imap_username: imapUsername,
          imap_folder: imapFolder,
          smtp_host: smtpHost,
          smtp_port: Number(smtpPort),
          smtp_use_tls: smtpUseTls,
          smtp_username: smtpUsername,
          from_address: fromAddress,
          from_display_name: fromDisplayName,
          poll_interval_seconds: Number(pollInterval),
        },
        secrets: Object.keys(secrets).length > 0 ? secrets : undefined,
      });
    },
    onSuccess: () => {
      setImapPassword("");
      setImapPasswordCleared(false);
      setSmtpPassword("");
      setSmtpPasswordCleared(false);
      qc.invalidateQueries({ queryKey: ["integration-settings"] });
    },
  });

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Email</h2>
        <div className="spacer" />
        <label className="form-row-inline" style={{ marginBottom: 0 }}>
          <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} />
          Канал включён
        </label>
      </div>

      <p className="muted">
        Приём — IMAP-опрос ящика поддержки (интервал ≤ 60 сек), отправка — SMTP с тегом заявки в теме письма.
        Изменено: {formatDateTime(setting.updated_at)}.
      </p>

      <div className="form-grid">
        <div>
          <h3 className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
            Приём (IMAP)
          </h3>
          <div className="form-row">
            <label className="form-label">Хост</label>
            <input type="text" value={imapHost} onChange={(e) => setImapHost(e.target.value)} placeholder="imap.yandex.ru" />
          </div>
          <div className="form-row">
            <label className="form-label">Порт</label>
            <input type="number" value={imapPort} onChange={(e) => setImapPort(Number(e.target.value))} />
          </div>
          <div className="form-row-inline">
            <label>
              <input type="checkbox" checked={imapUseSsl} onChange={(e) => setImapUseSsl(e.target.checked)} /> SSL
            </label>
          </div>
          <div className="form-row">
            <label className="form-label">Логин</label>
            <input type="text" value={imapUsername} onChange={(e) => setImapUsername(e.target.value)} placeholder="support@o-horizons.com" />
          </div>
          <SecretField
            label="Пароль"
            isSet={isImapPasswordSet}
            value={imapPassword}
            onChange={setImapPassword}
            onClear={() => setImapPasswordCleared(true)}
            cleared={imapPasswordCleared}
          />
          <div className="form-row">
            <label className="form-label">Папка</label>
            <input type="text" value={imapFolder} onChange={(e) => setImapFolder(e.target.value)} />
          </div>
        </div>

        <div>
          <h3 className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
            Отправка (SMTP)
          </h3>
          <div className="form-row">
            <label className="form-label">Хост</label>
            <input type="text" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} placeholder="smtp.yandex.ru" />
          </div>
          <div className="form-row">
            <label className="form-label">Порт</label>
            <input type="number" value={smtpPort} onChange={(e) => setSmtpPort(Number(e.target.value))} />
          </div>
          <div className="form-row-inline">
            <label>
              <input type="checkbox" checked={smtpUseTls} onChange={(e) => setSmtpUseTls(e.target.checked)} /> STARTTLS
            </label>
          </div>
          <div className="form-row">
            <label className="form-label">Логин</label>
            <input type="text" value={smtpUsername} onChange={(e) => setSmtpUsername(e.target.value)} placeholder="support@o-horizons.com" />
          </div>
          <SecretField
            label="Пароль"
            isSet={isSmtpPasswordSet}
            value={smtpPassword}
            onChange={setSmtpPassword}
            onClear={() => setSmtpPasswordCleared(true)}
            cleared={smtpPasswordCleared}
          />
        </div>
      </div>

      <div className="form-grid">
        <div className="form-row">
          <label className="form-label">Адрес отправителя (From)</label>
          <input type="text" value={fromAddress} onChange={(e) => setFromAddress(e.target.value)} placeholder="support@o-horizons.com" />
        </div>
        <div className="form-row">
          <label className="form-label">Имя отправителя</label>
          <input type="text" value={fromDisplayName} onChange={(e) => setFromDisplayName(e.target.value)} />
        </div>
      </div>
      <div className="form-row" style={{ maxWidth: 220 }}>
        <label className="form-label">Интервал опроса, сек</label>
        <input type="number" min={10} value={pollInterval} onChange={(e) => setPollInterval(Number(e.target.value))} />
      </div>

      {saveMutation.isError && <ErrorBanner message={(saveMutation.error as Error).message} />}
      <div className="modal-foot" style={{ padding: 0, borderTop: "none", justifyContent: "flex-start" }}>
        <button className="btn btn-primary" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
          Сохранить
        </button>
      </div>
    </div>
  );
}

function PlaceholderChannelCard({ setting }: { setting: IntegrationSetting }) {
  const qc = useQueryClient();
  const [isEnabled, setIsEnabled] = useState(setting.is_enabled);

  useEffect(() => setIsEnabled(setting.is_enabled), [setting.is_enabled]);

  const toggleMutation = useMutation({
    mutationFn: (value: boolean) => updateIntegrationSetting(setting.channel, { is_enabled: value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["integration-settings"] }),
  });

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{CHANNEL_TITLES[setting.channel] ?? setting.channel}</h2>
        <div className="spacer" />
        <label className="form-row-inline" style={{ marginBottom: 0 }}>
          <input
            type="checkbox"
            checked={isEnabled}
            onChange={(e) => {
              setIsEnabled(e.target.checked);
              toggleMutation.mutate(e.target.checked);
            }}
          />
          Канал включён
        </label>
      </div>
      <p className="muted">
        Настройки подключения появятся здесь на следующем этапе разработки (см. план в README). Раздел уже готов
        принять их без миграции базы данных.
      </p>
    </div>
  );
}

export function ChannelsSettingsPage() {
  const settingsQuery = useQuery({ queryKey: ["integration-settings"], queryFn: listIntegrationSettings });

  if (settingsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (settingsQuery.isError) return <div className="view"><ErrorBanner message={(settingsQuery.error as Error).message} /></div>;

  const settings = settingsQuery.data ?? [];
  const email = settings.find((s) => s.channel === "email");
  const others = settings.filter((s) => s.channel !== "email");

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Каналы
        </h1>
      </div>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Учётные данные интеграций хранятся в базе данных (пароли — в зашифрованном виде), а не в файле конфигурации
        сервера — их можно менять здесь без переразвёртывания системы.
      </p>

      {email && <EmailChannelCard key={email.updated_at + "email"} setting={email} />}
      {others.map((s) => (
        <PlaceholderChannelCard key={s.channel} setting={s} />
      ))}
    </div>
  );
}
