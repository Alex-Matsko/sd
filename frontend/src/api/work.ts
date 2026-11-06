import { apiRequest, apiPage } from './client';

export type ProjectStatus = 'draft' | 'planning' | 'approval' | 'approved' | 'in_progress' | 'paused' | 'completed' | 'cancelled';
export type WorkTaskStatus = 'backlog' | 'ready' | 'in_progress' | 'review' | 'done' | 'cancelled';
export interface PlanTask {
  id: number; title: string; description: string; stage: string; assignee_name: string | null;
  start_date: string | null; due_date: string | null; estimate_minutes: number; depends_on_ids: number[];
}
export interface PlanSnapshot {
  title: string; description: string; owner_name: string | null; start_date: string | null; due_date: string | null;
  plan_version: number; tasks: PlanTask[];
}
export interface WorkTask extends Omit<PlanTask, 'assignee_name'> {
  status: WorkTaskStatus; assignee_id: number | null; actual_minutes: number; completion_note: string;
  completed_at: string | null; blocked: boolean; overdue: boolean;
}
export interface WorkApproval {
  id: number; round: number; user_id: number | null; contact_id: number | null; approver_name: string;
  state: 'pending' | 'approved' | 'rejected' | 'superseded'; snapshot: PlanSnapshot; comment: string;
  requested_at: string; decided_at: string | null;
}
export interface ProjectSummary {
  id: number; title: string; description: string; organization_id: number | null; owner_id: number;
  status: ProjectStatus; start_date: string | null; due_date: string | null; version: number; approval_round: number;
  created_at: string; updated_at: string; task_count: number; completed_count: number; progress_pct: number;
  estimate_minutes: number; actual_minutes: number; overdue: boolean; can_manage: boolean;
}
export interface Project extends ProjectSummary {
  tasks: WorkTask[]; approvals: WorkApproval[];
  tickets: {id: number; display_number: string; subject: string; status: string}[];
  comments: {id: number; author_name: string; body: string; created_at: string; user_id: number}[];
  history: {id: number; action: string; author_name: string | null; changes: Record<string, unknown>; created_at: string}[];
}
export interface ProjectInput {
  title: string; description: string; organization_id?: number | null; owner_id?: number;
  start_date: string | null; due_date: string | null;
}
export interface TaskInput {
  title: string; description: string; stage: string; assignee_id: number | null; start_date: string | null;
  due_date: string | null; estimate_minutes: number; depends_on_ids: number[];
}
export const listProjects = (query: {q?: string; status?: string; mine?: boolean; overdue?: boolean; limit?: number; offset?: number}) =>
  apiPage<ProjectSummary>('/projects', query);
export const getProject = (id: number) => apiRequest<Project>(`/projects/${id}`);
export const createProject = (body: ProjectInput) => apiRequest<Project>('/projects', {method: 'POST', body});
export const updateProject = (p: Project, body: Omit<ProjectInput, 'organization_id'>) => apiRequest<Project>(`/projects/${p.id}`, {method: 'PATCH', body: {...body, version: p.version}});
export const transitionProject = (p: Project, status: ProjectStatus, reason: string) => apiRequest<Project>(`/projects/${p.id}/status`, {method: 'POST', body: {status, reason, version: p.version}});
export const saveTask = (p: Project, id: number | null, body: TaskInput | Partial<WorkTask>) => apiRequest<Project>(`/projects/${p.id}/tasks${id ? `/${id}` : ''}`, {method: id ? 'PATCH' : 'POST', body: {...body, version: p.version}});
export const requestProjectApproval = (p: Project, user_ids: number[], contact_ids: number[]) => apiRequest<Project>(`/projects/${p.id}/approvals`, {method: 'POST', body: {version: p.version, user_ids, contact_ids}});
export const decideProjectApproval = (p: Project, id: number, decision: 'approved' | 'rejected', comment: string) => apiRequest<Project>(`/projects/${p.id}/approvals/${id}/decision`, {method: 'POST', body: {version: p.version, decision, comment}});
export const linkProjectTicket = (p: Project, ticket_id: number) => apiRequest<Project>(`/projects/${p.id}/tickets`, {method: 'POST', body: {version: p.version, ticket_id}});
export const unlinkProjectTicket = (p: Project, ticketId: number) => apiRequest<Project>(`/projects/${p.id}/tickets/${ticketId}`, {method: 'DELETE', body: {version: p.version}});
export const addProjectComment = (id: number, body: string) => apiRequest<Project>(`/projects/${id}/comments`, {method: 'POST', body: {body}});

export const ticketProjects = (ticketId: number) => apiRequest<{id: number; title: string; status: ProjectStatus}[]>(`/tickets/${ticketId}/projects`);
