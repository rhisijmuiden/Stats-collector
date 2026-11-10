import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Download, FileWarning, Printer } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/app";
import { applyTheme } from "../lib/theme";
import { Card, useLoad } from "../components/ui";
import { errorText } from "../i18n";
import { ChartView, EditorsView, type EditorRow, KpiView, type MeasureData, TopView, type Widget } from "./Dashboards";
import { GoalProgress, type Goal } from "./Goals";
import type { Item } from "./Content";

export interface ReportData {
  title: string; intro: string; language: "en" | "nl"; period: string; timezone: string;
  start: string; end: string; generated_at: string; expires_at: string; run_id: number;
  blocks: { block: Widget; data: Record<string, unknown>; error?: string }[];
}

/** The period as local dates: "1 Oct 2026 – 31 Oct 2026" (the end is exclusive). */
export function periodText(start: string, end: string, lang: string, tz?: string) {
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "long", year: "numeric", timeZone: tz };
  const first = new Date(start);
  const last = new Date(new Date(end).getTime() - 1000);
  const a = first.toLocaleDateString(lang, opts);
  const b = last.toLocaleDateString(lang, opts);
  return a === b ? a : `${a} – ${b}`;
}

function Block({ b }: { b: ReportData["blocks"][number] }) {
  const { t } = useTranslation();
  const w = b.block;
  if (b.error) return <Card title={w.title || t(`dashboards.type.${w.type}`)}><p className="muted small">{t("reports.blockFailed")}</p></Card>;
  if (w.type === "kpi") return <KpiView w={w} data={b.data as unknown as MeasureData} />;
  if (w.type === "chart") return <ChartView w={w} d={b.data as unknown as MeasureData} onMode={() => undefined} still />;
  if (w.type === "top") return <TopView w={w} items={(b.data.items as Item[]) ?? []} />;
  if (w.type === "editors") return <EditorsView w={w} editors={(b.data.editors as EditorRow[]) ?? []} />;
  if (w.type === "goals") {
    const goals = (b.data.goals as Goal[]) ?? [];
    return (
      <Card title={w.title || t("goals.title")}>
        {goals.length ? (
          <div className="goal-grid">
            {goals.map((g) => <div key={g.id} className="goal-tile"><div className="goal-name">{g.name}</div><GoalProgress goal={g} /></div>)}
          </div>
        ) : <p className="muted small">{t("dashboards.noData")}</p>}
      </Card>
    );
  }
  return (
    <Card title={w.title || undefined}>
      <div className="report-text">{(w.text ?? "").split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>)}</div>
    </Card>
  );
}

export function ReportBody({ data, pdfUrl }: { data: ReportData; pdfUrl?: string }) {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  const logo = theme?.assets?.logo_light ?? "/favicon.svg";
  return (
    <div className="report">
      <header className="report-head">
        <div className="report-brand"><img src={logo} alt="" /><span>{theme?.app_name ?? "Stats Collector"}</span></div>
        <div className="report-actions no-print">
          {pdfUrl && <a className="btn secondary" href={pdfUrl}><Download /> {t("reports.downloadPdf")}</a>}
          <button type="button" className="btn ghost" onClick={() => window.print()}><Printer /> {t("reports.print")}</button>
        </div>
      </header>
      <h1 className="report-title">{data.title}</h1>
      <p className="report-period">{periodText(data.start, data.end, i18n.language, data.timezone)}</p>
      {data.intro && <div className="report-text intro">{data.intro.split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>)}</div>}
      <div className="dash-grid">
        {data.blocks.map((b, i) => <div key={b.block.id ?? i} className={`dash-cell ${b.block.size} block-${b.block.type}`}><Block b={b} /></div>)}
      </div>
      <footer className="report-foot muted small">
        {t("reports.generatedAt", { date: new Date(data.generated_at).toLocaleString(i18n.language, { dateStyle: "long", timeStyle: "short", timeZone: data.timezone }) })}
      </footer>
    </div>
  );
}

/** The report behind a link (/r/<token>), without logging in. With ?print=1 it is laid out for the PDF. */
export default function PublicReport() {
  const { token = "" } = useParams();
  const { t, i18n } = useTranslation();
  const { theme, user } = useApp();
  const print = new URLSearchParams(window.location.search).has("print");
  const report = useLoad(() => api.get<ReportData>(`/api/public/reports/${encodeURIComponent(token)}`), [token]);
  useEffect(() => {
    if (report.data && !user && i18n.language !== report.data.language) i18n.changeLanguage(report.data.language);
  }, [report.data, user, i18n]);
  useEffect(() => {
    if (theme && print) applyTheme(theme, "light");
    document.documentElement.classList.toggle("printing", print);
  }, [theme, print]);
  useEffect(() => { if (report.data) document.title = report.data.title; }, [report.data]);
  if (report.error) {
    return (
      <div className="report-missing">
        <FileWarning />
        <h1>{report.error === "link_expired" ? t("reports.expiredTitle") : t("reports.missingTitle")}</h1>
        <p className="muted">{report.error === "link_expired" ? t("reports.expiredText") : errorText(report.error)}</p>
      </div>
    );
  }
  if (!report.data) return null;
  return <ReportBody data={report.data} pdfUrl={print ? undefined : `/api/public/reports/${encodeURIComponent(token)}/pdf`} />;
}

/** An archived report inside the app (/reports/runs/<id>). */
export function ArchivedReport() {
  const { id = "" } = useParams();
  const report = useLoad(() => api.get<ReportData>(`/api/reports/runs/${Number(id)}`), [id]);
  if (report.error) return <div className="page"><Card><p>{errorText(report.error)}</p></Card></div>;
  if (!report.data) return null;
  return <div className="page"><ReportBody data={report.data} pdfUrl={`/api/reports/runs/${Number(id)}/pdf`} /></div>;
}
