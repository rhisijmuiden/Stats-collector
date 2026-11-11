import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import FollowersPage from "./pages/Followers";
import GoalsPage from "./pages/Goals";
import DashboardsPage from "./pages/Dashboards";
import LiveWallsPage from "./pages/LiveWalls";
import { useApp } from "./lib/app";
import Layout from "./components/Layout";
import { Login, Setup } from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Users from "./pages/Users";
import SsoPage from "./pages/Sso";
import Branding from "./pages/Branding";
import Email from "./pages/Email";
import Backup from "./pages/Backup";
import Sources from "./pages/Sources";
import GeneralSettings from "./pages/GeneralSettings";
import InfoPage from "./pages/Info";
import Help from "./pages/Help";
import Profile from "./pages/Profile";
import Content from "./pages/Content";
import EditorsPage from "./pages/Editors";
import ReportsPage from "./pages/Reports";
import AlertsPage from "./pages/Alerts";
import BestTimesPage from "./pages/BestTimes";
import StoriesPage from "./pages/Stories";
import DigestPage from "./pages/Digest";
import PublicReport, { ArchivedReport } from "./pages/ReportView";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, loading } = useApp();
  const location = useLocation();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}

function EditorsOnly({ children }: { children: JSX.Element }) {
  const { user } = useApp();
  return user && ["admin", "editor_in_chief", "editor"].includes(user.role) ? children : <Navigate to="/" replace />;
}

function EditorsInChief({ children }: { children: JSX.Element }) {
  const { user } = useApp();
  return user && ["admin", "editor_in_chief"].includes(user.role) ? children : <Navigate to="/" replace />;
}

function AdminOnly({ children }: { children: JSX.Element }) {
  const { user } = useApp();
  return user?.role === "admin" ? children : <Navigate to="/" replace />;
}

export default function App() {
  const { loading } = useApp();
  if (loading) return null;
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/setup" element={<Setup />} />
      <Route path="/r/:token" element={<PublicReport />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<Dashboard />} />
        <Route path="content" element={<Content />} />
        <Route path="editors" element={<EditorsOnly><EditorsPage /></EditorsOnly>} />
        <Route path="followers" element={<FollowersPage />} />
        <Route path="goals" element={<GoalsPage />} />
        <Route path="dashboards" element={<DashboardsPage />} />
        <Route path="stories" element={<StoriesPage />} />
        <Route path="best-times" element={<BestTimesPage />} />
        <Route path="alerts" element={<EditorsOnly><AlertsPage /></EditorsOnly>} />
        <Route path="reports" element={<EditorsOnly><ReportsPage /></EditorsOnly>} />
        <Route path="reports/runs/:id" element={<EditorsOnly><ArchivedReport /></EditorsOnly>} />
        <Route path="info" element={<InfoPage />} />
        <Route path="help" element={<Help />} />
        <Route path="help/:slug" element={<Help />} />
        <Route path="profile" element={<Profile />} />
        <Route path="admin/sources" element={<AdminOnly><Sources /></AdminOnly>} />
        <Route path="admin/users" element={<AdminOnly><Users /></AdminOnly>} />
        <Route path="admin/sso" element={<AdminOnly><SsoPage /></AdminOnly>} />
        <Route path="admin/livewalls" element={<AdminOnly><LiveWallsPage /></AdminOnly>} />
        <Route path="admin/branding" element={<AdminOnly><Branding /></AdminOnly>} />
        <Route path="admin/email" element={<AdminOnly><Email /></AdminOnly>} />
        <Route path="admin/digest" element={<EditorsInChief><DigestPage /></EditorsInChief>} />
        <Route path="admin/backup" element={<AdminOnly><Backup /></AdminOnly>} />
        <Route path="admin/settings" element={<AdminOnly><GeneralSettings /></AdminOnly>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
