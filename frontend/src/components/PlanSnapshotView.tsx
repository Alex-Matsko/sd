import type { PlanSnapshot } from '../api/work';
import { hours, workDate } from '../lib/work';

export function PlanSnapshotView({plan}: {plan: PlanSnapshot}) {
  const byId = new Map(plan.tasks.map(t => [t.id, t.title]));
  return <div className="work-snapshot">
    <h3>{plan.title}</h3><p className="work-text">{plan.description || 'Цель не указана'}</p>
    <p className="muted">Руководитель: {plan.owner_name ?? '—'} · {workDate(plan.start_date)} — {workDate(plan.due_date)} · План {hours(plan.tasks.reduce((n,t) => n + t.estimate_minutes, 0))}</p>
    <div className="work-table-scroll"><table className="work-table"><thead><tr><th>Этап и задача</th><th>Исполнитель</th><th>Сроки</th><th>Оценка</th></tr></thead><tbody>{plan.tasks.map(t => <tr key={t.id}>
      <td><small className="muted">{t.stage}</small><strong>{t.title}</strong>{t.description && <p className="work-text">{t.description}</p>}{t.depends_on_ids.length > 0 && <small className="muted">После: {t.depends_on_ids.map(id => byId.get(id) ?? `#${id}`).join(', ')}</small>}</td>
      <td data-label="Исполнитель">{t.assignee_name ?? '—'}</td><td data-label="Сроки">{workDate(t.start_date)}<br/>{workDate(t.due_date)}</td><td data-label="Оценка">{hours(t.estimate_minutes)}</td>
    </tr>)}</tbody></table></div>
  </div>;
}
