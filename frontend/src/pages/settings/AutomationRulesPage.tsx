import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createAutomationRule, listAutomationRules, updateAutomationRule, previewAutomationRule, listAutomationRuns, retryAutomationRun,
  listOrganizations, listCategories, listTeams, listUsers } from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading, StatusTag } from "../../components/ui";
import { STATUS_LABELS, STATUS_TRANSITIONS, formatDateTime } from "../../lib/labels";
import type { AutomationAction, AutomationFilters, AutomationRule, AutomationRuleInput, AutomationTriggerType, Channel, Priority, TicketStatus } from "../../api/types";
import { TicketSchedulesPage } from "./TicketSchedulesPage";

const CONDITIONS: Record<AutomationTriggerType, string> = {
  resolved_without_reply: "Нет ответа после решения", status_without_reply: "Нет ответа клиента", status_age: "Время в статусе", deadline_overdue: "Просрочен срок решения",
};
const ACTIONS: Record<AutomationAction["type"], string> = {
  notify_staff: "Напомнить сотрудникам", internal_note: "Внутренняя заметка", client_reminder: "Написать клиенту", change_status: "Сменить статус",
};
const SOURCE_STATUSES = (Object.keys(STATUS_TRANSITIONS) as TicketStatus[]).filter((status) => STATUS_TRANSITIONS[status].length > 0);
const CHANNELS: Record<string, string> = { portal: "Личный кабинет", email: "Email", telegram: "Telegram", max: "MAX", phone: "Телефон", perimetr: "Периметр" };
const makeAction = (type: AutomationAction["type"]): AutomationAction => ({ type, text: type === "change_status" ? "" : "Напоминание по заявке {{ticket_number}}: {{subject}}\n{{ticket_url}}", recipient: "assignee", user_ids: [], channel: "ticket" });
function draft(rule?: AutomationRule): AutomationRuleInput {
  return rule ? { name: rule.name, trigger_type: rule.trigger_type, from_status: rule.from_status, to_status: rule.to_status,
    threshold_days: rule.threshold_days, delay_hours: rule.delay_hours, filters: rule.filters, actions: rule.actions.length ? rule.actions : [makeAction("change_status")],
    repeat_hours: rule.repeat_hours, max_runs: rule.max_runs, is_active: rule.is_active }
    : { name: "", trigger_type: "status_without_reply", from_status: "waiting_customer", to_status: null, threshold_days: 3, delay_hours: 72,
      filters: {}, actions: [makeAction("notify_staff")], repeat_hours: null, max_runs: 3, is_active: false };
}

