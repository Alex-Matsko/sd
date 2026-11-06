import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createTicketSchedule,
  deleteTicketSchedule,
  listCategories,
  listContacts,
  listOrganizations,
  listTicketSchedules,
  listUsers,
  runTicketScheduleNow,
  updateTicketSchedule,
  type TicketSchedule,
} from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading, PriorityTag } from "../../components/ui";
import { formatDate } from "../../lib/labels";

const CADENCE_LABELS: Record<TicketSchedule["cadence"], string> = {
  daily: "Ежедневно",
  weekly: "Еженедельно",
  monthly: "Ежемесячно",
  quarterly: "Раз в квартал",
};

const WEEKDAY_LABELS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];

function cadenceDetail(schedule: TicketSchedule): string {
  const base = CADENCE_LABELS[schedule.cadence];
  if (schedule.cadence === "weekly" && schedule.day_of_week !== null) {
    return `${base}, ${WEEKDAY_LABELS[schedule.day_of_week].toLowerCase()}`;
  }
  if ((schedule.cadence === "monthly" || schedule.cadence === "quarterly") && schedule.day_of_month !== null) {
    return `${base}, ${schedule.day_of_month}-е число`;
  }
  return base;
}

// Четыре текстовые кнопки действий требуют места: в 190px «Удалить» обрезалось,
// а «Создать сейчас» переносилось на две строки.
const COLUMNS = "1.4fr 1.2fr 1fr 100px 110px 290px";

export function TicketSchedulesPage() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<TicketSchedule | "new" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const schedulesQuery = useQuery({ queryKey: ["ticket-schedules"], queryFn: listTicketSchedules });
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: () => listOrganizations() });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: () => listUsers() });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["ticket-schedules"] });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => updateTicketSchedule(id, { is_active }),
    onSuccess: invalidate,
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteTicketSchedule(id),
    onSuccess: invalidate,
  });
  const runNowMutation = useMutation({
    mutationFn: (id: number) => runTicketScheduleNow(id),
    onSuccess: (schedule) => {
      setNotice(`Заявка по «${schedule.name}» создана. Следующая — ${formatDate(schedule.next_run_on)}`);
      invalidate();
      qc.invalidateQueries({ queryKey: ["tickets"] });
    },
  });

  if (schedulesQuery.isLoading) return <div className="view"><Loading /></div>;
  if (schedulesQuery.isError) {
    return <div className="view"><ErrorBanner message={(schedulesQuery.error as Error).message} /></div>;
  }

  const schedules = schedulesQuery.data ?? [];
  const orgsById = new Map((orgsQuery.data ?? []).map((o) => [o.id, o]));

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Плановые заявки
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          Добавить расписание
        </button>
      </div>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Регулярные работы по договору — профилактика, проверка резервных копий, обновления. Заявка создаётся сама
        в назначенный день и попадает в общую очередь.
      </p>

      {notice && <div className="success-banner">{notice}</div>}

      {schedules.length === 0 && <EmptyState text="Расписаний пока нет" />}
      {schedules.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: COLUMNS }}>
            <span>Название</span>
            <span>Организация</span>
            <span>Периодичность</span>
            <span>Приоритет</span>
            <span>Следующая</span>
            <span></span>
          </div>
          {schedules.map((s) => (
            <div className="list-row" style={{ gridTemplateColumns: COLUMNS }} key={s.id}>
              <span className="subject">
                {s.name}
                {!s.is_active && <span className="muted"> · выключено</span>}
              </span>
              <span className="muted">{orgsById.get(s.organization_id)?.name ?? "—"}</span>
              <span className="muted">{cadenceDetail(s)}</span>
              <span>
                <PriorityTag priority={s.priority} />
              </span>
              {/* У выключенного расписания дата следующего запуска в базе есть,
                  но показывать её как обещание нельзя — оно не сработает. */}
              <span className="muted">{s.is_active ? formatDate(s.next_run_on) : "—"}</span>
              <span style={{ display: "flex", gap: 10 }}>
                <button className="btn-link" onClick={() => setEditing(s)}>
                  Изменить
                </button>
                <button
                  className="btn-link"
                  disabled={runNowMutation.isPending}
                  onClick={() => runNowMutation.mutate(s.id)}
                >
                  Создать сейчас
                </button>
                <button className="btn-link" onClick={() => toggleMutation.mutate({ id: s.id, is_active: !s.is_active })}>
                  {s.is_active ? "Выключить" : "Включить"}
                </button>
                <button className="btn-link" onClick={() => deleteMutation.mutate(s.id)}>
                  Удалить
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <ScheduleModal
          schedule={editing === "new" ? null : editing}
          engineers={usersQuery.data ?? []}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            invalidate();
          }}
        />
      )}
    </div>
  );
}

