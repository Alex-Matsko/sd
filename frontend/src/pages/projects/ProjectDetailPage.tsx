import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { addProjectComment, decideProjectApproval, getProject, linkProjectTicket, requestProjectApproval, saveTask, transitionProject, unlinkProjectTicket, updateProject } from '../../api/work';
import type { Project, ProjectStatus, TaskInput, WorkTask, WorkTaskStatus } from '../../api/work';
import { listContacts, listOrganizations, listTickets, listUsers } from '../../api/endpoints';
import type { User } from '../../api/types';
import { useAuth } from '../../auth/AuthContext';
import { EmptyState, ErrorBanner, Loading } from '../../components/ui';
import { PlanSnapshotView } from '../../components/PlanSnapshotView';
import { IconPlus } from '../../components/icons';
import { APPROVAL_LABELS, PROJECT_LABELS, PROJECT_TRANSITIONS, TASK_LABELS, hours, taskTargets, workDate } from '../../lib/work';
import { formatDateTime } from '../../lib/labels';

function WorkDialog({title, children, onClose}: {title: string; children: ReactNode; onClose: () => void}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {ref.current?.showModal();}, []);
  return <dialog ref={ref} className="modal work-dialog" onCancel={e => {e.preventDefault(); onClose();}}>
    <div className="modal-head"><h3>{title}</h3><button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Закрыть окно">Закрыть</button></div>{children}
  </dialog>;
}

