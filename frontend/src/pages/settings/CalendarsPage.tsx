import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createCalendar,
  createHolidays,
  deleteHoliday,
  listCalendars,
  listHolidays,
  replaceCalendarWindows,
  updateCalendar,
} from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import type { BusinessCalendar } from "../../api/types";

const WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];

/** Часы приходят как "09:00:00", а input[type=time] понимает "09:00". */
const toInput = (value: string) => value.slice(0, 5);
const toApi = (value: string) => (value.length === 5 ? `${value}:00` : value);

interface DayRow {
  enabled: boolean;
  start: string;
  end: string;
}

function rowsFrom(calendar: BusinessCalendar): DayRow[] {
  return WEEKDAYS.map((_, weekday) => {
    const window = calendar.windows.find((w) => w.weekday === weekday);
    return window
      ? { enabled: true, start: toInput(window.start_time), end: toInput(window.end_time) }
      : { enabled: false, start: "09:00", end: "18:00" };
  });
}

export function CalendarsPage() {
  const calendarsQuery = useQuery({ queryKey: ["calendars"], queryFn: listCalendars });

  if (calendarsQuery.isLoading) return <div className="view"><Loading /></div>;
  if (calendarsQuery.isError) {
    return <div className="view"><ErrorBanner message={(calendarsQuery.error as Error).message} /></div>;
  }

  return (
    <div className="view" style={{ maxWidth: 1080 }}>
      <h1 className="view-title">Рабочий календарь</h1>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        По этому календарю считаются сроки реакции и решения: время вне рабочих часов и в праздники в SLA не
        идёт. Календарь привязывается к тарифу в разделе «Тарифы и SLA».
      </p>

      {(calendarsQuery.data ?? []).map((calendar) => (
        <CalendarCard key={calendar.id} calendar={calendar} />
      ))}

      <NewCalendar />
      <Holidays />
    </div>
  );
}

