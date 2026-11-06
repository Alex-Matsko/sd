import { useEffect, useId, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { listTickets } from '../api/endpoints';
import { listProjects } from '../api/work';
import { useAuth } from '../auth/AuthContext';
import { IconArrowRight, IconGrid, IconPlus, IconProjects, IconSearch, IconTicket } from './icons';
import { ErrorBanner } from './ui';

interface Result { key: string; to: string; title: string; detail: string; kind: 'page' | 'ticket' | 'project' }
const PAGES: Result[] = [
  {key: 'dashboard', to: '/dashboard', title: 'Обзор работы', detail: 'Очередь, сроки и загрузка', kind: 'page'},
  {key: 'new-ticket', to: '/tickets/new', title: 'Создать заявку', detail: 'Новое обращение', kind: 'page'},
  {key: 'tickets', to: '/tickets', title: 'Очередь заявок', detail: 'Список и канбан', kind: 'page'},
  {key: 'projects', to: '/projects', title: 'Проекты', detail: 'Планирование и согласование', kind: 'page'},
  {key: 'profile', to: '/profile', title: 'Мой профиль', detail: 'Личные настройки', kind: 'page'},
];

function SearchDialog({onClose}: {onClose: () => void}) {
  const navigate = useNavigate();
  const {user} = useAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [selected, setSelected] = useState(0);
  const listId = useId();
  const query = search.trim();
  useEffect(() => {
    const el = dialog.current;
    const previous = document.activeElement;
    el?.showModal();
    return () => {el?.close(); if(previous instanceof HTMLElement && previous.isConnected) previous.focus();};
  }, []);
  useEffect(() => {const timer = setTimeout(() => setDebounced(query), 250); return () => clearTimeout(timer);}, [query]);
  const enabled = debounced.length >= 2 && debounced === query;
  const tickets = useQuery({queryKey: ['command-tickets', debounced], queryFn: () => listTickets({q: debounced, limit: 5}), enabled, staleTime: 15000});
  const projects = useQuery({queryKey: ['command-projects', debounced], queryFn: () => listProjects({q: debounced, limit: 5}), enabled, staleTime: 15000});
  const pages = [...PAGES, ...(user?.role === 'admin' || user?.role === 'manager' ? [
    {key: 'operations', to: '/settings/operations', title: 'Состояние системы', detail: 'Каналы и фоновые процессы', kind: 'page' as const},
    {key: 'reports', to: '/reports', title: 'Отчёты', detail: 'Показатели сервиса', kind: 'page' as const},
  ] : [])].filter(p => !query || p.title.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')));
  const ticketRows: Result[] = enabled ? (tickets.data?.items ?? []).map(t => ({key: `ticket-${t.id}`, to: `/tickets/${t.id}`, title: t.subject, detail: t.display_number, kind: 'ticket'})) : [];
  const projectRows: Result[] = enabled ? (projects.data?.items ?? []).map(p => ({key: `project-${p.id}`, to: `/projects/${p.id}`, title: p.title, detail: `ПР-${p.id}`, kind: 'project'})) : [];
  const results = [...pages, ...ticketRows, ...projectRows];
  const current = Math.min(selected, Math.max(0, results.length - 1));
  const loading = query.length >= 2 && (!enabled || tickets.isFetching || projects.isFetching);
  useEffect(() => {document.getElementById(`${listId}-${current}`)?.scrollIntoView({block: 'nearest'});}, [listId, current, results.length]);
  function go(result: Result) {onClose(); navigate(result.to);}
  return <dialog ref={dialog} className="command-dialog" aria-label="Быстрый поиск" onCancel={e => {e.preventDefault(); onClose();}} onKeyDown={e => {if(e.key === 'Escape') {e.preventDefault(); e.stopPropagation(); onClose();}}}>
    <div className="command-input-row"><IconSearch size={21}/><input type="search" role="combobox" aria-expanded="true" aria-controls={listId} aria-activedescendant={results[current] ? `${listId}-${current}` : undefined} aria-autocomplete="list" aria-label="Поиск заявок, проектов и разделов" placeholder="Заявка, проект или раздел…" value={search} onChange={e => {setSearch(e.target.value); setSelected(0);}} onKeyDown={e => {
      if(e.key === 'ArrowDown') {e.preventDefault(); setSelected((current + 1) % Math.max(1, results.length));}
      if(e.key === 'ArrowUp') {e.preventDefault(); setSelected((current - 1 + results.length) % Math.max(1, results.length));}
      if(e.key === 'Enter' && !e.nativeEvent.isComposing && results[current]) {e.preventDefault(); go(results[current]);}
    }}/><button className="command-close" type="button" onClick={onClose} aria-label="Закрыть поиск">Esc</button></div>
    <div className="command-results" id={listId} role="listbox" aria-label="Результаты поиска" aria-busy={loading}>
      {!query && <p className="command-section">Быстрый переход</p>}
      {results.map((r,index) => <button key={r.key} id={`${listId}-${index}`} role="option" aria-selected={index === current} className={`command-result ${index === current ? 'selected' : ''}`} onPointerMove={() => setSelected(index)} onClick={() => go(r)}>
        <span className="command-result-icon">{r.kind === 'ticket' ? <IconTicket/> : r.kind === 'project' || r.key === 'projects' ? <IconProjects/> : r.key === 'new-ticket' ? <IconPlus/> : <IconGrid/>}</span>
        <span className="command-result-text"><strong>{r.title}</strong><small>{r.kind === 'ticket' ? 'Заявка · ' : r.kind === 'project' ? 'Проект · ' : ''}{r.detail}</small></span><IconArrowRight size={16}/>
      </button>)}
      {loading && <p className="command-hint" role="status">Ищем заявки и проекты…</p>}
      {!loading && query.length === 1 && <p className="command-hint">Введите ещё один символ для поиска заявок и проектов.</p>}
      {!loading && query.length >= 2 && !results.length && !tickets.isError && !projects.isError && <p className="command-hint">Ничего не найдено. Попробуйте другое название или номер заявки.</p>}
    </div>
    {enabled && (tickets.isError || projects.isError) && <ErrorBanner message={(tickets.error ?? projects.error)!.message}/>}
    <div className="command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> выбрать <kbd>↵</kbd> открыть</span><span>Только доступные вам данные</span></div>
  </dialog>;
}

export function CommandMenu() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    function shortcut(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'k' && !e.isComposing) {
        e.preventDefault();
        if (!e.repeat && (!document.querySelector('dialog[open]') || open)) setOpen(value => !value);
      }
    }
    document.addEventListener('keydown', shortcut);
    return () => document.removeEventListener('keydown', shortcut);
  }, [open]);
  return <><button type="button" className="command-trigger" aria-label="Быстрый поиск" aria-keyshortcuts="Meta+K Control+K" onClick={() => setOpen(true)}><IconSearch size={17}/><span>Найти заявку или проект</span><kbd>⌘ / Ctrl K</kbd></button>{open && <SearchDialog onClose={() => setOpen(false)}/>}</>;
}
