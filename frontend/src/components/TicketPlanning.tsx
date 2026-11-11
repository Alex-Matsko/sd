import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { updateTicket } from "../api/endpoints";
import type { Ticket } from "../api/types";
import { formatDateTime, formatMinutes } from "../lib/labels";

function localInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
export function TicketPlanning({ ticket }: { ticket: Ticket }) {
  const [due, setDue] = useState(() => localInput(ticket.planned_due_at));
  const [hours, setHours] = useState(() => ticket.estimated_minutes === null ? "" : String(Number((ticket.estimated_minutes / 60).toFixed(2))));
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const qc = useQueryClient();
  useEffect(() => { if (!editing) { setDue(localInput(ticket.planned_due_at)); setHours(ticket.estimated_minutes === null ? "" : String(Number((ticket.estimated_minutes / 60).toFixed(2)))); } }, [ticket.planned_due_at, ticket.estimated_minutes, editing]);
  const save = useMutation({ mutationFn: (payload: { planned_due_at: string | null; estimated_minutes: number | null }) => updateTicket(ticket.id, payload),
    onSuccess: (next) => {
      qc.setQueryData(["ticket", ticket.id], next); setEditing(false);
      qc.invalidateQueries({ queryKey: ["tickets"] }); qc.invalidateQueries({ queryKey: ["ticket", ticket.id, "history"] });
      qc.invalidateQueries({ queryKey: ["portal-ticket", ticket.id] });
    } });
  function submit() {
    const amount = hours.trim() ? Number(hours.replace(",", ".")) : null;
    if (amount !== null && (!Number.isFinite(amount) || amount < 0 || amount > 10000)) { setError("Укажите трудозатраты от 0 до 10 000 часов"); return; }
    if (due && !Number.isFinite(new Date(due).getTime())) { setError("Укажите корректные дату и время"); return; }
    setError(""); save.mutate({ planned_due_at: due ? new Date(due).toISOString() : null, estimated_minutes: amount === null ? null : Math.round(amount * 60) });
  }
  return <section className="panel ticket-planning" aria-label="Планирование заявки"><div className="panel-head"><h2>Срок и трудозатраты</h2></div>
    <p className="ticket-plan-hint">Срок и оценка будут видны клиенту в его заявке.</p>
    <label>Плановый срок решения<input aria-label="Плановый срок решения" type="datetime-local" value={due} disabled={save.isPending} onChange={(e) => { setDue(e.target.value); setEditing(true); }} /></label>
    <label>Оценка трудозатрат, ч<input aria-label="Оценка трудозатрат, ч" type="number" min="0" max="10000" step="any" placeholder="Например, 1.5" value={hours} disabled={save.isPending} onChange={(e) => { setHours(e.target.value); setEditing(true); }} /></label>
    <div className="ticket-plan-summary"><span>{ticket.planned_due_at ? formatDateTime(ticket.planned_due_at) : "Срок пока не назначен"}</span><strong>{ticket.estimated_minutes === null ? "Без оценки" : formatMinutes(ticket.estimated_minutes)}</strong></div>
    {(error || save.isError) && <p role="alert" className="ticket-plan-error">{error || save.error?.message}</p>}
    {save.isSuccess && !editing && <p role="status" className="ticket-plan-saved">План сохранён</p>}
    <button type="button" className="btn btn-primary" disabled={!editing || save.isPending} onClick={submit}>{save.isPending ? "Сохранение…" : "Сохранить план"}</button>
  </section>;
}
