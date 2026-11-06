import { useEffect, useRef, useState } from "react";
import { BrandMark } from "../components/BrandMark";
import { CommandMenu } from "../components/CommandMenu";
import type { ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { Avatar } from "../components/ui";
import { listNotifications, markAllNotificationsRead, markNotificationRead } from "../api/endpoints";
import { connectNotifications } from "../api/realtime";
import {
  isSoundEnabled,
  playNotificationSound,
  setSoundEnabled,
  startTitleFlash,
  stopTitleFlash,
} from "../lib/notificationAlerts";
import {
  IconBell,
  IconProjects,
  IconMenu,
  IconBuilding,
  IconChevronDown,
  IconChevronRight,
  IconClock,
  IconFileText,
  IconGrid,
  IconInbox,
  IconLogout,
  IconPhone,
  IconPlus,
  IconRoute,
  IconServer,
  IconSettings,
  IconTicket,
  IconUsers,
} from "../components/icons";
import { NOTIFICATION_TYPE_LABELS, USER_ROLE_LABELS, formatDateTime } from "../lib/labels";
import type { Notification } from "../api/types";

interface NavGroup {
  key: string;
  label: string;
  icon: ReactNode;
  items: { to: string; label: string; icon: ReactNode; end?: boolean }[];
}

const GROUPS: NavGroup[] = [
  {
    key: "reports",
    label: "Отчёты",
    icon: <IconFileText size={16} />,
    items: [
      { to: "/reports", label: "Сводный отчёт", icon: <IconGrid size={15} /> },
      { to: "/client-reports", label: "Отчёты клиентам", icon: <IconFileText size={15} /> },
    ],
  },
  {
    key: "directory",
    label: "Справочники",
    icon: <IconBuilding size={16} />,
    items: [
      { to: "/directory/organizations", label: "Организации", icon: <IconBuilding size={15} /> },
      { to: "/directory/contacts", label: "Контакты", icon: <IconUsers size={15} /> },
      { to: "/directory/contracts", label: "Договоры", icon: <IconFileText size={15} /> },
      { to: "/directory/assets", label: "Активы", icon: <IconServer size={15} /> },
    ],
  },
  {
    key: "settings",
    label: "Настройки",
    icon: <IconSettings size={16} />,
    items: [
      { to: "/settings/priority", label: "Матрица приоритетов", icon: <IconGrid size={15} /> },
      { to: "/settings/tariffs", label: "Тарифы и SLA", icon: <IconFileText size={15} /> },
      { to: "/settings/calendars", label: "Рабочий календарь", icon: <IconClock size={15} /> },
      { to: "/settings/categories", label: "Категории", icon: <IconGrid size={15} /> },
      { to: "/settings/routing", label: "Маршрутизация", icon: <IconRoute size={15} /> },
      { to: "/settings/channels", label: "Каналы", icon: <IconInbox size={15} /> },
      { to: "/settings/operations", label: "Состояние системы", icon: <IconServer size={15} /> },
      { to: "/settings/monitoring", label: "Мониторинг", icon: <IconServer size={15} /> },
      { to: "/settings/automation", label: "Автоматизация", icon: <IconClock size={15} /> },
      { to: "/settings/templates", label: "Шаблоны ответов", icon: <IconFileText size={15} /> },
      { to: "/settings/schedules", label: "Плановые заявки", icon: <IconClock size={15} /> },
      { to: "/settings/users", label: "Сотрудники", icon: <IconUsers size={15} /> },
    ],
  },
];

/** Звук и мигающая вкладка при новом уведомлении.
 *
 *  Колокольчик виден, только когда инженер смотрит на панель, а заявка
 *  приходит, пока он в другой вкладке. Сигналить нужно ровно на новых
 *  уведомлениях: без сравнения с уже виденными звук раздавался бы на каждом
 *  опросе списка, а при загрузке страницы — на всём накопившемся хвосте.
 */
function useNotificationAlerts(notifications: Notification[], unreadCount: number, isLoaded: boolean) {
  const seenIds = useRef<Set<number> | null>(null);

  useEffect(() => {
    // Пока список не загружен, он пуст — и запоминать эту пустоту как
    // «уже виденное» нельзя: пришедший следом хвост непрочитанных выглядел
    // бы новым, и панель звенела бы при каждом открытии.
    if (!isLoaded) return;

    const unread = notifications.filter((n) => !n.read_at);

    if (seenIds.current === null) {
      // Первая загрузка: то, что накопилось до прихода на страницу, — не
      // новость, звонить об этом не нужно.
      seenIds.current = new Set(unread.map((n) => n.id));
      return;
    }

    const fresh = unread.filter((n) => !seenIds.current!.has(n.id));
    unread.forEach((n) => seenIds.current!.add(n.id));
    if (fresh.length === 0) return;

    playNotificationSound();
    // Мигать имеет смысл только в фоновой вкладке: если человек смотрит на
    // панель, он и так увидел колокольчик.
    if (document.hidden) startTitleFlash(unreadCount);
  }, [notifications, unreadCount, isLoaded]);

  // Вернулись на вкладку — мигание больше не нужно.
  useEffect(() => {
    function onVisible() {
      if (!document.hidden) stopTitleFlash();
    }
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
      stopTitleFlash();
    };
  }, []);

  // Все уведомления прочитаны в другой вкладке — заголовок вернуть.
  useEffect(() => {
    if (unreadCount === 0) stopTitleFlash();
  }, [unreadCount]);
}


