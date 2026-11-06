import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { decidePortalProjectApproval, listPortalProjectApprovals } from './api';
import type { PortalProjectApproval } from './api';
import { PlanSnapshotView } from '../components/PlanSnapshotView';
import { APPROVAL_LABELS } from '../lib/work';
import { formatDateTime } from '../lib/labels';

function ApprovalCard({approval: a}: {approval: PortalProjectApproval}) {
  const qc = useQueryClient();
  const [comment, setComment] = useState('');
  const [open, setOpen] = useState(a.can_decide);
  const decide = useMutation({mutationFn: (decision: 'approved' | 'rejected') => decidePortalProjectApproval(a, decision, comment),
    onSuccess: () => {setComment(''); qc.invalidateQueries({queryKey: ['portal-project-approvals']});},
    onError: () => qc.invalidateQueries({queryKey: ['portal-project-approvals']})});
  return <article className="portal-card work-portal-approval"><div className="work-card-top"><button type="button" className="btn-link work-task-title" onClick={() => setOpen(!open)} aria-expanded={open}>{a.snapshot.title} · круг {a.round}</button><span className={`work-state work-state-${a.state}`}>{APPROVAL_LABELS[a.state]}</span></div>
    <p className="portal-muted">ПР-{a.project_id} · Запрошено {formatDateTime(a.requested_at)}</p>
    {open && <><PlanSnapshotView plan={a.snapshot}/>{a.comment && <p className="work-text">Ваш комментарий: {a.comment}</p>}{a.decided_at && <p className="portal-muted">Решение: {formatDateTime(a.decided_at)}</p>}
      {a.can_decide && <div className="work-form"><label>Замечания или комментарий<textarea value={comment} maxLength={5000} rows={3} onChange={e => setComment(e.target.value)}/></label><p className="portal-muted">Согласование относится к показанному плану, срокам и составу работ.</p>
        {decide.isError && <div role="alert" className="portal-error">{decide.error.message}</div>}<div className="work-actions"><button className="portal-btn portal-btn-primary" disabled={decide.isPending} onClick={() => decide.mutate('approved')}>Согласовать план</button><button className="portal-btn portal-btn-ghost" disabled={decide.isPending || comment.trim().length < 3} onClick={() => decide.mutate('rejected')}>Вернуть на доработку</button></div></div>}
    </>}
  </article>;
}

export function ProjectApprovals() {
  const approvals = useQuery({queryKey: ['portal-project-approvals'], queryFn: listPortalProjectApprovals, refetchInterval: 30000});
  if (approvals.isLoading) return <p className="portal-muted">Загрузка согласований…</p>;
  if (approvals.isError) return <div className="portal-error" role="alert">{approvals.error.message}</div>;
  const rows = approvals.data ?? [];
  if (!rows.length) return null;
  const pending = rows.filter(a => a.can_decide);
  const history = rows.filter(a => !a.can_decide);
  return <section className="work-stack work-portal-section"><h2>Согласование проектов {pending.length > 0 ? `· ${pending.length}` : ''}</h2>{pending.map(a => <ApprovalCard approval={a} key={a.id}/>)}{history.length > 0 && <details><summary>История согласований ({history.length})</summary><div className="work-stack">{history.map(a => <ApprovalCard approval={a} key={a.id}/>)}</div></details>}</section>;
}
