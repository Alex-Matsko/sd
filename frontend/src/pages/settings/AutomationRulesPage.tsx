import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listAutomationRules, updateAutomationRule } from "../../api/endpoints";
import { ErrorBanner, Loading } from "../../components/ui";
import { STATUS_LABELS, formatDateTime } from "../../lib/labels";
import type { AutomationRule, AutomationTriggerType } from "../../api/types";

const TRIGGER_LABELS: Record<AutomationTriggerType, string> = {
  resolved_without_reply: "Заявка находится в статусе-источнике N дней без ответа клиента",
};

function RuleCard({ rule }: { rule: AutomationRule }) {
  const qc = useQueryClient();
  const [isActive, setIsActive] = useState(rule.is_active);
  const [thresholdDays, setThresholdDays] = useState(rule.threshold_days);

  const saveMutation = useMutation({
    mutationFn: () => updateAutomationRule(rule.id, { is_active: isActive, threshold_days: thresholdDays }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["automation-rules"] }),
  });

  const dirty = isActive !== rule.is_active || thresholdDays !== rule.threshold_days;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{rule.name}</h2>
        <div className="spacer" />
        <label className="form-row-inline" style={{ marginBottom: 0 }}>
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
          Правило включено
        </label>
      </div>
      <p className="muted" style={{ marginTop: -6 }}>
        {TRIGGER_LABELS[rule.trigger_type]}
      </p>
      <div className="tag-row" style={{ marginBottom: 12 }}>
        <span className="status-tag status-resolved">
          <span className="dot" />
          {STATUS_LABELS[rule.from_status]}
        </span>
        <span className="muted">→</span>
        <span className="status-tag status-closed">
          <span className="dot" />
          {STATUS_LABELS[rule.to_status]}
        </span>
      </div>
      <div className="form-row-inline">
        <label className="form-label" style={{ margin: 0 }}>
          Через
        </label>
        <input
          type="number"
          min={1}
          style={{ width: 80 }}
          value={thresholdDays}
          onChange={(e) => setThresholdDays(Number(e.target.value))}
        />
        <span className="muted">дней</span>
        <div className="spacer" />
        <span className="muted" style={{ fontSize: 11.5 }}>
          Изменено: {formatDateTime(rule.updated_at)}
        </span>
      </div>
      {saveMutation.isError && <ErrorBanner message={(saveMutation.error as Error).message} />}
      <div className="modal-foot" style={{ padding: 0, borderTop: "none", justifyContent: "flex-start", marginTop: 10 }}>
        <button className="btn btn-primary" disabled={!dirty || saveMutation.isPending} onClick={() => saveMutation.mutate()}>
          Сохранить
        </button>
      </div>
    </div>
  );
}

export function AutomationRulesPage() {
  const rulesQuery = useQuery({ queryKey: ["automation-rules"], queryFn: listAutomationRules });

  if (rulesQuery.isLoading) return <div className="view"><Loading /></div>;
  if (rulesQuery.isError) return <div className="view"><ErrorBanner message={(rulesQuery.error as Error).message} /></div>;

  return (
    <div className="view">
      <h1 className="view-title">Автоматизация</h1>
      <p className="muted" style={{ marginTop: -10, marginBottom: 16 }}>
        Правила автоматического перевода заявок между статусами. Заявка, для которой сработало правило,
        сама переезжает в новую колонку на канбан-доске очереди заявок.
      </p>
      {(rulesQuery.data ?? []).map((rule) => (
        <RuleCard key={rule.id} rule={rule} />
      ))}
    </div>
  );
}
