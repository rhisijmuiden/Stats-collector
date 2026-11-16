import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock, FileEdit, Globe, Megaphone, MessageSquareWarning, MousePointerClick, Search, SearchX, Sparkles, UserCheck } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { Alert, Card, PageHead, useLoad } from "../components/ui";
import Chart, { cssVar } from "../components/Chart";
import { Breakdown, fmt, fmtSeconds, ItemModal, RangePicker, type Range } from "./Content";

interface Row { key: string; value: number }
interface Group { key: string; items: number; avg_views: number; avg_read_seconds: number; read_rate: number }
export interface WebsiteData {
  sources: { id: number; name: string; plugin: string | null }[];
  live: { readers: number | null; items: { id: number; title: string; url: string | null; readers: number }[] };
  searches: { total: number; empty: number; top: Row[]; top_empty: Row[] };
  campaigns: { source: string; medium: string; campaign: string; views: number }[];
  scroll: { views: number; average: number | null; steps: Record<string, number>; reached: Record<string, number> };
  referrers: Row[]; devices: Row[];
  production: {
    published: number; updated: number; per_day: { day: string; count: number }[];
    pipeline: { scheduled: number; drafts: number; pending: number; pending_comments: number } | null;
    scheduled: { title: string; at: string | null; source: string; author?: string | null }[];
    by_editor?: { id: number; name: string; published: number }[];
  };
  articles: {
    articles: number; with_details: number; avg_words: number | null;
    length: Group[]; media: Group[]; updates: Group[]; seo: { articles: number; without_keyword: number; bands: Group[] };
  };
}

/** True when the plugin is at least 0.4, which sends searches, scroll depth, campaigns and the rest. */
const recentPlugin = (v: string | null) => {
  if (!v || v === "demo") return v === "demo";
  const [a, b] = v.split(".").map(Number);
  return a > 0 || b >= 4;
};

