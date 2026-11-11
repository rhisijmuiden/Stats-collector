import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Archive, BookOpen, FileBarChart, FileText, Info, LayoutDashboard, LogOut, Mail, Menu, Palette, Radio, Settings, ShieldCheck, UserCheck, Users, HeartHandshake, Target, Layers, MonitorPlay, BellRing, Clock, Newspaper, MailCheck } from "lucide-react";
import { useApp } from "../lib/app";
import { api, type User } from "../lib/api";
import { resolveMode } from "../lib/theme";
import { setLanguage } from "../i18n";
import { Toasts } from "./ui";

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("");
}

export function Brand() {
  const { theme, user } = useApp();
  const mode = resolveMode(user?.theme ?? "system");
  const sidebarDark = true; // the sidebar is dark in both modes
  const logo = (sidebarDark || mode === "dark" ? theme?.assets?.logo_dark : theme?.assets?.logo_light)
    ?? theme?.assets?.logo_light ?? "/favicon.svg";
  return (
    <div className="brand">
      <img src={logo} alt="" />
      <span>{theme?.app_name ?? "Stats Collector"}</span>
    </div>
  );
}

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { i18n } = useTranslation();
  const { user, setUser } = useApp();
  const change = async (lang: "en" | "nl") => {
    if (user) {
      const u = await api.patch<User>("/api/auth/me", { language: lang });
      setUser(u);
    } else {
      setLanguage(lang);
    }
  };
  return (
    <div className="seg" aria-label="Language">
      {(["en", "nl"] as const).map((l) => (
        <button key={l} type="button" aria-pressed={i18n.language === l} onClick={() => change(l)}>
          {compact ? l.toUpperCase() : l === "en" ? "English" : "Nederlands"}
        </button>
      ))}
    </div>
  );
}

export default function Layout() {
  const { t } = useTranslation();
  const { user, logout } = useApp();
  const [open, setOpen] = useState(false);
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => setOpen(false), [location.pathname]);

  useEffect(() => {
    if (user?.role !== "admin") return;
    api.get<{ check: { update_available: boolean } }>("/api/system/releases")
      .then((r) => setUpdateAvailable(r.check.update_available))
      .catch(() => undefined);
  }, [user?.role]);

  if (!user) return null;
  const isAdmin = user.role === "admin";
  const item = (to: string, Icon: typeof Users, label: string, dot = false) => (
    <NavLink to={to} end={to === "/"} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
      <Icon aria-hidden />
      {label}
      {dot && <span className="badge-dot" title={t("info.updateAvailable")} />}
    </NavLink>
  );

  return (
    <div className="shell">
      <div className="mobile-bar">
        <button className="icon-btn" onClick={() => setOpen(true)} aria-label={t("nav.openMenu")}>
          <Menu />
        </button>
        <Brand />
      </div>
      <aside className={`sidebar${open ? " open" : ""}`} aria-label={t("nav.main")}>
        <Brand />
        <div className="nav-label">{t("nav.analytics")}</div>
        {item("/", LayoutDashboard, t("nav.dashboard"))}
        {item("/dashboards", Layers, t("nav.dashboards"))}
        {item("/content", FileText, t("nav.content"))}
        {user.role !== "staff" && item("/editors", UserCheck, t("nav.editors"))}
        {item("/followers", HeartHandshake, t("nav.followers"))}
        {item("/goals", Target, t("nav.goals"))}
        {item("/stories", Newspaper, t("nav.stories"))}
        {item("/best-times", Clock, t("nav.bestTimes"))}
        {user.role !== "staff" && item("/alerts", BellRing, t("nav.alerts"))}
        {user.role !== "staff" && item("/reports", FileBarChart, t("nav.reports"))}
        {isAdmin && (
          <>
            <div className="nav-label">{t("nav.administration")}</div>
            {item("/admin/sources", Radio, t("nav.sources"))}
            {item("/admin/users", Users, t("nav.users"))}
            {item("/admin/sso", ShieldCheck, t("nav.sso"))}
            {item("/admin/livewalls", MonitorPlay, t("nav.livewalls"))}
            {item("/admin/branding", Palette, t("nav.branding"))}
            {item("/admin/email", Mail, t("nav.email"))}
            {item("/admin/digest", MailCheck, t("nav.digest"))}
            {item("/admin/backup", Archive, t("nav.backup"))}
            {item("/admin/settings", Settings, t("nav.settings"))}
          </>
        )}
        <div className="spacer" />
        {item("/help", BookOpen, t("nav.help"))}
        {item("/info", Info, t("nav.info"), updateAvailable)}
        <div className="user-chip">
          <button className="avatar" style={{ border: 0, cursor: "pointer" }} onClick={() => navigate("/profile")}
            aria-label={t("nav.profile")} title={t("nav.profile")}>
            {initials(user.display_name)}
          </button>
          <div className="who">
            <b>{user.display_name}</b>
            <small>{t(`roles.${user.role}`)}</small>
          </div>
          <button className="icon-btn" onClick={() => logout()} aria-label={t("nav.logout")} title={t("nav.logout")}>
            <LogOut />
          </button>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
      <Toasts />
    </div>
  );
}
