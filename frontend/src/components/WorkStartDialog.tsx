import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Ticket } from "../api/types";

export type WorkPlan = { planned_due_at: string; estimated_minutes: number };
function localDate(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}T${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}
export function WorkStartDialog({ ticket, pending, error, onClose, onConfirm }: {
  ticket: Ticket; pending: boolean; error?: string; onClose: () => void; onConfirm: (plan: WorkPlan) => void;
}) {
  const expired = !!ticket.planned_due_at && new Date(ticket.planned_due_at).getTime() <= Date.now();
  const [due, setDue] = useState(expired ? "" : localDate(ticket.planned_due_at));
  const [hours, setHours] = useState(ticket.estimated_minutes ? String(Number((ticket.estimated_minutes/60).toFixed(2))) : "");
  const [validation, setValidation] = useState("");
  const ref = useRef<HTMLFormElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    node?.showModal();
    return () => { node?.close(); previous?.focus(); };
  }, []);
  function submit(event: React.FormEvent) {
    event.preventDefault();
    const minutes = Math.round(Number(hours.replace(",", ".")) * 60);
    if (!due || !Number.isFinite(new Date(due).getTime()) || new Date(due).getTime() <= Date.now()) { setValidation("Укажите срок выполнения в будущем."); return; }
    if (!hours.trim() || !Number.isFinite(minutes) || minutes < 1 || minutes > 600000) { setValidation("Укажите трудозатраты от 1 минуты до 10 000 часов."); return; }
    setValidation(""); onConfirm({ planned_due_at: new Date(due).toISOString(), estimated_minutes: minutes });
  }
  return createPortal(<dialog ref={dialog} className="work-start-dialog" aria-labelledby="work-start-title"
    onCancel={event => { event.preventDefault(); event.stopPropagation(); if (!pending) onClose(); }}
    onClick={event => { if (event.target === event.currentTarget && !pending) onClose(); }}>
    <form ref={ref} className="modal" onSubmit={submit} onKeyDown={event => {
      if (event.key === "Tab") {
        const items = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') ?? []);
        const first=items[0], last=items.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }}>
      <div className="modal-head"><h3 id="work-start-title">План перед началом работы</h3><button type="button" className="btn btn-ghost" aria-label="Закрыть план начала работы" disabled={pending} onClick={onClose}>×</button></div>
      <div className="modal-body">
        <strong>{ticket.display_number} — {ticket.subject}</strong>
        <p className="muted">Клиент увидит срок и оценку в заявке и уведомлении. Фактическое время учитывается отдельно.</p>
        {expired && <p className="muted" role="status">Предыдущий срок истёк. Укажите новый срок перед началом работы.</p>}
        <label className="form-row">Выполнить до *<input type="datetime-local" autoFocus required value={due} disabled={pending} onChange={e=>setDue(e.target.value)} /></label>
        <label className="form-row">Примерные трудозатраты, ч *<input type="number" required min="0.01" max="10000" step="any" placeholder="Например, 1.5" value={hours} disabled={pending} onChange={e=>setHours(e.target.value)} /></label>
        <p className="muted">Срок — в часовом поясе вашего устройства. 1,5 ч — это 1 ч 30 мин работы.</p>
        {(validation || error) && <p role="alert" className="rich-editor-error">{validation || error}</p>}
      </div>
      <div className="modal-foot"><button type="button" className="btn btn-ghost" disabled={pending} onClick={onClose}>Отмена</button><button className="btn btn-primary" disabled={pending}>{pending ? "Начинаем работу…" : "Подтвердить и начать"}</button></div>
    </form>
  </dialog>, document.body);
}
