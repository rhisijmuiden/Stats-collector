import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { BarChart3, BookOpen, CheckCircle2, Circle } from "lucide-react";
import { useApp } from "../lib/app";
import { Card, PageHead } from "../components/ui";

const PHASES = ["p0", "p1", "p2", "p3", "p4", "p5"] as const;

export default function Dashboard() {
  const { t } = useTranslation();
  const { user, theme } = useApp();
  const channels = Object.entries(theme?.channels ?? {});
  return (
    <div className="page">
      <PageHead title={t("dashboard.title")} subtitle={t("dashboard.welcome", { name: user?.display_name })} />
      <Card>
        <div className="empty">
          <BarChart3 />
          <h2>{t("dashboard.emptyTitle")}</h2>
          <p>{t("dashboard.emptyText")}</p>
          <div className="row" style={{ justifyContent: "center", marginTop: 12 }}>
            {channels.map(([ch, color]) => (
              <span key={ch} className="badge"><i style={{ width: 9, height: 9, borderRadius: 3, background: color, display: "inline-block" }} />{t(`channels.${ch}`)}</span>
            ))}
          </div>
        </div>
      </Card>
      <div className="grid two">
        <Card title={t("dashboard.roadmap")} subtitle={t("dashboard.roadmapIntro")}>
          <ol className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: 10 }}>
            {PHASES.map((p, i) => (
              <li key={p} className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                {i === 0 ? <CheckCircle2 size={18} color="var(--good)" /> : <Circle size={18} color="var(--muted)" />}
                <div>
                  <b>{t(`dashboard.phases.${p}.title`)}</b>
                  <div className="muted small">{t(`dashboard.phases.${p}.text`)}</div>
                </div>
              </li>
            ))}
          </ol>
        </Card>
        <Card title={t("dashboard.nextSteps")}>
          <div className="stack">
            {user?.role === "admin" && (
              <>
                <Link to="/admin/branding">{t("dashboard.stepBranding")}</Link>
                <Link to="/admin/email">{t("dashboard.stepEmail")}</Link>
                <Link to="/admin/backup">{t("dashboard.stepBackup")}</Link>
                <Link to="/admin/users">{t("dashboard.stepUsers")}</Link>
              </>
            )}
            <Link to="/help" className="row"><BookOpen size={16} /> {t("dashboard.stepHelp")}</Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
