import type { Channel, Priority, TicketStatus } from "../api/types";
import { CHANNEL_LABELS, PRIORITY_LABELS, STATUS_LABELS } from "../lib/labels";
import { IconAlertTriangle } from "./icons";

export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.4 }}>
      {initials || "?"}
    </span>
  );
}

export function WhoMini({ name }: { name: string | null | undefined }) {
  if (!name) return <span className="who-mini muted">Не назначено</span>;
  return (
    <span className="who-mini">
      <Avatar name={name} size={22} />
      <span>{name}</span>
    </span>
  );
}

const PRIORITY_CLASS: Record<Priority, string> = {
  P1: "priority-p1",
  P2: "priority-p2",
  P3: "priority-p3",
  P4: "priority-p4",
};

export function PriorityTag({ priority }: { priority: Priority }) {
  return <span className={`priority-tag ${PRIORITY_CLASS[priority]}`}>{PRIORITY_LABELS[priority]}</span>;
}

const STATUS_CLASS: Record<TicketStatus, string> = {
  new: "status-new",
  assigned: "status-assigned",
  in_progress: "status-progress",
  waiting_customer: "status-waiting",
  waiting_third_party: "status-waiting",
  resolved: "status-resolved",
  closed: "status-closed",
  cancelled: "status-closed",
};

export function StatusTag({ status }: { status: TicketStatus }) {
  return (
    <span className={`status-tag ${STATUS_CLASS[status]}`}>
      <span className="dot" />
      {STATUS_LABELS[status]}
    </span>
  );
}

export function ChannelTag({ channel }: { channel: Channel }) {
  return <span className="channel-tag">{CHANNEL_LABELS[channel]}</span>;
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <p>{text}</p>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="error-banner">
      <IconAlertTriangle size={16} />
      <span>{message}</span>
    </div>
  );
}

export function Loading() {
  return <div className="loading">Загрузка…</div>;
}
