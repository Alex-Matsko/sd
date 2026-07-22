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
} from "../../api/endpoints";
import { EmptyState, ErrorBanner, Loading } from "../../components/ui";
import type { RoutingRuleType } from "../../api/types";

const RULE_TYPE_LABELS: Record<RoutingRuleType, string> = {
  organization_to_engineer: "Организация → инженер",
  category_to_team: "Категория → команда",
};

export function RoutingRulesPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const rulesQuery = useQuery({ queryKey: ["routing-rules"], queryFn: listRoutingRules });
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: listOrganizations });
  const categoriesQuery = useQuery({ queryKey: ["categories"], queryFn: listCategories });
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const teamsQuery = useQuery({ queryKey: ["teams"], queryFn: listTeams });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteRoutingRule(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["routing-rules"] }),
  });

  if (rulesQuery.isLoading) return <div className="view"><Loading /></div>;
  if (rulesQuery.isError) return <div className="view"><ErrorBanner message={(rulesQuery.error as Error).message} /></div>;

  const orgsById = new Map((orgsQuery.data ?? []).map((o) => [o.id, o]));
  const categoriesById = new Map((categoriesQuery.data ?? []).map((c) => [c.id, c]));
  const usersById = new Map((usersQuery.data ?? []).map((u) => [u.id, u]));
  const teamsById = new Map((teamsQuery.data ?? []).map((t) => [t.id, t]));
  const rules = [...(rulesQuery.data ?? [])].sort((a, b) => a.order - b.order);

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Маршрутизация
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          Добавить правило
        </button>
      </div>

      {rules.length === 0 && <EmptyState text="Правил маршрутизации пока нет" />}
      {rules.length > 0 && (
        <div className="list">
          <div className="list-head" style={{ gridTemplateColumns: "60px 1.4fr 1.4fr 1.4fr 90px 40px" }}>
            <span>№</span>
            <span>Тип</span>
            <span>Условие</span>
            <span>Назначение</span>
            <span>Активно</span>
            <span />
          </div>
          {rules.map((r) => (
            <div className="list-row" style={{ gridTemplateColumns: "60px 1.4fr 1.4fr 1.4fr 90px 40px" }} key={r.id}>
              <span className="mono">{r.order}</span>
              <span>{RULE_TYPE_LABELS[r.rule_type]}</span>
              <span className="muted">
                {r.organization_id ? orgsById.get(r.organization_id)?.name : r.category_id ? categoriesById.get(r.category_id)?.name : "—"}
              </span>
              <span className="muted">
                {r.target_engineer_id ? usersById.get(r.target_engineer_id)?.full_name : r.target_team_id ? teamsById.get(r.target_team_id)?.name : "—"}
              </span>
              <span>{r.is_active ? "Да" : "Нет"}</span>
              <span>
                <button className="icon-btn" onClick={() => deleteMutation.mutate(r.id)}>
                  ×
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <NewRoutingRuleModal
          organizations={orgsQuery.data ?? []}
          categories={categoriesQuery.data ?? []}
          users={usersQuery.data ?? []}
          teams={teamsQuery.data ?? []}
          nextOrder={rules.length ? Math.max(...rules.map((r) => r.order)) + 1 : 1}
          onClose={() => setShowModal(false)}
          onCreated={() => {
            setShowModal(false);
            qc.invalidateQueries({ queryKey: ["routing-rules"] });
          }}
        />
      )}
    </div>
  );
}

function NewRoutingRuleModal({
  organizations,
  categories,
  users,
  teams,
  nextOrder,
  onClose,
  onCreated,
}: {
  organizations: { id: number; name: string }[];
  categories: { id: number; name: string }[];
  users: { id: number; full_name: string }[];
  teams: { id: number; name: string }[];
  nextOrder: number;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [ruleType, setRuleType] = useState<RoutingRuleType>("organization_to_engineer");
  const [organizationId, setOrganizationId] = useState<number | "">("");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [targetEngineerId, setTargetEngineerId] = useState<number | "">("");
  const [targetTeamId, setTargetTeamId] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      await createRoutingRule({
        order: nextOrder,
        rule_type: ruleType,
        is_active: true,
        organization_id: ruleType === "organization_to_engineer" ? (organizationId ? Number(organizationId) : null) : null,
        category_id: ruleType === "category_to_team" ? (categoryId ? Number(categoryId) : null) : null,
        target_engineer_id: ruleType === "organization_to_engineer" ? (targetEngineerId ? Number(targetEngineerId) : null) : null,
        target_team_id: ruleType === "category_to_team" ? (targetTeamId ? Number(targetTeamId) : null) : null,
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось создать правило");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Новое правило маршрутизации</h3>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {error && <ErrorBanner message={error} />}
          <div className="form-row">
            <label className="form-label">Тип правила</label>
            <select value={ruleType} onChange={(e) => setRuleType(e.target.value as RoutingRuleType)}>
              <option value="organization_to_engineer">Организация → инженер</option>
              <option value="category_to_team">Категория → команда</option>
            </select>
          </div>

          {ruleType === "organization_to_engineer" ? (
            <div className="form-grid">
              <div className="form-row">
                <label className="form-label">Организация</label>
                <select value={organizationId} onChange={(e) => setOrganizationId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Любая</option>
                  {organizations.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">Инженер</label>
                <select value={targetEngineerId} onChange={(e) => setTargetEngineerId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Выберите инженера</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ) : (
            <div className="form-grid">
              <div className="form-row">
                <label className="form-label">Категория</label>
                <select value={categoryId} onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Любая</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label className="form-label">Команда</label>
                <select value={targetTeamId} onChange={(e) => setTargetTeamId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Выберите команду</option>
                  {teams.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            Создать
          </button>
        </div>
      </div>
    </div>
  );
}