function CalendarCard({ calendar }: { calendar: BusinessCalendar }) {
  const qc = useQueryClient();
  const [rows, setRows] = useState<DayRow[]>(() => rowsFrom(calendar));
  const [is24x7, setIs24x7] = useState(calendar.is_24x7);
  const [observesHolidays, setObservesHolidays] = useState(calendar.observes_holidays);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const saveMutation = useMutation({
    mutationFn: async () => {
      await updateCalendar(calendar.id, { is_24x7: is24x7, observes_holidays: observesHolidays });
      await replaceCalendarWindows(
        calendar.id,
        rows
          .map((row, weekday) => ({ ...row, weekday }))
          .filter((row) => row.enabled)
          .map((row) => ({ weekday: row.weekday, start_time: toApi(row.start), end_time: toApi(row.end) }))
      );
    },
    onSuccess: () => {
      setError(null);
      setSaved(true);
      qc.invalidateQueries({ queryKey: ["calendars"] });
    },
    onError: (e) => {
      setSaved(false);
      setError(e instanceof Error ? e.message : "Не удалось сохранить календарь");
    },
  });

  function setRow(index: number, patch: Partial<DayRow>) {
    setSaved(false);
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{calendar.name}</h2>
        <span className="muted">{calendar.timezone}</span>
      </div>

      {error && <ErrorBanner message={error} />}
      {saved && !error && <div className="success-banner">Календарь сохранён</div>}

      <div className="form-row-inline">
        <label className="form-row-inline" style={{ marginBottom: 0 }}>
          <input
            type="checkbox"
            checked={is24x7}
            onChange={(e) => {
              setIs24x7(e.target.checked);
              setSaved(false);
            }}
          />
          Круглосуточно, без выходных
        </label>
        <label className="form-row-inline" style={{ marginBottom: 0 }}>
          <input
            type="checkbox"
            checked={observesHolidays}
            disabled={is24x7}
            onChange={(e) => {
              setObservesHolidays(e.target.checked);
              setSaved(false);
            }}
          />
          Учитывать праздники
        </label>
      </div>

      {is24x7 ? (
        <p className="muted">
          Круглосуточный календарь: рабочие часы и праздники не применяются, SLA идёт непрерывно.
        </p>
      ) : (
        <div className="weekday-grid">
          {rows.map((row, weekday) => (
            <div className="weekday-row" key={weekday}>
              <label className="weekday-name">
                <input
                  type="checkbox"
                  checked={row.enabled}
                  onChange={(e) => setRow(weekday, { enabled: e.target.checked })}
                />
                {WEEKDAYS[weekday]}
              </label>
              {row.enabled ? (
                <>
                  <input type="time" value={row.start} onChange={(e) => setRow(weekday, { start: e.target.value })} />
                  <span className="muted">—</span>
                  <input type="time" value={row.end} onChange={(e) => setRow(weekday, { end: e.target.value })} />
                  {row.start >= row.end && <span className="muted">начало позже конца</span>}
                </>
              ) : (
                <span className="muted">выходной</span>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="form-row-inline" style={{ justifyContent: "flex-end", marginTop: 14 }}>
        <button
          className="btn btn-primary"
          disabled={saveMutation.isPending || rows.some((r) => r.enabled && r.start >= r.end)}
          onClick={() => saveMutation.mutate()}
        >
          Сохранить
        </button>
      </div>
    </div>
  );
}

function NewCalendar() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      createCalendar({
        name: name.trim(),
        // Пятидневка 9–18 как отправная точка: у большинства клиентов
        // рабочие часы именно такие, а поправить их можно тут же.
        windows: [0, 1, 2, 3, 4].map((weekday) => ({
          weekday,
          start_time: "09:00:00",
          end_time: "18:00:00",
        })),
      }),
    onSuccess: () => {
      setOpen(false);
      setName("");
      setError(null);
      qc.invalidateQueries({ queryKey: ["calendars"] });
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось создать календарь"),
  });

  if (!open) {
    return (
      <div className="form-row-inline" style={{ marginBottom: 22 }}>
        <button className="btn btn-ghost" onClick={() => setOpen(true)}>
          Добавить календарь
        </button>
        <span className="muted">например, для тарифа с круглосуточной поддержкой</span>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Новый календарь</h2>
      </div>
      {error && <ErrorBanner message={error} />}
      <div className="form-row-inline">
        <input
          type="text"
          style={{ flex: 1 }}
          placeholder="Круглосуточная поддержка"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn btn-primary" disabled={!name.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}>
          Создать
        </button>
        <button className="btn-link" onClick={() => setOpen(false)}>
          Отмена
        </button>
      </div>
      <p className="muted">Создаётся с пятидневкой 9–18; часы и праздники настраиваются сразу после.</p>
    </div>
  );
}

function Holidays() {
  const qc = useQueryClient();
  const holidaysQuery = useQuery({ queryKey: ["holidays"], queryFn: listHolidays });
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const addMutation = useMutation({
    mutationFn: () => createHolidays({ holiday_date: from, until_date: to || null, name: name.trim() }),
    onSuccess: () => {
      setFrom("");
      setTo("");
      setName("");
      setError(null);
      qc.invalidateQueries({ queryKey: ["holidays"] });
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось добавить"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteHoliday(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["holidays"] }),
  });

  const holidays = holidaysQuery.data ?? [];

  // Праздники группируются по годам: список за несколько лет иначе
  // читается сплошной лентой, а следить надо именно за годами — чтобы
  // не пропустить незаполненный.
  const byYear = useMemo(() => {
    const groups = new Map<string, typeof holidays>();
    for (const holiday of holidays) {
      const year = holiday.holiday_date.slice(0, 4);
      groups.set(year, [...(groups.get(year) ?? []), holiday]);
    }
    return [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [holidays]);

  const nextYear = String(new Date().getFullYear() + 1);
  const nextYearMissing = holidays.length > 0 && !byYear.some(([year]) => year === nextYear);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Праздничные дни</h2>
        <span className="muted">общие для всех календарей с галочкой «учитывать праздники»</span>
      </div>

      {nextYearMissing && (
        <div className="error-banner">
          На {nextYear} год праздники не заведены. С 1 января система будет считать эти дни рабочими, и сроки
          по SLA сместятся.
        </div>
      )}
      {error && <ErrorBanner message={error} />}

      <div className="form-row-inline" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
        <div className="form-row" style={{ marginBottom: 0 }}>
          <label className="form-label">С</label>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="form-row" style={{ marginBottom: 0 }}>
          <label className="form-label">По (необязательно)</label>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <div className="form-row" style={{ flex: 1, minWidth: 220, marginBottom: 0 }}>
          <label className="form-label">Название</label>
          <input
            type="text"
            placeholder="Новогодние каникулы"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <button
          className="btn btn-primary"
          disabled={!from || !name.trim() || addMutation.isPending}
          onClick={() => addMutation.mutate()}
        >
          Добавить
        </button>
      </div>
      <p className="muted">
        Период задаётся, чтобы не заводить каникулы по одному дню. Уже отмеченные дни внутри периода
        пропускаются.
      </p>

      {holidaysQuery.isLoading && <Loading />}
      {holidays.length === 0 && holidaysQuery.isSuccess && <EmptyState text="Праздничных дней не заведено" />}

      {byYear.map(([year, items]) => (
        <div key={year}>
          <h3 className="form-section">{year} год · {items.length} дн.</h3>
          <div className="list">
            {items.map((holiday) => (
              <div className="list-row" style={{ gridTemplateColumns: "130px 1fr 100px" }} key={holiday.id}>
                <span className="mono">{holiday.holiday_date.split("-").reverse().join(".")}</span>
                <span>{holiday.name}</span>
                <span>
                  <button className="btn-link" onClick={() => deleteMutation.mutate(holiday.id)}>
                    Удалить
                  </button>
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
