import type { ProjectStatus, WorkTaskStatus } from '../api/work';

export const PROJECT_LABELS: Record<ProjectStatus, string> = {
  draft: 'Черновик', planning: 'Планирование', approval: 'На согласовании', approved: 'Согласован',
  in_progress: 'В работе', paused: 'Приостановлен', completed: 'Завершён', cancelled: 'Отменён',
};
export const TASK_LABELS: Record<WorkTaskStatus, string> = {
  backlog: 'План', ready: 'К выполнению', in_progress: 'В работе', review: 'На проверке', done: 'Готово', cancelled: 'Отменена',
};
export const APPROVAL_LABELS = {pending: 'Ожидает решения', approved: 'Согласовано', rejected: 'На доработку', superseded: 'Отозвано'};
export const PROJECT_TRANSITIONS: Record<ProjectStatus, ProjectStatus[]> = {
  draft: ['planning', 'cancelled'], planning: ['cancelled'], approval: ['planning', 'cancelled'],
  approved: ['in_progress', 'planning', 'cancelled'], in_progress: ['paused', 'completed', 'planning', 'cancelled'],
  paused: ['in_progress', 'planning', 'cancelled'], completed: ['planning'], cancelled: ['planning'],
};
export const TASK_TRANSITIONS: Record<WorkTaskStatus, WorkTaskStatus[]> = {
  backlog: ['ready', 'in_progress', 'cancelled'], ready: ['backlog', 'in_progress', 'cancelled'],
  in_progress: ['ready', 'review'], review: ['in_progress', 'done'], done: ['ready'], cancelled: ['backlog', 'ready'],
};
export function hours(minutes: number) { return `${Number((minutes / 60).toFixed(1))} ч`; }
export function workDate(value: string | null) {
  return value ? new Date(`${value}T12:00:00`).toLocaleDateString('ru-RU', {day: 'numeric', month: 'short', year: 'numeric'}) : 'Не задан';
}
export function taskTargets(status: WorkTaskStatus, projectStatus: ProjectStatus, manager: boolean, blocked: boolean) {
  if (projectStatus === 'draft' || projectStatus === 'planning') {
    return manager ? (['backlog', 'ready', 'cancelled'] as WorkTaskStatus[]).filter(target => target !== status) : [];
  }
  return TASK_TRANSITIONS[status].filter(target => {
    if (projectStatus !== 'in_progress' || target === 'cancelled') return false;
    if ((target === 'done' || status === 'done') && !manager) return false;
    return !blocked || !['in_progress', 'review', 'done'].includes(target);
  });
}