export function AutomationRulesPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"rules" | "schedules">("rules");
  const [editing, setEditing] = useState<AutomationRule | "new" | null>(null);
  const [history, setHistory] = useState<AutomationRule | null>(null);
  const rules = useQuery({ queryKey: ["automation-rules"], queryFn: listAutomationRules });
  const toggle = useMutation({ mutationFn: (rule: AutomationRule) => updateAutomationRule(rule.id, { is_active: !rule.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["automation-rules"] }) });
  return <div className="view automation-page">
    <div className="toolbar"><h1 className="view-title" style={{ marginBottom: 0 }}>Автоматизация</h1><div className="spacer" />{tab === "rules" && <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>+ Добавить правило</button>}</div>
    <p className="view-description">Напоминания, действия по заявкам и регулярные работы. Сначала проверьте совпадения, затем включите нужное правило.</p>
    <div className="automation-tabs" aria-label="Раздел автоматизации"><button type="button" className={`btn ${tab === "rules" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("rules")}>Правила и напоминания</button><button type="button" className={`btn ${tab === "schedules" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("schedules")}>Регулярные работы</button></div>
    {tab === "schedules" ? <TicketSchedulesPage embedded /> : <>
      {toggle.isError && <ErrorBanner message={toggle.error.message} />}
      {rules.isLoading && <Loading />}{rules.isError && <ErrorBanner message={rules.error.message} />}
      {rules.isSuccess && rules.data.length === 0 && <EmptyState text="Правил пока нет. Добавьте первое правило автоматизации." />}
      {(rules.data ?? []).map((rule) => <article className="panel automation-rule" key={rule.id}>
        <div className="panel-head"><h2>{rule.name}</h2><span className={`status-tag ${rule.is_active ? "status-resolved" : "status-closed"}`}>{rule.is_active ? "Включено" : "Выключено"}</span></div>
        <div className="tag-row"><StatusTag status={rule.from_status} /><span className="muted">· {CONDITIONS[rule.trigger_type]} · {rule.delay_hours ?? rule.threshold_days * 24} ч</span>{rule.to_status && <><span>→</span><StatusTag status={rule.to_status} /></>}</div>
        <p className="automation-condition">{(rule.actions.length ? rule.actions : [makeAction("change_status")]).map(a => ACTIONS[a.type]).join(" → ")}{rule.repeat_hours ? ` · повтор каждые ${rule.repeat_hours} ч, до ${rule.max_runs} раз` : " · однократно"}</p>
        {Object.values(rule.filters).some(v => Array.isArray(v) ? v.length : v) && <p className="muted">Применяются фильтры заявок</p>}
        <div className="automation-rule-actions"><span className="muted">{formatDateTime(rule.updated_at)}</span><div className="spacer" /><button type="button" className="btn btn-ghost" onClick={() => setHistory(rule)}>Журнал</button><button type="button" className="btn btn-ghost" aria-label={`Изменить правило ${rule.name}`} onClick={() => setEditing(rule)}>Изменить</button><button type="button" className="btn btn-ghost" disabled={toggle.isPending} aria-label={`${rule.is_active ? "Выключить" : "Включить"} правило ${rule.name}`} onClick={() => toggle.mutate(rule)}>{rule.is_active ? "Выключить" : "Включить"}</button></div>
      </article>)}
    </>}
    {editing !== null && <RuleEditor rule={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    {history && <RunHistory rule={history} onClose={() => setHistory(null)} />}
  </div>;
}

function RuleEditor({ rule, onClose }: { rule?: AutomationRule; onClose: () => void }) {
  const qc = useQueryClient();
  const dialog = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState<AutomationRuleInput>(() => draft(rule));
  const orgs = useQuery({ queryKey: ["organizations"], queryFn: () => listOrganizations() });
  const categories = useQuery({ queryKey: ["categories"], queryFn: listCategories });
  const teams = useQuery({ queryKey: ["teams"], queryFn: listTeams });
  const users = useQuery({ queryKey: ["users"], queryFn: listUsers });
  useEffect(() => { dialog.current?.showModal(); }, []);
  const save = useMutation({ mutationFn: () => rule ? updateAutomationRule(rule.id, value) : createAutomationRule(value),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ["automation-rules"] }); onClose(); } });
  const preview = useMutation({ mutationFn: (payload: AutomationRuleInput) => previewAutomationRule(payload) });
  const previewCurrent = preview.variables === value;
  const hasTransition = value.actions.some(action => action.type === "change_status");
  function action(index: number, patch: Partial<AutomationAction>) {
    setValue(old => ({ ...old, actions: old.actions.map((a, i) => i === index ? { ...a, ...patch } : a) }));
  }
  function filter(patch: Partial<AutomationFilters>) { setValue(old => ({ ...old, filters: { ...old.filters, ...patch } })); }
  function changeSource(from_status: TicketStatus) {
    const next = STATUS_TRANSITIONS[from_status];
    setValue(old => ({ ...old, from_status, to_status: hasTransition ? (old.to_status && next.includes(old.to_status) ? old.to_status : next[0]) : null }));
  }
  function preset(kind: "customer" | "overdue" | "close") {
    const base = draft();
    setValue(kind === "customer" ? { ...base, name: "Напомнить клиенту об ответе", actions: [{ ...makeAction("client_reminder"), text: "Здравствуйте, {{client_name}}! Ожидаем вашего ответа по заявке {{ticket_number}} — {{subject}}.\n{{ticket_url}}" }], repeat_hours: 48 }
      : kind === "overdue" ? { ...base, name: "Просрочен срок решения", trigger_type: "deadline_overdue", from_status: "in_progress", delay_hours: 1, repeat_hours: 24, actions: [{ ...makeAction("notify_staff"), text: "Просрочена заявка {{ticket_number}}: {{subject}}\nСрок: {{due_at}}\n{{ticket_url}}" }] }
      : { ...base, name: "Закрыть решённую заявку без ответа", trigger_type: "resolved_without_reply", from_status: "resolved", to_status: "closed", actions: [makeAction("change_status")] });
  }
  return <dialog ref={dialog} className="modal work-dialog automation-dialog" aria-label={rule ? "Изменить правило" : "Добавить правило"} onCancel={(event) => { if (save.isPending) event.preventDefault(); else onClose(); }}>
    <form onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
      <header className="modal-head"><h3>{rule ? "Изменить правило" : "Новое правило"}</h3><button type="button" className="icon-btn" aria-label="Закрыть форму" disabled={save.isPending} onClick={onClose}>×</button></header>
      <div className="modal-body">
        {!rule && <div className="automation-presets"><span className="muted">Начать с шаблона:</span><button type="button" className="btn btn-ghost" onClick={() => preset("customer")}>Ждём клиента</button><button type="button" className="btn btn-ghost" onClick={() => preset("overdue")}>Просрочка</button><button type="button" className="btn btn-ghost" onClick={() => preset("close")}>Автозакрытие</button></div>}
        <label className="form-row">Название<input type="text" autoFocus required maxLength={255} value={value.name} onChange={event => setValue({ ...value, name: event.target.value })} /></label>
        <section className="automation-editor-section"><h4>Когда выполнять</h4>
          <div className="automation-transition-fields"><label className="form-row">Условие<select aria-label="Условие" value={value.trigger_type} onChange={event => { const trigger_type = event.target.value as AutomationTriggerType; setValue({ ...value, trigger_type, ...(trigger_type === "resolved_without_reply" ? { from_status: "resolved", ...(hasTransition ? { to_status: "closed" } : {}) } : {}) }); }}>{Object.entries(CONDITIONS).map(([key, text]) => <option value={key} key={key}>{text}</option>)}</select></label>
          <label className="form-row">Статус заявки<select aria-label="Исходный статус" value={value.from_status} onChange={event => changeSource(event.target.value as TicketStatus)}>{(value.trigger_type === "resolved_without_reply" ? ["resolved" as const] : SOURCE_STATUSES).map(status => <option value={status} key={status}>{STATUS_LABELS[status]}</option>)}</select></label></div>
          <label className="form-row">{value.trigger_type === "deadline_overdue" ? "Через сколько часов после срока" : "Через сколько часов"}<input type="number" required min={1} max={87600} step={1} value={value.delay_hours ?? value.threshold_days * 24} onChange={event => setValue({ ...value, delay_hours: Number(event.target.value) })} /></label>
          <p className="muted">{value.trigger_type === "deadline_overdue" ? "Используется плановый срок решения; если его нет — срок SLA без паузы." : value.trigger_type === "status_age" ? "Отсчёт с последнего перехода в выбранный статус." : "Отсчёт с перехода в статус или последнего ответа клиента. Внутренние заметки и напоминания не сбрасывают таймер."}</p>
        </section>
        <details className="automation-editor-section"><summary>Фильтры заявок</summary><p className="muted">Все заполненные условия должны совпасть. Пустые поля — без ограничения.</p>
          <div className="automation-transition-fields">
            <label className="form-row">Организация<select aria-label="Организация" value={value.filters.organization_id ?? ""} onChange={event => filter({ organization_id: Number(event.target.value) || null })}><option value="">Все организации</option>{(orgs.data ?? []).map(o => <option value={o.id} key={o.id}>{o.name}</option>)}</select></label>
            <label className="form-row">Категория<select aria-label="Категория" value={value.filters.category_id ?? ""} onChange={event => filter({ category_id: Number(event.target.value) || null })}><option value="">Все категории</option>{(categories.data ?? []).map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</select></label>
            <label className="form-row">Команда<select aria-label="Команда" value={value.filters.team_id ?? ""} onChange={event => filter({ team_id: Number(event.target.value) || null })}><option value="">Все команды</option>{(teams.data ?? []).map(t => <option value={t.id} key={t.id}>{t.name}</option>)}</select></label>
            <label className="form-row">Исполнитель<select aria-label="Исполнитель" value={value.filters.unassigned ? "none" : value.filters.assigned_engineer_id ?? ""} onChange={event => filter({ unassigned: event.target.value === "none", assigned_engineer_id: Number(event.target.value) || null })}><option value="">Любой</option><option value="none">Без исполнителя</option>{(users.data ?? []).map(u => <option value={u.id} key={u.id}>{u.full_name}</option>)}</select></label>
          </div>
          <fieldset className="automation-checks"><legend>Приоритет</legend>{(["P1", "P2", "P3", "P4"] as Priority[]).map(p => <label key={p}><input type="checkbox" checked={value.filters.priorities?.includes(p) ?? false} onChange={event => filter({ priorities: event.target.checked ? [...(value.filters.priorities ?? []), p] : value.filters.priorities?.filter(v => v !== p) })} />{p}</label>)}</fieldset>
          <fieldset className="automation-checks"><legend>Канал заявки</legend>{Object.entries(CHANNELS).map(([c, title]) => <label key={c}><input type="checkbox" checked={value.filters.channels?.includes(c as Channel) ?? false} onChange={event => filter({ channels: event.target.checked ? [...(value.filters.channels ?? []), c as Channel] : value.filters.channels?.filter(v => v !== c) })} />{title}</label>)}</fieldset>
        </details>
        <section className="automation-editor-section"><h4>Что сделать</h4>
          {value.actions.map((a, index) => <div className="automation-action-editor" key={index}>
            <div className="automation-action-head"><strong>{index + 1}. {ACTIONS[a.type]}</strong><button type="button" className="btn btn-ghost" aria-label={`Удалить действие ${index + 1}`} disabled={value.actions.length === 1} onClick={() => setValue({ ...value, actions: value.actions.filter((_, i) => i !== index), ...(a.type === "change_status" ? { to_status: null } : {}) })}>Удалить</button></div>
            {a.type === "change_status" ? <label className="form-row">Перевести в<select aria-label="Перевести в" value={value.to_status ?? ""} onChange={event => setValue({ ...value, to_status: event.target.value as TicketStatus })}>{STATUS_TRANSITIONS[value.from_status].map(status => <option value={status} key={status}>{STATUS_LABELS[status]}</option>)}</select></label> : <>
              {a.type === "notify_staff" && <><label className="form-row">Кому напомнить<select aria-label="Кому напомнить" value={a.recipient} onChange={event => action(index, { recipient: event.target.value as AutomationAction["recipient"] })}><option value="assignee">Исполнителю</option><option value="team">Команде заявки</option><option value="managers">Руководителям и администраторам</option><option value="users">Выбранным сотрудникам</option></select></label>{a.recipient === "users" && <fieldset className="automation-checks"><legend>Получатели с доступом к заявке</legend>{(users.data ?? []).filter(u => u.is_active).map(u => <label key={u.id}><input type="checkbox" checked={a.user_ids.includes(u.id)} onChange={event => action(index, { user_ids: event.target.checked ? [...a.user_ids, u.id] : a.user_ids.filter(id => id !== u.id) })} />{u.full_name}</label>)}</fieldset>}<p className="muted">Уведомление в системе и подключённых мессенджерах с учётом личных настроек сотрудника.</p></>}
              {a.type === "client_reminder" && <label className="form-row">Куда отправить<select aria-label="Куда отправить" value={a.channel} onChange={event => action(index, { channel: event.target.value as AutomationAction["channel"] })}><option value="ticket">В канал заявки</option>{["email", "telegram", "max", "portal"].map(c => <option value={c} key={c}>{CHANNELS[c]}</option>)}</select></label>}
              <label className="form-row">Текст<textarea required maxLength={10000} rows={4} value={a.text} onChange={event => action(index, { text: event.target.value })} /></label>
              <div className="automation-variables" aria-label="Добавить переменную">{["ticket_number", "subject", "client_name", "organization", "assignee", "due_at", "ticket_url"].map(key => <button type="button" key={key} onClick={() => action(index, { text: a.text + `{{${key}}}` })}>{`{{${key}}}`}</button>)}</div>
              {a.type === "internal_note" && <p className="muted">Заметка видна сотрудникам и не отправляется клиенту.</p>}
            </>}
          </div>)}
          <label className="form-row">Добавить действие<select aria-label="Добавить действие" value="" disabled={value.actions.length >= 10} onChange={event => { const type = event.target.value as AutomationAction["type"]; if (!type) return; const next = [...value.actions]; const insertAt = next.findIndex(a => a.type === "change_status"); next.splice(insertAt < 0 ? next.length : insertAt, 0, makeAction(type)); setValue({ ...value, actions: next, ...(type === "change_status" ? { to_status: STATUS_TRANSITIONS[value.from_status][0], repeat_hours: null } : {}) }); }}><option value="">Выберите действие…</option>{Object.entries(ACTIONS).filter(([key]) => key !== "change_status" || !hasTransition).map(([key, title]) => <option value={key} key={key}>{title}</option>)}</select></label>
        </section>
        <section className="automation-editor-section"><h4>Повторение</h4><label className="max-notification-option"><input type="checkbox" disabled={hasTransition} checked={value.repeat_hours !== null} onChange={event => setValue({ ...value, repeat_hours: event.target.checked ? 24 : null })} />Повторять, пока заявка подходит под условия</label>
          {value.repeat_hours !== null && <div className="automation-transition-fields"><label className="form-row">Интервал, часов<input type="number" required min={1} max={8760} value={value.repeat_hours} onChange={event => setValue({ ...value, repeat_hours: Number(event.target.value) })} /></label><label className="form-row">Всего выполнений, не более<input type="number" required min={1} max={1000} value={value.max_runs} onChange={event => setValue({ ...value, max_runs: Number(event.target.value) })} /></label></div>}
          <p className="muted">Ответ клиента запускает новый отсчёт только для условий без ответа. Возврат в статус начинает новый цикл. Повтор не создаётся, пока предыдущее сообщение ожидает доставки. Смена статуса выполняется один раз.</p>
        </section>
        <section className="automation-editor-section"><h4>Проверка без отправки</h4><button type="button" className="btn btn-ghost" disabled={preview.isPending || !value.name.trim()} onClick={() => preview.mutate(value)}>{preview.isPending ? "Проверка…" : "Проверить заявки"}</button>
          {previewCurrent && preview.isError && <ErrorBanner message={preview.error.message} />}
          {previewCurrent && preview.data && <div className="automation-preview"><p>Подходят по условиям: <strong>{preview.data.matched_count}</strong>. Действия доступны: <strong>{preview.data.ready_count}</strong>.</p><p className="muted">Показаны первые 20 заявок. Уведомления и сообщения не отправлялись. Журнал выполнений и интервалы повторов учитываются при фактическом запуске.</p>{preview.data.samples.map(sample => <article key={sample.ticket_id}><strong>{sample.display_number} — {sample.subject}</strong>{sample.error && <p className="error-text">{sample.error}</p>}{sample.actions.map((a, i) => <div key={i}><span className="muted">{ACTIONS[a.type]}{a.recipient_count !== null ? ` · получателей: ${a.recipient_count}` : ""}</span>{a.text && <p className="automation-message-preview">{a.text}</p>}</div>)}</article>)}</div>}
        </section>
        <label className="max-notification-option"><input type="checkbox" checked={value.is_active} onChange={event => setValue({ ...value, is_active: event.target.checked })} />Правило включено</label>
        <p className="muted">Включённое правило применяется и к существующим заявкам. Новые правила создаются выключенными, если вы явно не включите их. Изменение условий или действий начинает новый цикл выполнения.</p>
        {save.isError && <ErrorBanner message={save.error.message} />}
      </div>
      <footer className="modal-foot"><button type="button" className="btn btn-ghost" disabled={save.isPending} onClick={onClose}>Отмена</button><button type="submit" className="btn btn-primary" disabled={save.isPending || !value.name.trim()}>{save.isPending ? "Сохранение…" : rule ? "Сохранить" : "Создать правило"}</button></footer>
    </form>
  </dialog>;
}

