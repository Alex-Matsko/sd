import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createAutomationRule, listAutomationRules, updateAutomationRule } from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading, StatusTag } from "../../components/ui";
import { STATUS_LABELS, STATUS_TRANSITIONS, formatDateTime } from "../../lib/labels";
import type { AutomationRule, AutomationRuleInput, AutomationTriggerType, TicketStatus } from "../../api/types";

const CONDITIONS: Record<AutomationTriggerType, string> = {
  resolved_without_reply: "Нет ответа после решения",
  status_without_reply: "Нет ответа клиента",
  status_age: "Время в статусе",
};
const SOURCE_STATUSES = (Object.keys(STATUS_TRANSITIONS) as TicketStatus[]).filter((status) => STATUS_TRANSITIONS[status].length > 0);

export function AutomationRulesPage() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<AutomationRule | "new" | null>(null);
  const rules = useQuery({ queryKey: ["automation-rules"], queryFn: listAutomationRules });
  const toggle = useMutation({ mutationFn: (rule: AutomationRule) => updateAutomationRule(rule.id, { is_active: !rule.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["automation-rules"] }) });
  return <div className="view automation-page">
    <div className="toolbar"><h1 className="view-title" style={{ marginBottom: 0 }}>Автоматизация</h1><div className="spacer" /><button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>+ Добавить правило</button></div>
    <p className="view-description">Автоматически меняйте статус заявки через заданное число дней. Проверка выполняется фоновым процессом, изменения видны на канбане и в истории заявки.</p>
    {toggle.isError && <ErrorBanner message={toggle.error.message} />}
    {rules.isLoading && <Loading />}{rules.isError && <ErrorBanner message={rules.error.message} />}
    {rules.isSuccess && rules.data.length === 0 && <EmptyState text="Правил пока нет. Добавьте первое правило автоматизации." />}
    {(rules.data ?? []).map((rule) => <article className="panel automation-rule" key={rule.id}>
      <div className="panel-head"><h2>{rule.name}</h2><span className={`status-tag ${rule.is_active ? "status-resolved" : "status-closed"}`}>{rule.is_active ? "Включено" : "Выключено"}</span></div>
      <div className="tag-row"><StatusTag status={rule.from_status} /><span className="muted">→</span><StatusTag status={rule.to_status} /></div>
      <p className="automation-condition">{CONDITIONS[rule.trigger_type]} · {rule.threshold_days} дн.</p>
      <div className="automation-rule-actions"><span className="muted">Изменено: {formatDateTime(rule.updated_at)}</span><div className="spacer" /><button type="button" className="btn btn-ghost" aria-label={`Изменить правило ${rule.name}`} onClick={() => setEditing(rule)}>Изменить</button><button type="button" className="btn btn-ghost" disabled={toggle.isPending} aria-label={`${rule.is_active ? "Выключить" : "Включить"} правило ${rule.name}`} onClick={() => toggle.mutate(rule)}>{rule.is_active ? "Выключить" : "Включить"}</button></div>
    </article>)}
    {editing !== null && <RuleEditor rule={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
  </div>;
}

function RuleEditor({ rule, onClose }: { rule?: AutomationRule; onClose: () => void }) {
  const qc = useQueryClient();
  const dialog = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState<AutomationRuleInput>(() => rule ? { name: rule.name, trigger_type: rule.trigger_type, from_status: rule.from_status, to_status: rule.to_status, threshold_days: rule.threshold_days, is_active: rule.is_active }
    : { name: "", trigger_type: "status_without_reply", from_status: "waiting_customer", to_status: "in_progress", threshold_days: 3, is_active: false });
  useEffect(() => { dialog.current?.showModal(); }, []);
  const save = useMutation({ mutationFn: () => rule ? updateAutomationRule(rule.id, value) : createAutomationRule(value),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ["automation-rules"] }); onClose(); } });
  function changeSource(from_status: TicketStatus) {
    const next = STATUS_TRANSITIONS[from_status];
    setValue((old) => ({ ...old, from_status, to_status: next.includes(old.to_status) ? old.to_status : next[0] }));
  }
  return <dialog ref={dialog} className="modal work-dialog automation-dialog" aria-label={rule ? "Изменить правило" : "Добавить правило"} onCancel={(event) => { if (save.isPending) event.preventDefault(); else onClose(); }} onClick={(event) => { if (event.target === event.currentTarget && !save.isPending) onClose(); }}>
    <form onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
      <header className="modal-head"><h3>{rule ? "Изменить правило" : "Новое правило"}</h3><button type="button" className="icon-btn" aria-label="Закрыть форму" disabled={save.isPending} onClick={onClose}>×</button></header>
      <div className="modal-body">
        <label className="form-row">Название<input type="text" autoFocus required maxLength={255} value={value.name} onChange={(event) => setValue({ ...value, name: event.target.value })} /></label>
        <label className="form-row">Условие<select aria-label="Условие" value={value.trigger_type} onChange={(event) => { const trigger_type = event.target.value as AutomationTriggerType; setValue({ ...value, trigger_type, ...(trigger_type === "resolved_without_reply" ? { from_status: "resolved", to_status: "closed" } : {}) }); }}>{Object.entries(CONDITIONS).map(([key, text]) => <option value={key} key={key}>{text}</option>)}</select></label>
        <div className="automation-transition-fields"><label className="form-row">Исходный статус<select aria-label="Исходный статус" value={value.from_status} onChange={(event) => changeSource(event.target.value as TicketStatus)}>{(value.trigger_type === "resolved_without_reply" ? ["resolved" as const] : SOURCE_STATUSES).map((status) => <option value={status} key={status}>{STATUS_LABELS[status]}</option>)}</select></label>
          <label className="form-row">Перевести в<select aria-label="Перевести в" value={value.to_status} onChange={(event) => setValue({ ...value, to_status: event.target.value as TicketStatus })}>{STATUS_TRANSITIONS[value.from_status].map((status) => <option value={status} key={status}>{STATUS_LABELS[status]}</option>)}</select></label></div>
        <label className="form-row">Через сколько дней<input type="number" required min={1} max={3650} step={1} value={value.threshold_days} onChange={(event) => setValue({ ...value, threshold_days: Number(event.target.value) })} /></label>
        <p className="automation-rule-summary">{value.trigger_type === "status_age" ? "Если статус не менялся" : "Если клиент не отвечал после перехода в этот статус"} {value.threshold_days || "…"} дн., заявка перейдёт из «{STATUS_LABELS[value.from_status]}» в «{STATUS_LABELS[value.to_status]}».</p>
        <label className="max-notification-option"><input type="checkbox" checked={value.is_active} onChange={(event) => setValue({ ...value, is_active: event.target.checked })} />Правило включено</label>
        <p className="muted">Включённое правило применяется и к существующим заявкам. Для одного исходного статуса может быть включено одно правило; ненужное правило можно отключить.</p>
        {save.isError && <ErrorBanner message={save.error.message} />}
      </div>
      <footer className="modal-foot"><button type="button" className="btn btn-ghost" disabled={save.isPending} onClick={onClose}>Отмена</button><button type="submit" className="btn btn-primary" disabled={save.isPending || !value.name.trim()}>{save.isPending ? "Сохранение…" : rule ? "Сохранить" : "Создать правило"}</button></footer>
    </form>
  </dialog>;
}
