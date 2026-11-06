import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createRoutingRule,
  deleteRoutingRule,
  listCategories,
  listOrganizations,
  listRoutingRules,
  listTeams,
  listUsers,
  previewRouting,
  updateRoutingRule,
} from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import { CHANNEL_LABELS, PRIORITY_LABELS } from "../../lib/labels";
import type { Channel, Priority, RoutingCondition, RoutingConditionField, RoutingRule } from "../../api/types";

const FIELD_LABELS: Record<RoutingConditionField, string> = {
  organization: "Организация",
  category: "Категория",
  channel: "Канал обращения",
  priority: "Приоритет",
  type: "Тип заявки",
  asset: "Актив",
};

const TYPE_LABELS: Record<string, string> = {
  incident: "Инцидент",
  service_request: "Запрос на обслуживание",
};

interface Options {
  organizations: { id: number; name: string }[];
  categories: { id: number; name: string; parent_id: number | null }[];
  users: { id: number; full_name: string }[];
  teams: { id: number; name: string }[];
}

/** Варианты значения для выбранного поля условия. */
function valuesFor(field: RoutingConditionField, options: Options): { value: number | string; label: string }[] {
  switch (field) {
    case "organization":
      return options.organizations.map((o) => ({ value: o.id, label: o.name }));
    case "category":
      return options.categories.map((c) => ({
        value: c.id,
        // Подкатегория без родителя в списке неотличима от других: «Windows»
        // встречается и под серверами, и под рабочими местами.
        label: c.parent_id
          ? `${options.categories.find((p) => p.id === c.parent_id)?.name ?? "—"} → ${c.name}`
          : c.name,
      }));
    case "channel":
      return (Object.keys(CHANNEL_LABELS) as Channel[]).map((c) => ({ value: c, label: CHANNEL_LABELS[c] }));
    case "priority":
      return (["P1", "P2", "P3", "P4"] as Priority[]).map((p) => ({ value: p, label: PRIORITY_LABELS[p] }));
    case "type":
      return Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label }));
    default:
      return [];
  }
}

function describeCondition(condition: RoutingCondition, options: Options): string {
  const values = Array.isArray(condition.value) ? condition.value : [condition.value];
  const all = valuesFor(condition.field, options);
  const labels = values.map((v) => all.find((o) => String(o.value) === String(v))?.label ?? String(v));
  return `${condition.negate ? "кроме: " : ""}${FIELD_LABELS[condition.field]} — ${labels.join(" или ")}`;
}

export function RoutingRulesPage() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<RoutingRule | "new" | null>(null);

  const rulesQuery = useQuery({ queryKey: ["routing-rules"], queryFn: listRoutingRules });
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const categoriesQuery = useQuery({ queryKey: ["categories"], queryFn: listCategories });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const teamsQuery = useQuery({ queryKey: ["teams"], queryFn: listTeams });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteRoutingRule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["routing-rules"] }),
  });
  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => updateRoutingRule(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["routing-rules"] }),
  });

  if (rulesQuery.isLoading) return <div className="view"><Loading /></div>;
  if (rulesQuery.isError) return <div className="view"><ErrorBanner message={(rulesQuery.error as Error).message} /></div>;

  const options: Options = {
    organizations: orgsQuery.data ?? [],
    categories: (categoriesQuery.data ?? []) as Options["categories"],
    users: usersQuery.data ?? [],
    teams: teamsQuery.data ?? [],
  };
  const usersById = new Map(options.users.map((u) => [u.id, u]));
  const teamsById = new Map(options.teams.map((t) => [t.id, t]));
  const rules = [...(rulesQuery.data ?? [])].sort((a, b) => a.order - b.order);

  const columns = "50px 1.4fr 2.2fr 1.3fr 190px";

  return (
    <div className="view" style={{ maxWidth: 1180 }}>
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Маршрутизация
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          Добавить правило
        </button>
      </div>
      <p className="muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Правила проверяются сверху вниз, срабатывает первое подошедшее. Если не подошло ни одно, заявка остаётся
        в общей очереди диспетчера.
      </p>

      {rules.length === 0 && <EmptyState text="Правил маршрутизации пока нет" />}
      {rules.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: columns }}>
            <span>№</span>
            <span>Название</span>
            <span>Когда срабатывает</span>
            <span>Кому уходит</span>
            <span />
          </div>
          {rules.map((rule) => (
            <div className="list-row" style={{ gridTemplateColumns: columns }} key={rule.id}>
              <span className="mono">{rule.order}</span>
              <span className="subject">
                {rule.name || "Без названия"}
                {!rule.is_active && <span className="muted"> · выключено</span>}
              </span>
              <span className="muted">
                {rule.conditions.length === 0 ? (
                  "прежний формат: по организации или категории"
                ) : (
                  <>
                    {rule.conditions.map((c, i) => (
                      <span key={i}>
                        {i > 0 && <em className="rule-joiner">{rule.match === "all" ? " и " : " или "}</em>}
                        {describeCondition(c, options)}
                      </span>
                    ))}
                  </>
                )}
              </span>
              <span className="muted">
                {rule.target_engineer_id
                  ? usersById.get(rule.target_engineer_id)?.full_name
                  : rule.target_team_id
                    ? `Группа «${teamsById.get(rule.target_team_id)?.name ?? "—"}»`
                    : "—"}
              </span>
              <span style={{ display: "flex", gap: 10 }}>
                <button className="btn-link" onClick={() => setEditing(rule)}>
                  Изменить
                </button>
                <button
                  className="btn-link"
                  onClick={() => toggleMutation.mutate({ id: rule.id, is_active: !rule.is_active })}
                >
                  {rule.is_active ? "Выключить" : "Включить"}
                </button>
                <button className="btn-link" onClick={() => deleteMutation.mutate(rule.id)}>
                  Удалить
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      <RoutingPreview options={options} />

      {editing && (
        <RuleModal
          rule={editing === "new" ? null : editing}
          options={options}
          nextOrder={rules.length ? Math.max(...rules.map((r) => r.order)) + 1 : 1}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            qc.invalidateQueries({ queryKey: ["routing-rules"] });
          }}
        />
      )}
    </div>
  );
}

