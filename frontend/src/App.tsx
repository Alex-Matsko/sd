import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./layout/Layout";
import { Loading } from "./components/ui";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { TicketsPage } from "./pages/TicketsPage";
import { NewTicketPage } from "./pages/NewTicketPage";
import { ReportsPage } from "./pages/ReportsPage";
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
import { CategoriesPage } from "./pages/settings/CategoriesPage";
import { RoutingRulesPage } from "./pages/settings/RoutingRulesPage";
import { ChannelsSettingsPage } from "./pages/settings/ChannelsSettingsPage";
import { AutomationRulesPage } from "./pages/settings/AutomationRulesPage";
import { UsersPage } from "./pages/settings/UsersPage";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
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
        <Route path="tickets" element={<TicketsPage />} />
        <Route path="tickets/new" element={<NewTicketPage />} />
        <Route path="tickets/:ticketId" element={<TicketDetailPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="calls" element={<CallsPage />} />
        <Route path="directory/organizations" element={<OrganizationsPage />} />
        <Route path="directory/organizations/:organizationId" element={<OrganizationDetailPage />} />
        <Route path="directory/contacts" element={<ContactsPage />} />
        <Route path="directory/contracts" element={<ContractsPage />} />
        <Route path="directory/assets" element={<AssetsPage />} />
        <Route path="settings/priority" element={<PriorityMatrixPage />} />
        <Route path="settings/tariffs" element={<TariffsPage />} />
        <Route path="settings/categories" element={<CategoriesPage />} />
        <Route path="settings/routing" element={<RoutingRulesPage />} />
        <Route path="settings/channels" element={<ChannelsSettingsPage />} />
        <Route path="settings/automation" element={<AutomationRulesPage />} />
        <Route path="settings/users" element={<UsersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