function ScheduleModal({
  schedule,
  engineers,
  onClose,
  onSaved,
}: {
  schedule: TicketSchedule | null;
  engineers: { id: number; full_name: string }[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(schedule?.name ?? "");
  const [subject, setSubject] = useState(schedule?.subject ?? "");
  const [body, setBody] = useState(schedule?.body ?? "");
  const [cadence, setCadence] = useState<TicketSchedule["cadence"]>(schedule?.cadence ?? "monthly");
  const [dayOfWeek, setDayOfWeek] = useState<number>(schedule?.day_of_week ?? 0);
  const [dayOfMonth, setDayOfMonth] = useState<number>(schedule?.day_of_month ?? 1);
  const [priority, setPriority] = useState(schedule?.priority ?? "P3");
  const [categoryId, setCategoryId] = useState<number | "">(schedule?.category_id ?? "");
  const [engineerId, setEngineerId] = useState<number | "">(schedule?.assigned_engineer_id ?? "");
  const [orgId, setOrgId] = useState<number | "">(schedule?.organization_id ?? "");
  const [contactId, setContactId] = useState<number | "">(schedule?.contact_id ?? "");
  const [error, setError] = useState<string | null>(null);

  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: () => listOrganizations() });
  const categoriesQuery = useQuery({ queryKey: ["categories"], queryFn: listCategories });
  // Контакты грузятся только после выбора организации: список всех контактов
  // по всем клиентам выбирать вручную невозможно.
  const contactsQuery = useQuery({
    queryKey: ["contacts", orgId],
    queryFn: () => listContacts(orgId as number),
    enabled: orgId !== "",
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        subject: subject.trim(),
        body: body.trim() || null,
        cadence,
        priority,
        category_id: categoryId || null,
        assigned_engineer_id: engineerId || null,
        day_of_week: cadence === "weekly" ? dayOfWeek : null,
        day_of_month: cadence === "monthly" || cadence === "quarterly" ? dayOfMonth : null,
      };
      // contact_id менять у существующего расписания нельзя (бэкенд его не
      // принимает в PATCH): организация заявки уже зафиксирована.
      if (!schedule) payload.contact_id = contactId;
      return schedule ? updateTicketSchedule(schedule.id, payload) : createTicketSchedule(payload);
    },
    onSuccess: onSaved,
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось сохранить расписание"),
  });

  const canSave = name.trim() && subject.trim() && (schedule || contactId !== "");

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{schedule ? "Плановая заявка" : "Новая плановая заявка"}</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}

          <div className="form-row">
            <label className="form-label">Название расписания (видно только сотрудникам)</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ежемесячная профилактика серверов"
            />
          </div>

          {!schedule && (
            <>
              <div className="form-row">
                <label className="form-label">Организация</label>
                <select
                  value={orgId}
                  onChange={(e) => {
                    setOrgId(e.target.value ? Number(e.target.value) : "");
                    setContactId("");
                  }}
                >
                  <option value="">Выберите организацию</option>
                  {(orgsQuery.data ?? []).map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">Контакт, от имени которого создаётся заявка</label>
                <select
                  value={contactId}
                  disabled={orgId === ""}
                  onChange={(e) => setContactId(e.target.value ? Number(e.target.value) : "")}
                >
                  <option value="">{orgId === "" ? "Сначала выберите организацию" : "Выберите контакт"}</option>
                  {(contactsQuery.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.full_name}
                    </option>
                  ))}
                </select>
              </div>
            </>
          )}

          <div className="form-row">
            <label className="form-label">Тема заявки</label>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Профилактика: проверка резервных копий"
            />
          </div>

          <div className="form-row">
            <label className="form-label">Описание работ</label>
            <textarea rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
          </div>

          <div className="form-row-inline">
            <div className="form-row" style={{ flex: 1 }}>
              <label className="form-label">Периодичность</label>
              <select value={cadence} onChange={(e) => setCadence(e.target.value as TicketSchedule["cadence"])}>
                {Object.entries(CADENCE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            {cadence === "weekly" && (
              <div className="form-row" style={{ flex: 1 }}>
                <label className="form-label">День недели</label>
                <select value={dayOfWeek} onChange={(e) => setDayOfWeek(Number(e.target.value))}>
                  {WEEKDAY_LABELS.map((label, index) => (
                    <option key={label} value={index}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {(cadence === "monthly" || cadence === "quarterly") && (
              <div className="form-row" style={{ flex: 1 }}>
                <label className="form-label">Число месяца</label>
                <input
                  type="number"
                  min={1}
                  max={31}
                  value={dayOfMonth}
                  onChange={(e) => setDayOfMonth(Number(e.target.value))}
                />
                {dayOfMonth > 28 && (
                  <span className="muted" style={{ fontSize: 12 }}>
                    В коротких месяцах заявка создастся в последний день
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="form-row-inline">
            <div className="form-row" style={{ flex: 1 }}>
              <label className="form-label">Приоритет</label>
              <select value={priority} onChange={(e) => setPriority(e.target.value as typeof priority)}>
                {["P1", "P2", "P3", "P4"].map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-row" style={{ flex: 1 }}>
              <label className="form-label">Категория</label>
              <select value={categoryId} onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : "")}>
                <option value="">Без категории</option>
                {(categoriesQuery.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-row" style={{ flex: 1 }}>
              <label className="form-label">Исполнитель</label>
              <select value={engineerId} onChange={(e) => setEngineerId(e.target.value ? Number(e.target.value) : "")}>
                <option value="">По маршрутизации</option>
                {engineers.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn-primary" disabled={!canSave || saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            Сохранить
          </button>
        </div>
      </div>
    </div>
  );
}