function ProjectEditor({project: p, users, onSave, onClose}: {project: Project; users: User[]; onSave: (p: Project) => void; onClose: () => void}) {
  const [title, setTitle] = useState(p.title);
  const [description, setDescription] = useState(p.description);
  const [owner, setOwner] = useState(p.owner_id);
  const [start, setStart] = useState(p.start_date ?? '');
  const [due, setDue] = useState(p.due_date ?? '');
  const save = useMutation({mutationFn: () => updateProject(p, {title, description, owner_id: owner, start_date: start || null, due_date: due || null}), onSuccess: onSave});
  return <WorkDialog title="План проекта" onClose={onClose}><form onSubmit={e => {e.preventDefault(); save.mutate();}}>
    <div className="modal-body work-form">{save.isError && <ErrorBanner message={save.error.message}/>}
      <label>Название<input type="text" required minLength={3} maxLength={300} value={title} onChange={e => setTitle(e.target.value)}/></label>
      <label>Цель и ожидаемый результат<textarea rows={5} value={description} maxLength={20000} onChange={e => setDescription(e.target.value)}/></label>
      <label>Руководитель<select value={owner} onChange={e => setOwner(Number(e.target.value))}>{users.filter(u => u.is_active).map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></label>
      <div className="work-fields"><label>Начало<input type="date" value={start} onChange={e => setStart(e.target.value)}/></label><label>Завершение<input type="date" value={due} min={start || undefined} onChange={e => setDue(e.target.value)}/></label></div>
      <p className="muted">Описание и задачи входят в план, который увидят согласующие, включая клиента.</p>
    </div><div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Отмена</button><button className="btn btn-primary" disabled={save.isPending}>Сохранить план</button></div>
  </form></WorkDialog>;
}

function TaskEditor({project: p, task, users, userId, initialStatus, onSave, onClose}: {project: Project; task: WorkTask | null; users: User[]; userId?: number; initialStatus?: WorkTaskStatus; onSave: (p: Project) => void; onClose: () => void}) {
  const planning = ['draft', 'planning'].includes(p.status) && p.can_manage;
  const [title, setTitle] = useState(task?.title ?? '');
  const [description, setDescription] = useState(task?.description ?? '');
  const [stage, setStage] = useState(task?.stage ?? 'Основной этап');
  const [assignee, setAssignee] = useState(String(task?.assignee_id ?? ''));
  const [start, setStart] = useState(task?.start_date ?? '');
  const [due, setDue] = useState(task?.due_date ?? p.due_date ?? '');
  const [estimate, setEstimate] = useState(task ? String(task.estimate_minutes / 60) : '');
  const [deps, setDeps] = useState<number[]>(task?.depends_on_ids ?? []);
  const [status, setStatus] = useState<WorkTaskStatus>(initialStatus ?? task?.status ?? 'backlog');
  const [actual, setActual] = useState(task ? String(task.actual_minutes / 60) : '0');
  const [note, setNote] = useState(task?.completion_note ?? '');
  const mayExecute = p.can_manage || task?.assignee_id === userId;
  const targets = task ? taskTargets(task.status, p.status, p.can_manage, task.blocked) : [];
  const mutation = useMutation({mutationFn: () => {
    const plan: TaskInput = {title, description, stage, assignee_id: assignee ? Number(assignee) : null, start_date: start || null, due_date: due || null, estimate_minutes: Math.round(Number(estimate) * 60), depends_on_ids: deps};
    return saveTask(p, task?.id ?? null, task ? {...(planning ? plan : {}), ...(status !== task.status ? {status} : {}), ...(!planning && mayExecute && ['in_progress', 'paused'].includes(p.status) ? {actual_minutes: Math.round(Number(actual) * 60), completion_note: note} : {})} : plan);
  }, onSuccess: onSave});
  return <WorkDialog title={task ? `Задача #${task.id}` : 'Новая задача'} onClose={onClose}><form onSubmit={e => {e.preventDefault(); mutation.mutate();}}>
    <div className="modal-body work-form">{mutation.isError && <ErrorBanner message={mutation.error.message}/>}
      {task?.blocked && <p className="work-warning">Заблокирована: сначала нужно принять предшествующие задачи.</p>}
      <label>Название<input type="text" required minLength={3} maxLength={300} disabled={!planning} value={title} onChange={e => setTitle(e.target.value)}/></label>
      <label>Описание и критерии готовности<textarea rows={3} disabled={!planning} value={description} maxLength={10000} onChange={e => setDescription(e.target.value)}/></label>
      <div className="work-fields"><label>Этап<input type="text" list="work-stages" required maxLength={100} disabled={!planning} value={stage} onChange={e => setStage(e.target.value)}/><datalist id="work-stages">{Array.from(new Set(p.tasks.map(t => t.stage))).map(s => <option value={s} key={s}/>)}</datalist></label>
        <label>Исполнитель<select disabled={!planning} value={assignee} onChange={e => setAssignee(e.target.value)}><option value="">Не назначен</option>{users.filter(u => u.is_active).map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></label>
        <label>Начало<input type="date" min={p.start_date ?? undefined} max={p.due_date ?? undefined} disabled={!planning} value={start} onChange={e => setStart(e.target.value)}/></label>
        <label>Срок<input type="date" min={start || p.start_date || undefined} max={p.due_date ?? undefined} disabled={!planning} value={due} onChange={e => setDue(e.target.value)}/></label>
        <label>План, часов<input type="number" min={0} max={100000} step="any" disabled={!planning} value={estimate} onChange={e => setEstimate(e.target.value)}/></label>
        {task && <label>Статус<select value={status} disabled={!mayExecute || targets.length === 0} onChange={e => setStatus(e.target.value as WorkTaskStatus)}>{Array.from(new Set([task.status, ...targets])).map(s => <option key={s} value={s}>{TASK_LABELS[s]}</option>)}</select></label>}</div>
      {planning && p.tasks.some(t => t.id !== task?.id) && <fieldset className="work-checklist"><legend>Начать после выполнения</legend>{p.tasks.filter(t => t.id !== task?.id && t.status !== 'cancelled').map(t => <label key={t.id} className="work-checkbox"><input type="checkbox" checked={deps.includes(t.id)} onChange={e => setDeps(e.target.checked ? [...deps, t.id] : deps.filter(id => id !== t.id))}/>{t.title}</label>)}</fieldset>}
      {task && <><label>Фактически затрачено, часов<input type="number" min={0} max={100000} step="any" disabled={!mayExecute || (task.status === 'done' && status === 'done') || !['in_progress', 'paused'].includes(p.status)} value={actual} onChange={e => setActual(e.target.value)}/></label>
        <label>Результат и примечание для приёмки<textarea rows={3} disabled={!mayExecute || (task.status === 'done' && status === 'done') || !['in_progress', 'paused'].includes(p.status)} value={note} maxLength={10000} onChange={e => setNote(e.target.value)}/></label>
        <p className="muted">Факт нужен для контроля проекта. Для списания часов по договору используйте учёт времени в заявке.</p></>}
    </div><div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Закрыть</button>{(planning || (mayExecute && (p.status === 'in_progress' || p.status === 'paused'))) && <button className="btn btn-primary" disabled={mutation.isPending}>Сохранить задачу</button>}</div>
  </form></WorkDialog>;
}

function ApprovalPanel({project: p, users, onSave}: {project: Project; users: User[]; onSave: (p: Project) => void}) {
  const {user} = useAuth();
  const [selectedUsers, setSelectedUsers] = useState<number[]>([]);
  const [selectedContacts, setSelectedContacts] = useState<number[]>([]);
  const [comment, setComment] = useState('');
  const contacts = useQuery({queryKey: ['contacts', p.organization_id], queryFn: () => listContacts(p.organization_id ?? undefined), enabled: p.organization_id != null});
  const request = useMutation({mutationFn: () => requestProjectApproval(p, selectedUsers, selectedContacts), onSuccess: onSave});
  const decide = useMutation({mutationFn: ({id, decision}: {id: number; decision: 'approved' | 'rejected'}) => decideProjectApproval(p, id, decision, comment), onSuccess: result => {setComment(''); onSave(result);}});
  const own = p.approvals.find(a => a.round === p.approval_round && a.user_id === user?.id && a.state === 'pending' && p.status === 'approval');
  return <div className="work-stack">
    {p.can_manage && ['draft', 'planning'].includes(p.status) && <div className="panel work-form">
      <h2>Отправить план на согласование</h2><p className="muted">Все выбранные участники должны одобрить одну версию. Замечание любого участника возвращает план на доработку.</p>
      {request.isError && <ErrorBanner message={request.error.message}/>}
      <div className="work-fields"><fieldset className="work-checklist"><legend>Сотрудники · минимум один</legend>{users.filter(u => u.is_active && u.id !== p.owner_id && u.id !== user?.id).map(u => <label className="work-checkbox" key={u.id}><input type="checkbox" checked={selectedUsers.includes(u.id)} onChange={e => setSelectedUsers(e.target.checked ? [...selectedUsers,u.id] : selectedUsers.filter(id => id !== u.id))}/>{u.full_name}</label>)}</fieldset>
        <fieldset className="work-checklist"><legend>Представители клиента{p.organization_id ? " · минимум один" : ""}</legend>{contacts.isError && <ErrorBanner message={contacts.error.message}/>}{!p.organization_id && <p className="muted">Доступно для проекта организации.</p>}{contacts.data?.length === 0 && <p className="muted">Добавьте контакт в организации.</p>}{contacts.data?.map(c => <label className="work-checkbox" key={c.id}><input type="checkbox" checked={selectedContacts.includes(c.id)} onChange={e => setSelectedContacts(e.target.checked ? [...selectedContacts,c.id] : selectedContacts.filter(id => id !== c.id))}/>{c.full_name}</label>)}</fieldset></div>
      <p className="muted">Клиент увидит запрос в личном кабинете. Убедитесь, что для выбранного контакта настроен вход. Внешние сообщения не отправляются.</p>
      <button className="btn btn-primary" disabled={!selectedUsers.length || (!!p.organization_id && !selectedContacts.length) || request.isPending} onClick={() => request.mutate()}>Отправить на согласование</button>
    </div>}
    {own && <div className="panel work-form"><h2>Ваше решение · круг {own.round}</h2><PlanSnapshotView plan={own.snapshot}/><label>Замечания или комментарий<textarea value={comment} maxLength={5000} rows={3} onChange={e => setComment(e.target.value)}/></label>
      {decide.isError && <ErrorBanner message={decide.error.message}/>}<div className="work-actions"><button className="btn btn-primary" disabled={decide.isPending} onClick={() => decide.mutate({id: own.id, decision: 'approved'})}>Согласовать</button><button className="btn" disabled={decide.isPending || comment.trim().length < 3} onClick={() => decide.mutate({id: own.id, decision: 'rejected'})}>Вернуть на доработку</button></div></div>}
    {p.approvals.length === 0 && <EmptyState text="Согласований пока нет. Заполните задачи, назначьте исполнителей и укажите сроки."/>}
    {Array.from(new Set(p.approvals.map(a => a.round))).reverse().map(round => <div className="panel work-form" key={round}><div className="work-card-top"><h2>Круг согласования {round}</h2><span className="muted">{round === p.approval_round && p.status !== 'planning' && p.status !== 'cancelled' ? 'Текущий' : 'История'}</span></div>
      {p.approvals.filter(a => a.round === round).map(a => <div className="work-approval-row" key={a.id}><div><strong>{a.approver_name}</strong><small className="muted">{a.contact_id ? 'Представитель клиента' : 'Сотрудник'} · {formatDateTime(a.decided_at ?? a.requested_at)}</small>{a.comment && <p className="work-text">{a.comment}</p>}</div><span className={`work-state work-state-${a.state}`}>{APPROVAL_LABELS[a.state]}</span></div>)}
      <details><summary>Посмотреть отправленную версию плана</summary><PlanSnapshotView plan={p.approvals.find(a => a.round === round)!.snapshot}/></details>
    </div>)}
  </div>;
}

const HISTORY_LABELS: Record<string, string> = {created: 'Проект создан', plan_updated: 'План изменён', task_created: 'Задача добавлена', task_updated: 'Задача изменена', status_changed: 'Состояние проекта изменено', approval_requested: 'План отправлен на согласование', approval_decided: 'Получено решение', ticket_linked: 'Заявка связана', ticket_unlinked: 'Связь с заявкой удалена'};

export function ProjectDetailPage() {
  const id = Number(useParams().projectId);
  const {user} = useAuth();
  const qc = useQueryClient();
  const [tab, setTab] = useState('plan');
  const [editor, setEditor] = useState<{project: Project; task: WorkTask | null; initialStatus?: WorkTaskStatus} | null>(null);
  const [projectEditor, setProjectEditor] = useState<Project | null>(null);
  const [nextStatus, setNextStatus] = useState<ProjectStatus | ''>('');
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  const [ticket, setTicket] = useState('');
  const [ticketSearch, setTicketSearch] = useState('');
  const [dragId, setDragId] = useState<number | null>(null);
  const [overColumn, setOverColumn] = useState<WorkTaskStatus | null>(null);
  const project = useQuery({queryKey: ['project', id], queryFn: () => getProject(id), enabled: Number.isInteger(id) && id > 0, refetchInterval: 30000});
  const users = useQuery({queryKey: ['users'], queryFn: listUsers});
  const orgs = useQuery({queryKey: ['organizations'], queryFn: listOrganizations});
  const p = project.data;
  const planning = !!p && ['draft', 'planning'].includes(p.status);
  const tickets = useQuery({queryKey: ['project-ticket-options', p?.organization_id, ticketSearch], queryFn: () => listTickets({organization_id: p?.organization_id ?? undefined, q: ticketSearch || undefined, limit: 30}), enabled: !!p?.can_manage && planning});
  function saved(result: Project) {
    qc.setQueryData(['project', id], result);
    qc.invalidateQueries({queryKey: ['projects']});
    qc.invalidateQueries({queryKey: ['notifications']});
  }
  const move = useMutation({mutationFn: ({task, status}: {task: WorkTask; status: WorkTaskStatus}) => saveTask(p!, task.id, {status}), onSuccess: saved, onError: () => qc.invalidateQueries({queryKey: ['project', id]})});
  const transition = useMutation({mutationFn: () => transitionProject(p!, nextStatus as ProjectStatus, reason), onSuccess: result => {saved(result); setNextStatus(''); setReason('');}});
  const addComment = useMutation({mutationFn: () => addProjectComment(id, comment.trim()), onSuccess: result => {saved(result); setComment('');}});
  const link = useMutation({mutationFn: () => linkProjectTicket(p!, Number(ticket)), onSuccess: result => {saved(result); setTicket('');}});
  const unlink = useMutation({mutationFn: (ticketId: number) => unlinkProjectTicket(p!, ticketId), onSuccess: saved});
  if (project.isLoading) return <div className="view"><Loading/></div>;
  if (project.isError) return <div className="view"><ErrorBanner message={project.error.message}/><Link to="/projects">Вернуться к проектам</Link></div>;
  if (!p) return <div className="view"><EmptyState text="Проект не найден"/></div>;
  const usersById = new Map((users.data ?? []).map(u => [u.id, u.full_name]));
  const canAct = (t: WorkTask) => p.can_manage || t.assignee_id === user?.id;
  function changeTask(t: WorkTask, status: WorkTaskStatus) {
    if (status === 'done' && t.completion_note.trim().length < 3) setEditor({project: p!, task: t, initialStatus: status});
    else move.mutate({task: t, status});
  }
  const stages = Array.from(new Set(p.tasks.map(t => t.stage)));
  const visibleTasks = p.tasks.filter(t => t.status !== 'cancelled');
  const columns: WorkTaskStatus[] = ['backlog', 'ready', 'in_progress', 'review', 'done'];
  const dragged = p.tasks.find(t => t.id === dragId);
  return <div className="view work-view">
    <Link to="/projects" className="muted">← Все проекты</Link>
    <div className="work-heading"><div><div className="work-eyebrow">ПР-{p.id} · {p.organization_id ? orgs.data?.find(o => o.id === p.organization_id)?.name : 'Внутренний проект'}</div><h1 className="view-title">{p.title}</h1></div><span className={`work-state work-state-${p.status}`}>{PROJECT_LABELS[p.status]}</span></div>
    <p className="work-text work-description">{p.description || 'Добавьте цель и ожидаемый результат в план проекта.'}</p>
    <div className="work-summary"><div><span className="muted">Руководитель</span><strong>{usersById.get(p.owner_id) ?? '—'}</strong></div><div><span className="muted">Плановые сроки</span><strong className={p.overdue ? 'work-overdue' : ''}>{workDate(p.start_date)} — {workDate(p.due_date)}{p.overdue ? ' · Просрочен' : ''}</strong></div><div><span className="muted">Трудозатраты</span><strong>{hours(p.estimate_minutes)} план · {hours(p.actual_minutes)} факт</strong></div><div><span className="muted">Выполнено {p.completed_count} из {p.task_count}</span><div className="work-progress"><span style={{width: `${p.progress_pct}%`}}/></div><strong>{p.progress_pct}%</strong></div></div>
    {p.can_manage && <div className="work-actions">
      {planning && <><button className="btn btn-primary" onClick={() => setEditor({project: p, task: null})}><IconPlus size={15}/> Добавить задачу</button><button className="btn" onClick={() => setProjectEditor(p)}>Изменить план</button><button className="btn" onClick={() => setTab('approval')}>Согласовать план</button></>}
      <select aria-label="Действие с проектом" value={nextStatus} onChange={e => {setNextStatus(e.target.value as ProjectStatus | ''); transition.reset();}}><option value="">Изменить состояние…</option>{PROJECT_TRANSITIONS[p.status].map(s => <option key={s} value={s}>{s === 'planning' && !planning ? 'Вернуть в планирование' : PROJECT_LABELS[s]}</option>)}</select>
    </div>}
    {nextStatus && <form className="panel work-form" onSubmit={e => {e.preventDefault(); transition.mutate();}}><h3>{PROJECT_LABELS[p.status]} → {PROJECT_LABELS[nextStatus]}</h3>{['planning','cancelled'].includes(nextStatus) && !planning && <p className="work-warning">Прежнее согласование перестанет разрешать выполнение работ. После изменения плана потребуется новое.</p>}
      <label>Причина или комментарий<textarea rows={2} value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} required={['planning','cancelled'].includes(nextStatus) && !planning} minLength={3}/></label>
      {transition.isError && <ErrorBanner message={transition.error.message}/>}<div className="work-actions"><button className="btn btn-primary" disabled={transition.isPending}>Применить состояние</button><button type="button" className="btn" onClick={() => setNextStatus('')}>Отмена</button></div></form>}
    <div className="work-tabs" role="tablist" aria-label="Разделы проекта">{[['plan','План и этапы'],['board','Канбан'],['approval',`Согласование${p.approvals.some(a => a.state === 'pending' && a.user_id === user?.id && p.status === 'approval') ? ' •' : ''}`],['activity','Обсуждение и история']].map(([key,label]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</div>
    {move.isError && <ErrorBanner message={move.error.message}/>}
    {tab === 'plan' && <div className="work-stack">{p.tasks.length === 0 && <EmptyState text="Начните с этапов: подготовка, внедрение, проверка. Добавьте задачи, сроки и зависимости."/>}
      {stages.map(stage => <section className="panel" key={stage}><div className="panel-head"><h2>{stage}</h2><span className="muted">{p.tasks.filter(t => t.stage === stage && t.status === 'done').length} / {p.tasks.filter(t => t.stage === stage && t.status !== 'cancelled').length} выполнено</span></div><div className="work-table-scroll"><table className="work-table"><thead><tr><th>Задача</th><th>Исполнитель</th><th>Сроки</th><th>План / факт</th><th>Статус</th></tr></thead><tbody>{p.tasks.filter(t => t.stage === stage).map(t => <tr key={t.id} className={t.status === 'cancelled' ? 'work-cancelled' : ''}>
        <td><button className="btn-link work-task-title" onClick={() => setEditor({project: p, task: t})}>#{t.id} · {t.title}</button>{t.description && <p className="work-task-description">{t.description}</p>}{t.depends_on_ids.length > 0 && <small className={t.blocked ? 'work-warning-text' : 'muted'}>{t.blocked ? 'Ожидает' : 'После'}: {t.depends_on_ids.map(i => p.tasks.find(d => d.id === i)?.title ?? `#${i}`).join(', ')}</small>}</td>
        <td>{t.assignee_id ? usersById.get(t.assignee_id) ?? '—' : 'Не назначен'}</td><td className={t.overdue ? 'work-overdue' : ''}>{workDate(t.start_date)}<br/>{workDate(t.due_date)}</td><td>{hours(t.estimate_minutes)}<br/><span className="muted">{hours(t.actual_minutes)}</span></td><td><span className={`work-state work-state-${t.status}`}>{TASK_LABELS[t.status]}</span>{canAct(t) && <select aria-label={`Изменить статус: ${t.title}`} value="" disabled={move.isPending || !taskTargets(t.status,p.status,p.can_manage,t.blocked).length} onChange={e => changeTask(t,e.target.value as WorkTaskStatus)}><option value="">Перевести…</option>{taskTargets(t.status,p.status,p.can_manage,t.blocked).map(s => <option key={s} value={s}>{TASK_LABELS[s]}</option>)}</select>}</td>
      </tr>)}</tbody></table></div></section>)}
      <section className="panel work-form"><h2>Связанные заявки</h2><p className="muted">Заявки сохраняют свои SLA и правила доступа.</p>{p.tickets.map(t => <div className="work-card-top" key={t.id}><Link to={`/tickets/${t.id}`}>{t.display_number} · {t.subject}</Link>{p.can_manage && planning && <button className="btn btn-ghost" disabled={unlink.isPending} onClick={() => unlink.mutate(t.id)}>Убрать связь</button>}</div>)}
        {p.tickets.length === 0 && <p className="muted">Доступных связанных заявок нет.</p>}{p.can_manage && planning && <div className="work-actions"><input type="text" aria-label="Поиск заявки для проекта" placeholder="Найти заявку" value={ticketSearch} onChange={e => setTicketSearch(e.target.value)}/><select aria-label="Связанная заявка" value={ticket} onChange={e => setTicket(e.target.value)}><option value="">Выберите заявку…</option>{tickets.data?.items.filter(t => !p.tickets.some(link => link.id === t.id)).map(t => <option key={t.id} value={t.id}>{t.display_number} · {t.subject}</option>)}</select><button className="btn" disabled={!ticket || link.isPending} onClick={() => link.mutate()}>Связать</button></div>}{(link.isError || unlink.isError || tickets.isError) && <ErrorBanner message={(link.error ?? unlink.error ?? tickets.error)!.message}/>}</section>
    </div>}
    {tab === 'board' && <><p className="muted">Перетаскивайте карточки или открывайте задачу для изменения статуса. Готовность принимает руководитель проекта.</p><div className="work-board">{columns.map(column => {
      const columnTasks = visibleTasks.filter(t => t.status === column);
      const dropAllowed = !!dragged && taskTargets(dragged.status,p.status,p.can_manage,dragged.blocked).includes(column) && canAct(dragged);
      return <section key={column} className={`work-column ${overColumn === column && dropAllowed ? 'work-column-target' : ''}`} onDragOver={e => {if(dropAllowed && !move.isPending) {e.preventDefault(); setOverColumn(column);}}} onDragLeave={() => setOverColumn(null)} onDrop={e => {e.preventDefault(); setOverColumn(null); if(dragged && dropAllowed && !move.isPending) changeTask(dragged, column); setDragId(null);}}>
        <div className="work-column-head"><strong>{TASK_LABELS[column]}</strong><span>{columnTasks.length}</span></div>{columnTasks.map(t => <button type="button" key={t.id} className={`work-task-card ${t.blocked ? 'work-task-blocked' : ''}`} draggable={canAct(t) && !move.isPending && !!taskTargets(t.status,p.status,p.can_manage,t.blocked).length} onDragStart={() => setDragId(t.id)} onDragEnd={() => {setDragId(null); setOverColumn(null);}} onClick={() => setEditor({project: p, task: t})}>
          <small className="muted">{t.stage} · #{t.id}</small><strong>{t.title}</strong>{t.blocked && <small className="work-warning-text">Ожидает предшествующие задачи</small>}<span className={t.overdue ? 'work-overdue' : 'muted'}>{workDate(t.due_date)}</span><div className="work-card-top"><span>{t.assignee_id ? usersById.get(t.assignee_id) : 'Не назначен'}</span><span>{hours(t.estimate_minutes)}</span></div>
        </button>)}{columnTasks.length === 0 && <p className="muted work-column-empty">Задач нет</p>}</section>;
    })}</div>{p.tasks.some(t => t.status === 'cancelled') && <p className="muted">Отменённые задачи доступны на вкладке «План и этапы».</p>}</>}
    {tab === 'approval' && <ApprovalPanel key={p.id} project={p} users={users.data ?? []} onSave={saved}/>}
    {tab === 'activity' && <div className="work-activity"><section className="panel work-form"><h2>Внутреннее обсуждение</h2><p className="muted">Комментарии видят только сотрудники с доступом к проекту.</p><form className="work-form" onSubmit={e => {e.preventDefault(); addComment.mutate();}}><textarea aria-label="Комментарий к проекту" placeholder="Решения, риски, вопросы по работе…" value={comment} maxLength={10000} rows={3} onChange={e => setComment(e.target.value)}/>{addComment.isError && <ErrorBanner message={addComment.error.message}/>}<button className="btn btn-primary" disabled={!comment.trim() || addComment.isPending}>Добавить комментарий</button></form>{p.comments.map(c => <article className="work-comment" key={c.id}><div className="work-card-top"><strong>{c.author_name}</strong><small className="muted">{formatDateTime(c.created_at)}</small></div><p className="work-text">{c.body}</p></article>)}</section>
      <section className="panel work-form"><h2>История изменений</h2>{p.history.map(h => <article className="work-history" key={h.id}><strong>{HISTORY_LABELS[h.action] ?? h.action}</strong><small className="muted">{h.author_name ?? (h.changes.contact_id ? 'Представитель клиента' : 'Система')} · {formatDateTime(h.created_at)}</small>{typeof h.changes.reason === 'string' && h.changes.reason && <p>{h.changes.reason}</p>}{typeof h.changes.title === 'string' && <p>{h.changes.title}</p>}{h.action === 'status_changed' && <p>{PROJECT_LABELS[h.changes.from as ProjectStatus]} → {PROJECT_LABELS[h.changes.to as ProjectStatus]}</p>}{h.action === 'approval_decided' && <p>{h.changes.decision === 'approved' ? 'Согласовано' : 'На доработку'}{typeof h.changes.comment === 'string' && h.changes.comment ? `: ${h.changes.comment}` : ''}</p>}</article>)}</section></div>}
    {editor && <TaskEditor project={editor.project} task={editor.task} initialStatus={editor.initialStatus} users={users.data ?? []} userId={user?.id} onClose={() => {setEditor(null); qc.invalidateQueries({queryKey: ['project', id]});}} onSave={result => {saved(result); setEditor(null);}}/>}
    {projectEditor && <ProjectEditor project={projectEditor} users={users.data ?? []} onClose={() => {setProjectEditor(null); qc.invalidateQueries({queryKey: ['project', id]});}} onSave={result => {saved(result); setProjectEditor(null);}}/>}
  </div>;
}