function NotificationBell() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [soundOn, setSoundOn] = useState(isSoundEnabled);
  const ref = useRef<HTMLDivElement>(null);

  const notificationsQuery = useQuery({
    queryKey: ["notifications"],
    queryFn: () => listNotifications(),
    // Kept as a fallback alongside the websocket below: if a proxy blocks
    // websockets the bell still updates, just less promptly.
    refetchInterval: 30_000,
  });

  // Live push (ТЗ р. 8). The payload isn't merged into the cache directly -
  // refetching keeps one source of truth for the list and its read state.
  useEffect(() => connectNotifications(() => qc.invalidateQueries({ queryKey: ["notifications"] })), [qc]);

  const readMutation = useMutation({
    mutationFn: (id: number) => markNotificationRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const readAllMutation = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const notifications = notificationsQuery.data ?? [];
  const unreadCount = notifications.filter((n) => !n.read_at).length;

  useNotificationAlerts(notifications, unreadCount, notificationsQuery.isSuccess);

  return (
    <div className="notification-bell" ref={ref}>
      <button className="icon-btn" title="Уведомления" aria-label="Уведомления" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <IconBell size={18} />
        {unreadCount > 0 && <span className="notification-badge">{unreadCount > 9 ? "9+" : unreadCount}</span>}
      </button>
      {open && (
        <div className="notification-dropdown">
          <div className="notification-dropdown-head">
            <span>Уведомления</span>
            <div className="spacer" />
            {/* В открытом офисе звук нужен не всем, а выключать его через
                настройки браузера — не вариант: он и так тихий. */}
            <button
              className="btn-link"
              title={soundOn ? "Выключить звук уведомлений" : "Включить звук уведомлений"}
              onClick={() => {
                const next = !soundOn;
                setSoundEnabled(next);
                setSoundOn(next);
                // Проба вслух: иначе непонятно, что именно включилось.
                if (next) playNotificationSound();
              }}
            >
              {soundOn ? "Звук вкл." : "Звук выкл."}
            </button>
            {unreadCount > 0 && (
              <button className="btn-link" onClick={() => readAllMutation.mutate()}>
                Прочитать все
              </button>
            )}
          </div>
          <div className="notification-list">
            {notifications.length === 0 && <p className="muted" style={{ padding: "12px 14px" }}>Уведомлений нет</p>}
            {notifications.map((n) => (
              <button
                key={n.id}
                className={`notification-row ${n.read_at ? "" : "unread"}`}
                onClick={() => {
                  if (!n.read_at) readMutation.mutate(n.id);
                  if (n.type === "channel_error") navigate("/settings/operations");
                  else if (n.project_id) navigate(`/projects/${n.project_id}`);
                  else if (n.ticket_id) navigate(`/tickets/${n.ticket_id}`);
                  setOpen(false);
                }}
              >
                <span className="notification-type">{NOTIFICATION_TYPE_LABELS[n.type]}</span>
                <span className="notification-title">{n.title}</span>
                <span className="muted notification-time">{formatDateTime(n.created_at)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem("sd_theme") ?? "system");
  const canManage = user?.role === "admin" || user?.role === "manager";
  const currentGroup = GROUPS.find((group) => group.items.some((item) => location.pathname.startsWith(item.to)));
  const pageTitle = currentGroup?.items.find((item) => location.pathname.startsWith(item.to))?.label
    ?? (location.pathname.startsWith("/projects") ? "Проекты" : location.pathname === "/dashboard" ? "Обзор работы" : location.pathname === "/profile" ? "Мой профиль" : location.pathname === "/calls" ? "Звонки" : location.pathname === "/tickets/new" ? "Новая заявка" : "Заявки");

  useEffect(() => {
    setMobileOpen(false);
    if (currentGroup) setOpenGroups((prev) => ({ ...prev, [currentGroup.key]: true }));
    document.title = `${pageTitle} · Служба поддержки`;
  }, [location.pathname, currentGroup, pageTitle]);

  useEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.dataset.theme = theme;
    localStorage.setItem("sd_theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!mobileOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMobileOpen(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [mobileOpen]);

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({ reports: false, directory: false, settings: false });

  function toggleGroup(key: string) {
    setOpenGroups((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleLogout() {
    const ending = logout();
    navigate("/login", { replace: true });
    await ending;
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Перейти к содержимому</a>
      {mobileOpen && <button className="sidebar-overlay" aria-label="Закрыть меню" onClick={() => setMobileOpen(false)} />}
      <aside id="main-navigation" className={`sidebar${mobileOpen ? " sidebar-open" : ""}`}>

        <div className="sidebar-brand">
          <BrandMark />
          <div><span className="brand-name">Открытые Горизонты</span><span className="brand-caption">SERVICE DESK</span></div>
        </div>

        <nav className="sidebar-nav" aria-label="Главное меню">
          <span className="nav-section-label">Рабочее пространство</span>
          <NavLink to="/dashboard" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <IconGrid size={16} />
            <span>Обзор работы</span>
          </NavLink>
          <NavLink to="/tickets" end className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <IconInbox size={16} />
            <span>Очередь заявок</span>
          </NavLink>
          <NavLink to="/tickets/new" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <IconPlus size={16} />
            <span>Новая заявка</span>
          </NavLink>
          <NavLink to="/projects" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}><IconProjects size={17} /><span>Проекты</span></NavLink>
          <NavLink to="/calls" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <IconPhone size={16} />
            <span>Звонки</span>
          </NavLink>

          {GROUPS.filter((group) => canManage || group.key === "directory").map((group) => (
            <div className="nav-group" key={group.key}>
              <button className="nav-group-head" aria-expanded={!!openGroups[group.key]} onClick={() => toggleGroup(group.key)}>
                {openGroups[group.key] ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
                {group.icon}
                <span>{group.label}</span>
              </button>
              {openGroups[group.key] && (
                <div className="nav-group-items">
                  {group.items.map((item) => (
                    <NavLink key={item.to} to={item.to} className={({ isActive }) => `nav-item nested ${isActive ? "active" : ""}`}>
                      {item.icon}
                      <span>{item.label}</span>
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer"><span className="sidebar-footer-dot" /> Служба поддержки<span className="muted">Открытые Горизонты</span></div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <button className="icon-btn mobile-menu-button" aria-label="Открыть меню" aria-expanded={mobileOpen} aria-controls="main-navigation" onClick={() => setMobileOpen((open) => !open)}><IconMenu size={20} /></button>
          <div className="topbar-title">
            {location.pathname.startsWith("/projects") ? <IconProjects size={18} /> : location.pathname === "/dashboard" ? <IconGrid size={18} /> : <IconTicket size={18} />}
            <span>{pageTitle}</span>
          </div>
          <div className="spacer" />
          <CommandMenu />
          <select className="theme-select" aria-label="Цветовая тема" value={theme} onChange={(e) => setTheme(e.target.value)}><option value="system">Тема: системная</option><option value="light">Тема: светлая</option><option value="dark">Тема: тёмная</option></select>
          <NotificationBell />
          {user && (
            <div className="topbar-user">
              <button
                className="topbar-user-link"
                title="Профиль"
                onClick={() => navigate("/profile")}
                style={{ display: "flex", alignItems: "center", gap: 10, background: "none", border: "none", cursor: "pointer", padding: 0 }}
              >
                <Avatar name={user.full_name} />
                <div className="topbar-user-info">
                  <span className="topbar-user-name">{user.full_name}</span>
                  <span className="topbar-user-role muted">{USER_ROLE_LABELS[user.role]}</span>
                </div>
              </button>
              <button className="icon-btn" title="Выйти" onClick={handleLogout}>
                <IconLogout size={17} />
              </button>
            </div>
          )}
        </header>
        <main id="main-content" className="app-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
