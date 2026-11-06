import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { createProject, listProjects } from '../../api/work';
import { listOrganizations, listUsers } from '../../api/endpoints';
import { EmptyState, ErrorBanner, Loading } from '../../components/ui';
import { IconPlus } from '../../components/icons';
import { useAuth } from '../../auth/AuthContext';
import { PROJECT_LABELS, hours, workDate } from '../../lib/work';
import type { ProjectStatus } from '../../api/work';

export function ProjectsPage() {
  const {user} = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [org, setOrg] = useState('');
  const [owner, setOwner] = useState('');
  const [start, setStart] = useState('');
  const [due, setDue] = useState('');
  const offset = Math.max(0, Number(params.get('offset')) || 0);
  const status = params.get('status') ?? '';
  const mine = params.get('mine') === 'true';
  const overdue = params.get('overdue') === 'true';
  const [search, setSearch] = useState(params.get('q') ?? '');
  const projects = useQuery({queryKey: ['projects', params.toString()], queryFn: () => listProjects({q: params.get('q') || undefined, status: status || undefined, mine, overdue, limit: 24, offset}), refetchInterval: 30000});
  const orgs = useQuery({queryKey: ['organizations'], queryFn: listOrganizations});
  const users = useQuery({queryKey: ['users'], queryFn: listUsers});
  const usersById = new Map((users.data ?? []).map(u => [u.id, u.full_name]));
  const orgsById = new Map((orgs.data ?? []).map(o => [o.id, o.name]));
  function filter(key: string, value: string) {
    setParams(prev => {const next = new URLSearchParams(prev); if(value) next.set(key, value); else next.delete(key); next.delete('offset'); return next;});
  }
  const create = useMutation({mutationFn: () => createProject({title, description, organization_id: org ? Number(org) : null, owner_id: Number(owner) || user?.id,
      start_date: start || null, due_date: due || null}), onSuccess: p => {qc.invalidateQueries({queryKey: ['projects']}); navigate(`/projects/${p.id}`);}});
  const rows = projects.data?.items ?? [];
  return <div className="view work-view">
    <div className="work-heading"><div><div className="work-eyebrow">Крупные задачи и изменения</div><h1 className="view-title">Проекты</h1><p className="muted">От согласованного плана до принятого результата.</p></div>
      <button className="btn btn-primary" onClick={() => setCreating(!creating)}><IconPlus size={16}/> Новый проект</button></div>
    {creating && <form className="panel work-form" onSubmit={e => {e.preventDefault(); create.mutate();}}>
      <div className="panel-head"><h2>Новый проект</h2><button type="button" className="btn btn-ghost" onClick={() => setCreating(false)}>Закрыть</button></div>
      {create.isError && <ErrorBanner message={create.error.message}/>}
      <label>Название<input type="text" required minLength={3} maxLength={300} value={title} onChange={e => setTitle(e.target.value)}/></label>
      <label>Цель и ожидаемый результат<textarea rows={3} maxLength={20000} value={description} onChange={e => setDescription(e.target.value)}/></label>
      <div className="work-fields"><label>Организация<select value={org} onChange={e => setOrg(e.target.value)}><option value="">Внутренний проект</option>{orgs.data?.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
        <label>Руководитель<select value={owner || user?.id} onChange={e => setOwner(e.target.value)}>{users.data?.filter(u => u.is_active && (user?.role !== 'engineer' || u.id === user.id)).map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></label>
        <label>Плановое начало<input type="date" value={start} onChange={e => setStart(e.target.value)}/></label><label>Срок завершения<input type="date" value={due} min={start || undefined} onChange={e => setDue(e.target.value)}/></label></div>
      <p className="muted">Цель и план задач будут видны назначенным представителям клиента при согласовании.</p>
      <button className="btn btn-primary" disabled={create.isPending}>Создать проект</button>
    </form>}
    <form className="work-filters" onSubmit={e => {e.preventDefault(); filter('q', search.trim());}}>
      <input type="text" aria-label="Поиск проектов" placeholder="Поиск по названию" value={search} onChange={e => setSearch(e.target.value)}/><button className="btn" type="submit">Найти</button>
      <select aria-label="Состояние проекта" value={status} onChange={e => filter('status', e.target.value)}><option value="">Все состояния</option>{Object.entries(PROJECT_LABELS).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select>
      <label className="work-checkbox"><input type="checkbox" checked={mine} onChange={e => filter('mine', e.target.checked ? 'true' : '')}/> Мои проекты</label>
      <label className="work-checkbox"><input type="checkbox" checked={overdue} onChange={e => filter('overdue', e.target.checked ? 'true' : '')}/> Просроченные</label>
    </form>
    {projects.isLoading && <Loading/>}{projects.isError && <ErrorBanner message={projects.error.message}/>}
    {projects.isSuccess && rows.length === 0 && <EmptyState text="Проектов по этим условиям пока нет. Создайте проект и разложите работу на этапы."/>}
    <div className="project-grid">{rows.map(p => <Link to={`/projects/${p.id}`} className="project-card" key={p.id}>
      <div className="work-card-top"><span className="work-code">ПР-{p.id}</span><span className={`work-state work-state-${p.status}`}>{PROJECT_LABELS[p.status as ProjectStatus]}</span></div>
      <h2>{p.title}</h2><p className="muted">{p.organization_id ? orgsById.get(p.organization_id) : 'Внутренний проект'}</p>
      <div className="work-progress" role="progressbar" aria-label="Выполнено задач" aria-valuenow={p.progress_pct} aria-valuemin={0} aria-valuemax={100}><span style={{width: `${p.progress_pct}%`}}/></div>
      <div className="work-card-top"><span>{p.completed_count} из {p.task_count} задач</span><strong>{p.progress_pct}%</strong></div>
      <div className="work-card-footer"><span>{usersById.get(p.owner_id) ?? '—'}</span><span className={p.overdue ? 'work-overdue' : ''}>{workDate(p.due_date)}</span></div>
      <small className="muted">План {hours(p.estimate_minutes)} · Факт {hours(p.actual_minutes)}</small>
    </Link>)}</div>
    {(projects.data?.total ?? 0) > 24 && <div className="work-pagination"><button className="btn" disabled={!offset} onClick={() => setParams(prev => {const n = new URLSearchParams(prev); n.set('offset', String(Math.max(0, offset - 24))); return n;})}>Назад</button><span>{offset + 1}–{Math.min(offset + 24, projects.data?.total ?? 0)} из {projects.data?.total}</span><button className="btn" disabled={offset + 24 >= (projects.data?.total ?? 0)} onClick={() => setParams(prev => {const n = new URLSearchParams(prev); n.set('offset', String(offset + 24)); return n;})}>Далее</button></div>}
  </div>;
}
