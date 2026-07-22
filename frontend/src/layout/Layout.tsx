import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { Avatar } from "../components/ui";
import { listNotifications, markAllNotificationsRead, markNotificationRead } from "../api/endpoints";
import {
  IconBell,
  IconBuilding,
  IconChevronDown,
  IconChevronRight,
  IconFileText,
  IconGrid,
  IconInbox,
  IconLogout,
  IconPlus,
  IconRoute,
  IconServer,
  IconSettings,
  IconTicket,
  IconUsers,
} from "../components/icons";
import { NOTIFICATION_TYPE_LABELS, USER_ROLE_LABELS, formatDateTime } from "../lib/labels";

interface NavGroup {
  key: string;
  label: string;
  icon: ReactNode;
  items: { to: string; label: string; icon: ReactNode; end?: boolean }[];
}

const GROUPS: NavGroup[] = [
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
      { to: "/settings/categories", label: "Категории", icon: <IconGrid size={15} /> },
      { to: "/settings/routing", label: "Маршрутизация", icon: <IconRoute size={15} /> },
      { to: "/settings/channels", label: "Каналы", icon: <IconInbox size={15} /> },
    ],
  },
];

function NotificationBell() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const notificationsQuery = useQuery({
    queryKey: ["notifications"],
    queryFn: () => listNotifications(),
    refetchInterval: 30_000,
  });

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

  return (
    <div className="notification-bell" ref={ref}>
      <button className="icon-btn" title="Уведомления" onClick={() => setOpen((v) => !v)}>
        <IconBell size={18} />
        {unreadCount > 0 && <span className="notification-badge">{unreadCount > 9 ? "9+" : unreadCount}</span>}
      </button>
      {open && (
        <div className="notification-dropdown">
          <div className="notification-dropdown-head">
            <span>Уведомления</span>
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
                  if (n.ticket_id) navigate(`/tickets/${n.ticket_id}`);
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
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({ directory: true, settings: false });

  function toggleGroup(key: string) {
    setOpenGroups((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark">ОГ</span>
          <span className="brand-name">Открытые Горизонты</span>
        </div>

        <nav className="sidebar-nav">
          <NavLink to="/dashboard" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <IconGrid size={16} />
            <span>Дашборд</span>
          </NavLink>
          <NavLink to="/tickets" end className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <IconInbox size={16} />
            <span>Очередь заявок</span>
          </NavLink>
          <NavLink to="/tickets/new" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <IconPlus size={16} />
            <span>Новая заявка</span>
          </NavLink>

          {GROUPS.map((group) => (
            <div className="nav-group" key={group.key}>
              <button className="nav-group-head" onClick={() => toggleGroup(group.key)}>
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
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="topbar-title">
            <IconTicket size={18} />
            <span>Служба поддержки</span>
          </div>
          <div className="spacer" />
          <NotificationBell />
          {user && (
            <div className="topbar-user">
              <Avatar name={user.full_name} />
              <div className="topbar-user-info">
                <span className="topbar-user-name">{user.full_name}</span>
                <span className="topbar-user-role muted">{USER_ROLE_LABELS[user.role]}</span>
              </div>
              <button className="icon-btn" title="Выйти" onClick={handleLogout}>
                <IconLogout size={17} />
              </button>
            </div>
          )}
        </header>
        <main className="app-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
