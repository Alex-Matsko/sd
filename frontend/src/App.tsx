import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./layout/Layout";
import { Loading } from "./components/ui";
import { LoginPage } from "./pages/LoginPage";
const ProjectsPage = lazy(() => import("./pages/projects/ProjectsPage").then(m => ({default: m.ProjectsPage})));
const ProjectDetailPage = lazy(() => import("./pages/projects/ProjectDetailPage").then(m => ({default: m.ProjectDetailPage})));
import { DashboardPage } from "./pages/DashboardPage";
import { TicketsPage } from "./pages/TicketsPage";
import { NewTicketPage } from "./pages/NewTicketPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ClientReportsPage } from "./pages/ClientReportsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { CallsPage } from "./pages/CallsPage";
import { TicketDetailPage } from "./pages/TicketDetailPage";
import { OrganizationsPage } from "./pages/directory/OrganizationsPage";
import { OrganizationDetailPage } from "./pages/directory/OrganizationDetailPage";
import { ContactsPage } from "./pages/directory/ContactsPage";
import { ContractsPage } from "./pages/directory/ContractsPage";
import { AssetsPage } from "./pages/directory/AssetsPage";
import { PriorityMatrixPage } from "./pages/settings/PriorityMatrixPage";
import { TariffsPage } from "./pages/settings/TariffsPage";
import { CalendarsPage } from "./pages/settings/CalendarsPage";
import { CategoriesPage } from "./pages/settings/CategoriesPage";
import { RoutingRulesPage } from "./pages/settings/RoutingRulesPage";
import { ChannelsSettingsPage } from "./pages/settings/ChannelsSettingsPage";
import { AutomationRulesPage } from "./pages/settings/AutomationRulesPage";
import { UsersPage } from "./pages/settings/UsersPage";
import { ResponseTemplatesPage } from "./pages/settings/ResponseTemplatesPage";
import { TicketSchedulesPage } from "./pages/settings/TicketSchedulesPage";
import { OperationsPage } from "./pages/settings/OperationsPage";
import { MonitoringPage } from "./pages/settings/MonitoringPage";

function RequireManager({ children }: { children: JSX.Element }) {
  const { user } = useAuth();
  if (user?.role !== "manager" && user?.role !== "admin") {
    return <div className="view"><h1 className="view-title">Недостаточно прав</h1><p className="muted">Этот раздел доступен руководителю и администратору.</p></div>;
  }
  return children;
}

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) return <Loading />;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
  return children;
}

export default function App() {
  return (
    <Suspense fallback={<Loading />}><Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="tickets" element={<TicketsPage />} />
        <Route path="tickets/new" element={<NewTicketPage />} />
        <Route path="tickets/:ticketId" element={<TicketDetailPage />} />
        <Route path="reports" element={<RequireManager><ReportsPage /></RequireManager>} />
        <Route path="client-reports" element={<RequireManager><ClientReportsPage /></RequireManager>} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="calls" element={<CallsPage />} />
        <Route path="directory/organizations" element={<OrganizationsPage />} />
        <Route path="directory/organizations/:organizationId" element={<OrganizationDetailPage />} />
        <Route path="directory/contacts" element={<ContactsPage />} />
        <Route path="directory/contracts" element={<ContractsPage />} />
        <Route path="directory/assets" element={<AssetsPage />} />
        <Route path="settings/priority" element={<RequireManager><PriorityMatrixPage /></RequireManager>} />
        <Route path="settings/tariffs" element={<RequireManager><TariffsPage /></RequireManager>} />
        <Route path="settings/calendars" element={<RequireManager><CalendarsPage /></RequireManager>} />
        <Route path="settings/categories" element={<RequireManager><CategoriesPage /></RequireManager>} />
        <Route path="settings/routing" element={<RequireManager><RoutingRulesPage /></RequireManager>} />
        <Route path="settings/channels" element={<RequireManager><ChannelsSettingsPage /></RequireManager>} />
        <Route path="settings/automation" element={<RequireManager><AutomationRulesPage /></RequireManager>} />
        <Route path="settings/users" element={<RequireManager><UsersPage /></RequireManager>} />
        <Route path="settings/templates" element={<RequireManager><ResponseTemplatesPage /></RequireManager>} />
        <Route path="settings/schedules" element={<RequireManager><TicketSchedulesPage /></RequireManager>} />
        <Route path="settings/operations" element={<RequireManager><OperationsPage /></RequireManager>} />
        <Route path="settings/monitoring" element={<RequireManager><MonitoringPage /></RequireManager>} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes></Suspense>
  );
}
