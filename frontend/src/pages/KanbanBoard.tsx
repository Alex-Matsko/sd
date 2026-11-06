import { useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { updateTicket } from "../api/endpoints";
import { ErrorBanner, PriorityTag, SlaTag } from "../components/ui";
import { STATUS_LABELS, STATUS_TRANSITIONS } from "../lib/labels";
import type { Organization, Ticket, TicketStatus, User } from "../api/types";

// Terminal states (Закрыта/Отменена) are archived off the board on purpose -
// a Kanban board tracks work in flight, not the full history (section 4.2
// status model). Closed/cancelled tickets stay reachable via the list view.
const BOARD_COLUMNS: TicketStatus[] = [
  "new",
  "assigned",
  "in_progress",
  "waiting_customer",
  "waiting_third_party",
  "resolved",
];

export function KanbanBoard({
  tickets,
  orgsById,
  usersById,
}: {
  tickets: Ticket[];
  orgsById: Map<number, Organization>;
  usersById: Map<number, User>;
}) {
  const qc = useQueryClient();
  const [dragTicketId, setDragTicketId] = useState<number | null>(null);
  const [dragOverColumn, setDragOverColumn] = useState<TicketStatus | null>(null);

  const moveMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: TicketStatus }) => updateTicket(id, { status }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["tickets"] }),
  });

  // FLIP animation: whenever a card's column changes - because of a manual
  // drag *or* because the server moved it (SLA reopen-on-reply, auto-close
  // rule, an engineer changing status from the ticket card) - the card
  // visibly slides to its new position on the next refetch, instead of
  // teleporting. Driven purely by observed position deltas, so both causes
  // of movement get the same animation for free.
  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const prevRectsRef = useRef<Map<number, DOMRect>>(new Map());

  useLayoutEffect(() => {
    const nextRects = new Map<number, DOMRect>();
    cardRefs.current.forEach((el, id) => {
      const rect = el.getBoundingClientRect();
      nextRects.set(id, rect);
      const prev = prevRectsRef.current.get(id);
      if (prev) {
        const dx = prev.left - rect.left;
        const dy = prev.top - rect.top;
        if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
          el.style.transition = "none";
          el.style.transform = `translate(${dx}px, ${dy}px)`;
          requestAnimationFrame(() => {
            el.style.transition = "transform 320ms cubic-bezier(0.2, 0.8, 0.2, 1)";
            el.style.transform = "";
          });
        }
      }
    });
    prevRectsRef.current = nextRects;
  }, [tickets]);

  const byColumn = new Map<TicketStatus, Ticket[]>(BOARD_COLUMNS.map((s) => [s, []]));
  for (const t of tickets) {
    byColumn.get(t.status)?.push(t);
  }

  function canDrop(ticket: Ticket, target: TicketStatus): boolean {
    if (ticket.status === target) return false;
    return (STATUS_TRANSITIONS[ticket.status] ?? []).includes(target);
  }

  const draggedTicket = dragTicketId != null ? tickets.find((t) => t.id === dragTicketId) : undefined;

  return (
    <>
    {moveMutation.isError && <ErrorBanner message={moveMutation.error.message} />}
    <div className="kanban-board">
      {BOARD_COLUMNS.map((column) => {
        const columnTickets = byColumn.get(column) ?? [];
        const isValidTarget = draggedTicket ? canDrop(draggedTicket, column) : false;
        const isOver = dragOverColumn === column;
        return (
          <div
            key={column}
            className={`kanban-column ${isOver && isValidTarget ? "kanban-column-drop-ok" : ""} ${isOver && draggedTicket && !isValidTarget ? "kanban-column-drop-bad" : ""}`}
            onDragOver={(e) => {
              if (!draggedTicket) return;
              e.preventDefault();
              setDragOverColumn(column);
            }}
            onDragLeave={() => setDragOverColumn((c) => (c === column ? null : c))}
            onDrop={(e) => {
              e.preventDefault();
              setDragOverColumn(null);
              if (draggedTicket && canDrop(draggedTicket, column)) {
                moveMutation.mutate({ id: draggedTicket.id, status: column });
              }
            }}
          >
            <div className="kanban-column-head">
              <span>{STATUS_LABELS[column]}</span>
              <span className="kanban-count">{columnTickets.length}</span>
            </div>
            <div className="kanban-column-body">
              {columnTickets.map((t) => (
                <div
                  key={t.id}
                  ref={(el) => {
                    if (el) cardRefs.current.set(t.id, el);
                    else cardRefs.current.delete(t.id);
                  }}
                  className="kanban-card"
                  draggable
                  onDragStart={() => setDragTicketId(t.id)}
                  onDragEnd={() => {
                    setDragTicketId(null);
                    setDragOverColumn(null);
                  }}
                >
                  <Link to={`/tickets/${t.id}`} className="kanban-card-link">
                    <div className="kanban-card-top">
                      <span className="mono muted">{t.display_number}</span>
                      <PriorityTag priority={t.priority} />
                    </div>
                    <div className="kanban-card-subject">{t.subject}</div>
                    <div className="kanban-card-org muted">{orgsById.get(t.organization_id)?.name ?? "—"}</div>
                    <div className="kanban-card-bottom">
                      <SlaTag sla={t.sla} />
                      <span className="who-mini muted">
                        {t.assigned_engineer_id ? usersById.get(t.assigned_engineer_id)?.full_name ?? "—" : "Не назначено"}
                      </span>
                    </div>
                  </Link>
                </div>
              ))}
              {columnTickets.length === 0 && <div className="kanban-empty">Пусто</div>}
            </div>
          </div>
        );
      })}
    </div>
    </>
  );
}