function GroupTable({ title, rows, prefix }: { title: string; rows: Group[]; prefix: string }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const best = Math.max(...rows.filter((r) => r.items).map((r) => r.avg_views), 0);
  return (
    <div>
      <h3 className="small-title">{title}</h3>
      <div className="table-wrap"><table>
        <thead><tr><th>{t("website.group")}</th><th className="num">{t("website.articles")}</th><th>{t("website.avgViews")}</th><th className="num">{t("content.avgRead")}</th><th className="num">{t("website.readRate")}</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td>{t(`website.${prefix}.${r.key}`)}</td>
              <td className="num">{fmt(r.items, lang)}</td>
              <td className="meter-cell"><div><span className="meter"><span style={{ width: `${best ? (r.avg_views / best) * 100 : 0}%` }} /></span><b>{r.items ? fmt(r.avg_views, lang) : "–"}</b></div></td>
              <td className="num">{r.items ? fmtSeconds(r.avg_read_seconds) : "–"}</td>
              <td className="num">{r.items ? `${fmt(r.read_rate, lang, 1)}%` : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

export default function WebsitePage() {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  const lang = i18n.language;
  const [range, setRange] = useState<Range>("7d");
  const [source, setSource] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const data = useLoad(() => api.get<WebsiteData>(`/api/website?range=${range}${source ? `&source=${source}` : ""}`), [range, source]);
  // Readers now changes every minute.
  useEffect(() => {
    const timer = window.setInterval(() => data.reload(), 60000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const d = data.data;
  const color = theme?.channels?.website ?? cssVar("--accent", "#0E9F8E");

  const perDay = useMemo(() => {
    if (!d) return null;
    const text = cssVar("--muted", "#5d6b80");
    const grid = cssVar("--border", "#e2e7ef");
    return {
      animationDuration: 300,
      tooltip: { trigger: "axis" },
      grid: { left: 8, right: 8, top: 12, bottom: 8, containLabel: true },
      xAxis: { type: "category", data: d.production.per_day.map((r) => new Date(`${r.day}T12:00:00`).toLocaleDateString(lang, { day: "numeric", month: "short" })), axisLabel: { color: text, hideOverlap: true }, axisLine: { lineStyle: { color: grid } } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
      series: [{ name: t("website.publishedArticles"), type: "bar", data: d.production.per_day.map((r) => r.count), itemStyle: { color, borderRadius: [3, 3, 0, 0] } }],
    };
  }, [d, lang, color, t]);

  if (data.error) return <div className="page"><Alert kind="error">{errorText(data.error)}</Alert></div>;
  const old = d ? d.sources.filter((s) => !recentPlugin(s.plugin)) : [];
  const emptyShare = d && d.searches.total ? (d.searches.empty / d.searches.total) * 100 : 0;
  const stepLabel = (k: string) => (k === "100" ? t("website.scrollEnd") : t("website.scrollAtLeast", { pct: k }));

  return (
    <div className="page">
      <PageHead help="website" title={t("website.title")} subtitle={t("website.subtitle")} actions={<>
        {d && d.sources.length > 1 && (
          <select value={source} onChange={(e) => setSource(e.target.value)} aria-label={t("content.source")}>
            <option value="">{t("website.allSites")}</option>
            {d.sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        )}
        <RangePicker value={range} onChange={setRange} />
      </>} />
      {d && !d.sources.length && <div className="empty"><Globe /><h2>{t("website.noneTitle")}</h2><p>{t("website.noneText")}</p></div>}
      {d && old.length > 0 && <Alert kind="warning">{t("website.oldPlugin", { sites: old.map((s) => s.name).join(", ") })}</Alert>}
      {d && d.sources.length > 0 && (
        <div className="stack">
          <div className="kpis">
            <div className="kpi"><span className="kpi-bar" style={{ background: color }} /><div className="kpi-label"><span className={`live-dot${d.live.readers ? " on" : ""}`} /> {t("website.readersNow")}</div><div className="kpi-value">{d.live.readers == null ? "–" : fmt(d.live.readers, lang)}</div><div className="kpi-sub">{t("website.readersNowSub")}</div></div>
            <div className="kpi"><div className="kpi-label"><Search size={14} /> {t("website.searches")}</div><div className="kpi-value">{fmt(d.searches.total, lang)}</div><div className="kpi-sub">{t("website.searchesEmptySub", { pct: fmt(emptyShare, lang, 0) })}</div></div>
            <div className="kpi"><div className="kpi-label"><MousePointerClick size={14} /> {t("website.avgScroll")}</div><div className="kpi-value">{d.scroll.average == null ? "–" : `${fmt(d.scroll.average, lang)}%`}</div><div className="kpi-sub">{t("website.scrollEndSub", { pct: fmt(d.scroll.reached["100"] ?? 0, lang) })}</div></div>
            <div className="kpi"><div className="kpi-label"><FileEdit size={14} /> {t("website.publishedArticles")}</div><div className="kpi-value">{fmt(d.production.published, lang)}</div><div className="kpi-sub">{t("website.updatedSub", { count: d.production.updated })}</div></div>
            <div className="kpi"><div className="kpi-label"><Sparkles size={14} /> {t("website.avgWords")}</div><div className="kpi-value">{d.articles.avg_words == null ? "–" : fmt(d.articles.avg_words, lang)}</div><div className="kpi-sub">{t("website.avgWordsSub")}</div></div>
          </div>

          <div className="grid two">
            <Card title={t("website.liveTitle")} subtitle={t("website.liveText")}>
              {d.live.items.length ? (
                <ul className="bars-list">
                  {d.live.items.map((r) => (
                    <li key={r.id}>
                      <span className="bar" style={{ width: `${(r.readers / d.live.items[0].readers) * 100}%` }} />
                      <button type="button" className="link-btn" onClick={() => setOpen(r.id)}>{r.title}</button><b>{fmt(r.readers, lang)}</b>
                    </li>
                  ))}
                </ul>
              ) : <p className="muted small">{d.live.readers == null ? t("website.liveUnknown") : t("website.liveNone")}</p>}
            </Card>
            <Card title={t("website.productionTitle")} subtitle={t("website.productionText")}>
              {d.production.pipeline ? (
                <div className="kpis compact">
                  <div className="kpi"><div className="kpi-label"><CalendarClock size={14} /> {t("website.scheduled")}</div><div className="kpi-value">{fmt(d.production.pipeline.scheduled, lang)}</div></div>
                  <div className="kpi"><div className="kpi-label"><FileEdit size={14} /> {t("website.drafts")}</div><div className="kpi-value">{fmt(d.production.pipeline.drafts, lang)}</div></div>
                  <div className="kpi"><div className="kpi-label"><UserCheck size={14} /> {t("website.pending")}</div><div className="kpi-value">{fmt(d.production.pipeline.pending, lang)}</div></div>
                  <div className="kpi"><div className="kpi-label"><MessageSquareWarning size={14} /> {t("website.pendingComments")}</div><div className="kpi-value">{fmt(d.production.pipeline.pending_comments, lang)}</div></div>
                </div>
              ) : <p className="muted small">{t("website.pipelineUnknown")}</p>}
              {perDay && range !== "24h" && <Chart option={perDay} className="chart small" />}
            </Card>
          </div>

          <div className="grid two">
            <Card title={t("website.scheduledTitle")}>
              {d.production.scheduled.length ? (
                <ul className="items-list">
                  {d.production.scheduled.map((r, n) => (
                    <li key={n}><span>{r.title}{r.author ? <span className="muted"> · {r.author}</span> : null}</span><span className="muted nowrap">{r.at ? new Date(r.at).toLocaleString(lang, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–"}</span></li>
                  ))}
                </ul>
              ) : <p className="muted small">{t("website.scheduledNone")}</p>}
            </Card>
            {d.production.by_editor && (
              <Card title={t("website.byEditorTitle")}>
                {d.production.by_editor.length ? (
                  <ul className="bars-list">
                    {d.production.by_editor.map((r) => (
                      <li key={r.id}><span className="bar" style={{ width: `${(r.published / d.production.by_editor![0].published) * 100}%` }} /><span>{r.name}</span><b>{fmt(r.published, lang)}</b></li>
                    ))}
                  </ul>
                ) : <p className="muted small">{t("content.noBreakdown")}</p>}
              </Card>
            )}
          </div>

          <Card title={t("website.searchTitle")} subtitle={t("website.searchText")}>
            <div className="grid two">
              <Breakdown title={t("website.topSearches")} icon={<Search size={14} />} rows={d.searches.top} raw />
              <Breakdown title={t("website.emptySearches")} icon={<SearchX size={14} />} rows={d.searches.top_empty} raw warn />
            </div>
          </Card>

          <div className="grid two">
            <Card title={t("website.campaignsTitle")} subtitle={t("website.campaignsText")}>
              {d.campaigns.length ? (
                <div className="table-wrap"><table>
                  <thead><tr><th>{t("website.campaign")}</th><th>{t("website.utmSource")}</th><th>{t("website.utmMedium")}</th><th className="num">{t("content.views")}</th></tr></thead>
                  <tbody>
                    {d.campaigns.map((c, n) => (
                      <tr key={n}><td><Megaphone size={13} className="muted" /> {c.campaign || "–"}</td><td>{c.source || "–"}</td><td>{c.medium || "–"}</td><td className="num">{fmt(c.views, lang)}</td></tr>
                    ))}
                  </tbody>
                </table></div>
              ) : <p className="muted small">{t("website.campaignsNone")}</p>}
            </Card>
            <Card title={t("website.scrollTitle")} subtitle={t("website.scrollText")}>
              {d.scroll.views ? (
                <ul className="bars-list">
                  {(["25", "50", "75", "100"] as const).map((k) => (
                    <li key={k}><span className="bar" style={{ width: `${d.scroll.reached[k] ?? 0}%` }} /><span>{stepLabel(k)}</span><b>{fmt(d.scroll.reached[k] ?? 0, lang)}%</b></li>
                  ))}
                </ul>
              ) : <p className="muted small">{t("content.noBreakdown")}</p>}
            </Card>
          </div>

          <Card title={t("website.worksTitle")} subtitle={t("website.worksText", { count: d.articles.with_details, total: d.articles.articles })}>
            <div className="stack">
              <GroupTable title={t("website.byLength")} rows={d.articles.length} prefix="length" />
              <GroupTable title={t("website.byMedia")} rows={d.articles.media} prefix="media" />
              <GroupTable title={t("website.byUpdates")} rows={d.articles.updates} prefix="updates" />
              <div>
                <GroupTable title={t("website.bySeo")} rows={d.articles.seo.bands} prefix="seo" />
                <p className="muted small">{d.articles.seo.articles ? t("website.seoNoKeyword", { count: d.articles.seo.without_keyword }) : t("website.seoNone")}</p>
              </div>
            </div>
          </Card>

          <Card title={t("website.trafficTitle")}>
            <div className="grid two">
              <Breakdown title={t("content.referrers")} rows={d.referrers} />
              <Breakdown title={t("content.devices")} rows={d.devices} />
            </div>
          </Card>
        </div>
      )}
      {open != null && <ItemModal id={open} range={range} onClose={() => setOpen(null)} />}
    </div>
  );
}
