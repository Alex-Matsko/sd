import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listPriorityMatrix, replacePriorityMatrix } from "../../api/endpoints";
import { ErrorBanner, Loading } from "../../components/ui";
import { IMPACT_URGENCY_LABELS, PRIORITY_LABELS } from "../../lib/labels";
import type { ImpactUrgencyLevel, Priority } from "../../api/types";

const LEVELS: ImpactUrgencyLevel[] = ["high", "medium", "low"];
const PRIORITIES: Priority[] = ["P1", "P2", "P3", "P4"];

export function PriorityMatrixPage() {
  const qc = useQueryClient();
  const matrixQuery = useQuery({ queryKey: ["priority-matrix"], queryFn: listPriorityMatrix });
  const [grid, setGrid] = useState<Record<string, Priority>>({});

  useEffect(() => {
    if (!matrixQuery.data) return;
    const next: Record<string, Priority> = {};
    for (const rule of matrixQuery.data) {
      next[`${rule.impact}:${rule.urgency}`] = rule.priority;
    }
    setGrid(next);
  }, [matrixQuery.data]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const rules = LEVELS.flatMap((impact) =>
        LEVELS.map((urgency) => ({
          impact,
          urgency,
          priority: grid[`${impact}:${urgency}`] ?? "P3",
        }))
      );
      return replacePriorityMatrix(rules);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["priority-matrix"] }),
  });

  if (matrixQuery.isLoading) return <div className="view"><Loading /></div>;
  if (matrixQuery.isError) return <div className="view"><ErrorBanner message={(matrixQuery.error as Error).message} /></div>;

  return (
    <div className="view">
      <div className="toolbar">
        <h1 className="view-title" style={{ marginBottom: 0 }}>
          Матрица приоритетов
        </h1>
        <div className="spacer" />
        <button className="btn btn-primary" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
          Сохранить
        </button>
      </div>
      <p className="muted">Impact × Urgency определяют итоговый приоритет заявки (если не задан вручную).</p>

      {saveMutation.isError && <ErrorBanner message={(saveMutation.error as Error).message} />}

      <table className="matrix-table">
        <thead>
          <tr>
            <th />
            {LEVELS.map((u) => (
              <th key={u}>Urgency: {IMPACT_URGENCY_LABELS[u]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {LEVELS.map((impact) => (
            <tr key={impact}>
              <th>Impact: {IMPACT_URGENCY_LABELS[impact]}</th>
              {LEVELS.map((urgency) => {
                const key = `${impact}:${urgency}`;
                return (
                  <td key={key}>
                    <select
                      value={grid[key] ?? "P3"}
                      onChange={(e) => setGrid((prev) => ({ ...prev, [key]: e.target.value as Priority }))}
                    >
                      {PRIORITIES.map((p) => (
                        <option key={p} value={p}>
                          {PRIORITY_LABELS[p]}
                        </option>
                      ))}
                    </select>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
