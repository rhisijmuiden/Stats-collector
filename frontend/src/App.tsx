import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useApp } from "./lib/app";
import Layout from "./components/Layout";
import { Login, Setup } from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Users from "./pages/Users";
import SsoPage from "./pages/Sso";
import Branding from "./pages/Branding";
import Email from "./pages/Email";
import Backup from "./pages/Backup";
import GeneralSettings from "./pages/GeneralSettings";
import InfoPage from "./pages/Info";
import Help from "./pages/Help";
import Profile from "./pages/Profile";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, loading } = useApp();
  const location = useLocation();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
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
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<Dashboard />} />
        <Route path="info" element={<InfoPage />} />
        <Route path="help" element={<Help />} />
        <Route path="help/:slug" element={<Help />} />
        <Route path="profile" element={<Profile />} />
        <Route path="admin/users" element={<AdminOnly><Users /></AdminOnly>} />
        <Route path="admin/sso" element={<AdminOnly><SsoPage /></AdminOnly>} />
        <Route path="admin/branding" element={<AdminOnly><Branding /></AdminOnly>} />
        <Route path="admin/email" element={<AdminOnly><Email /></AdminOnly>} />
        <Route path="admin/backup" element={<AdminOnly><Backup /></AdminOnly>} />
        <Route path="admin/settings" element={<AdminOnly><GeneralSettings /></AdminOnly>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