function RunHistory({ rule, onClose }: { rule: AutomationRule; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const qc = useQueryClient();
  const runs = useQuery({ queryKey: ["automation-runs", rule.id], queryFn: () => listAutomationRuns(rule.id), refetchInterval: 10000 });
  const retry = useMutation({ mutationFn: (id: number) => retryAutomationRun(rule.id, id), onSuccess: () => qc.invalidateQueries({ queryKey: ["automation-runs", rule.id] }) });
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="modal work-dialog automation-dialog" aria-label="Журнал автоматизации" onCancel={onClose}><header className="modal-head"><h3>Журнал: {rule.name}</h3><button type="button" className="icon-btn" aria-label="Закрыть журнал" onClick={onClose}>×</button></header><div className="modal-body">
    {runs.isLoading && <Loading />}{runs.isError && <ErrorBanner message={runs.error.message} />}{retry.isError && <ErrorBanner message={retry.error.message} />}{runs.data?.length === 0 && <EmptyState text="Правило ещё не выполнялось" />}
    {runs.data?.map(run => <article className="automation-run" key={run.id}><div className="automation-action-head"><Link to={`/tickets/${run.ticket_id}`} onClick={onClose}>{run.display_number} — {run.subject}</Link><span className={`status-tag ${run.state === "error" ? "status-cancelled" : "status-resolved"}`}>{run.state === "error" ? "Ошибка" : "Применено"}</span></div><p className="muted">{formatDateTime(run.created_at)} · выполнение {run.occurrence} · версия {run.revision} · попыток {run.attempts}</p>{run.error && <p>{run.error}</p>}{run.delivery.map(job => <p key={job.id}>Доставка: {({ sent: "Отправлено", failed: "Ошибка", pending: "В очереди", processing: "Отправляется", retry: "Ожидает повтора", discarded: "Отменена" } as Record<string, string>)[job.state] ?? job.state}{job.error ? ` — ${job.error}` : ""}</p>)}{run.state === "error" && run.revision === rule.revision && rule.is_active && <button type="button" className="btn btn-ghost" disabled={retry.isPending} onClick={() => retry.mutate(run.id)}>Повторить проверку</button>}</article>)}
  </div></dialog>;
}
