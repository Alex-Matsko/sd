import type { Channel, Priority, SlaTimerState, TicketSlaView, TicketStatus } from "../api/types";
import { CHANNEL_LABELS, PRIORITY_LABELS, SLA_STATE_LABELS, STATUS_LABELS } from "../lib/labels";
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

// Worst-of-both-timers dot for the queue's SLA column (section 8: зелёный/жёлтый/красный).
// Priority when both timers are active: a breach always wins, then a warning, then paused.
const SLA_DOT_ORDER: SlaTimerState[] = ["breached", "warning", "paused", "ok", "met", "no_rule"];
const SLA_DOT_CLASS: Record<SlaTimerState, string> = {
  no_rule: "sla-dot-none",
  ok: "sla-dot-ok",
  warning: "sla-dot-warning",
  breached: "sla-dot-breached",
  met: "sla-dot-ok",
  paused: "sla-dot-paused",
};

function worstSlaState(sla: TicketSlaView): SlaTimerState {
  const states = [sla.reaction.state, sla.resolution.state];
  for (const candidate of SLA_DOT_ORDER) {
    if (states.includes(candidate)) return candidate;
  }
  return "no_rule";
}

export function SlaTag({ sla }: { sla: TicketSlaView | null | undefined }) {
  if (!sla) return <span className="muted">—</span>;
  const state = worstSlaState(sla);
  return (
    <span className={`sla-tag ${SLA_DOT_CLASS[state]}`} title={SLA_STATE_LABELS[state]}>
      <span className="dot" />
      {SLA_STATE_LABELS[state]}
    </span>
  );
}

const SLA_TIMER_CLASS: Record<SlaTimerState, string> = SLA_DOT_CLASS;

export function SlaTimerBadge({ label, timer }: { label: string; timer: { state: SlaTimerState; progress_pct: number | null } }) {
  return (
    <span className={`sla-tag ${SLA_TIMER_CLASS[timer.state]}`}>
      <span className="dot" />
      {label}: {SLA_STATE_LABELS[timer.state]}
      {timer.progress_pct !== null && timer.state !== "met" ? ` (${timer.progress_pct}%)` : ""}
    </span>
  );
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