/** «А куда уйдёт вот такая заявка?»
 *
 *  С появлением условий правило перестало читаться с одного взгляда, а
 *  ошибка в маршрутизации обнаруживается не сразу: заявка просто уходит не
 *  туда, и замечают это через день.
 */
function RoutingPreview({ options }: { options: Options }) {
  const [organizationId, setOrganizationId] = useState<number | "">("");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [channel, setChannel] = useState("");
  const [priority, setPriority] = useState("");

  const previewMutation = useMutation({
    mutationFn: () =>
      previewRouting({
        organization_id: Number(organizationId),
        category_id: categoryId || null,
        channel: channel || null,
        priority: priority || null,
      }),
  });

  const result = previewMutation.data;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Проверить правила</h2>
        <span className="muted">заявка не создаётся — только проверка</span>
      </div>
      <div className="form-row-inline" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
        <div className="form-row" style={{ minWidth: 200, marginBottom: 0 }}>
          <label className="form-label">Клиент</label>
          <select value={organizationId} onChange={(e) => setOrganizationId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Выберите</option>
            {options.organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </div>
        <div className="form-row" style={{ minWidth: 190, marginBottom: 0 }}>
          <label className="form-label">Категория</label>
          <select value={categoryId} onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Любая</option>
            {valuesFor("category", options).map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-row" style={{ minWidth: 140, marginBottom: 0 }}>
          <label className="form-label">Канал</label>
          <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">Любой</option>
            {valuesFor("channel", options).map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-row" style={{ minWidth: 130, marginBottom: 0 }}>
          <label className="form-label">Приоритет</label>
          <select value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="">Любой</option>
            {valuesFor("priority", options).map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
        <button
          className="btn btn-ghost"
          disabled={!organizationId || previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          Проверить
        </button>
      </div>

      {result && (
        <p className={result.matched ? "success-banner" : "muted"}>
          {result.matched
            ? `Сработает правило «${result.rule_name || "без названия"}» — уйдёт: ${result.target}`
            : "Ни одно правило не подошло: заявка останется в общей очереди диспетчера."}
        </p>
      )}
    </div>
  );
}

function RuleModal({
  rule,
  options,
  nextOrder,
  onClose,
  onSaved,
}: {
  rule: RoutingRule | null;
  options: Options;
  nextOrder: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(rule?.name ?? "");
  const [order, setOrder] = useState(rule?.order ?? nextOrder);
  const [match, setMatch] = useState<"all" | "any">(rule?.match ?? "all");
  const [conditions, setConditions] = useState<RoutingCondition[]>(
    rule?.conditions?.length ? rule.conditions : [{ field: "organization", value: "", negate: false }]
  );
  const [target, setTarget] = useState<string>(
    rule?.target_engineer_id ? `engineer:${rule.target_engineer_id}` : rule?.target_team_id ? `team:${rule.target_team_id}` : ""
  );
  const [error, setError] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: () => {
      const [kind, id] = target.split(":");
      const payload = {
        order,
        name: name.trim() || null,
        // rule_type остался ради правил старого формата; для правил с
        // условиями он не используется, но схема его требует.
        rule_type: (kind === "team" ? "category_to_team" : "organization_to_engineer") as RoutingRule["rule_type"],
        is_active: rule?.is_active ?? true,
        match,
        conditions: conditions.filter((c) => c.value !== "" && c.value !== null),
        organization_id: null,
        category_id: null,
        target_engineer_id: kind === "engineer" ? Number(id) : null,
        target_team_id: kind === "team" ? Number(id) : null,
      };
      return rule ? updateRoutingRule(rule.id, payload) : createRoutingRule(payload);
    },
    onSuccess: onSaved,
    onError: (e) => setError(e instanceof Error ? e.message : "Не удалось сохранить правило"),
  });

  function setCondition(index: number, patch: Partial<RoutingCondition>) {
    setConditions((current) => current.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }

  const canSave = target !== "" && conditions.some((c) => c.value !== "" && c.value !== null);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{rule ? "Правило маршрутизации" : "Новое правило"}</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}

          <div className="form-row-inline" style={{ alignItems: "flex-end" }}>
            <div className="form-row" style={{ flex: 1, marginBottom: 0 }}>
              <label className="form-label">Название (видно только сотрудникам)</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Аварии Ромашки — на дежурного"
              />
            </div>
            <div className="form-row" style={{ width: 110, marginBottom: 0 }}>
              <label className="form-label">Порядок</label>
              <input type="number" min={1} value={order} onChange={(e) => setOrder(Number(e.target.value))} />
            </div>
          </div>

          <h3 className="form-section">Когда срабатывает</h3>
          <div className="form-row-inline">
            <label className="form-row-inline" style={{ marginBottom: 0 }}>
              <input type="radio" checked={match === "all"} onChange={() => setMatch("all")} />
              Все условия сразу
            </label>
            <label className="form-row-inline" style={{ marginBottom: 0 }}>
              <input type="radio" checked={match === "any"} onChange={() => setMatch("any")} />
              Любое из условий
            </label>
          </div>

          {conditions.map((condition, index) => {
            const values = valuesFor(condition.field, options);
            return (
              <div className="condition-row" key={index}>
                <span className="condition-joiner">
                  {index === 0 ? "если" : match === "all" ? "и" : "или"}
                </span>
                <select
                  value={condition.field}
                  onChange={(e) =>
                    setCondition(index, { field: e.target.value as RoutingConditionField, value: "" })
                  }
                >
                  {Object.entries(FIELD_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <label className="condition-negate" title="Условие сработает, когда значение НЕ совпадает">
                  <input
                    type="checkbox"
                    checked={condition.negate}
                    onChange={(e) => setCondition(index, { negate: e.target.checked })}
                  />
                  кроме
                </label>
                <select
                  value={String(condition.value ?? "")}
                  onChange={(e) => {
                    const raw = e.target.value;
                    const numeric = values.length > 0 && typeof values[0].value === "number";
                    setCondition(index, { value: numeric ? Number(raw) : raw });
                  }}
                >
                  <option value="">Выберите значение</option>
                  {values.map((v) => (
                    <option key={v.value} value={v.value}>
                      {v.label}
                    </option>
                  ))}
                </select>
                <button
                  className="btn-link"
                  disabled={conditions.length === 1}
                  onClick={() => setConditions((c) => c.filter((_, i) => i !== index))}
                >
                  Убрать
                </button>
              </div>
            );
          })}

          <button
            className="btn-link"
            onClick={() => setConditions((c) => [...c, { field: "priority", value: "", negate: false }])}
          >
            + Добавить условие
          </button>

          <h3 className="form-section">Кому уходит заявка</h3>
          <div className="form-row">
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">Выберите исполнителя или группу</option>
              <optgroup label="Инженер">
                {options.users.map((u) => (
                  <option key={`e${u.id}`} value={`engineer:${u.id}`}>
                    {u.full_name}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Группа">
                {options.teams.map((t) => (
                  <option key={`t${t.id}`} value={`team:${t.id}`}>
                    {t.name}
                  </option>
                ))}
              </optgroup>
            </select>
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
