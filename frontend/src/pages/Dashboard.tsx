import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Activity, BookOpen, Clock, Plus, Radio, TrendingUp, Tv } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/app";
import { Alert, Card, PageHead, useLoad } from "../components/ui";
import Chart, { cssVar, shade } from "../components/Chart";
import ChannelsCard, { type Channels } from "../components/ChannelsCard";
import { GoalsCard } from "./Goals";
import { errorText } from "../i18n";

type Range = "24h" | "7d" | "30d" | "90d";
type Metric = "live_avg" | "live_peak" | "live_minutes";
type Mode = "stacked" | "overlay" | "separate";

interface LiveItem { id: number; title: string; kind: string; value: number; online: boolean; now_playing?: string | null }
interface LiveSource {
  id: number; name: string; kind: "icecast" | "owncast"; enabled: boolean; online: boolean; audience: number;
  items: LiveItem[]; peak_today: number; minutes_today: number; stale: boolean; last_error: string | null; updated_at: string | null;
}
interface Live { at: string; total: number; sources: LiveSource[] }
interface Series { granularity: "5min" | "hour" | "day"; buckets: string[]; series: { id: number; name: string; kind: string; values: (number | null)[] }[] }
interface Summary {
  total_minutes: number; peak: number;
  sources: { id: number; name: string; kind: string; minutes: number; peak: number; avg: number }[];
  top_items: { id: number; title: string; kind: string; source: string | null; source_kind: string | null; minutes: number; peak: number; published_at: string | null; ended_at: string | null }[];
}

const fmt = (n: number, lang: string, digits = 0) => new Intl.NumberFormat(lang, { maximumFractionDigits: digits }).format(n);

function useInterval(fn: () => void, ms: number) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    const id = window.setInterval(() => { if (!document.hidden) saved.current(); }, ms);
    return () => window.clearInterval(id);
  }, [ms]);
}

export default function Dashboard() {
  const { t, i18n } = useTranslation();
  const { user, theme } = useApp();
  const lang = i18n.language;
  const [range, setRange] = useState<Range>("24h");
  const [metric, setMetric] = useState<Metric>("live_avg");
  const [mode, setMode] = useState<Mode>("stacked");
  const live = useLoad(() => api.get<Live>("/api/dashboard/live"));
  const series = useLoad(() => api.get<Series>(`/api/dashboard/series?range=${range}&metric=${metric}`), [range, metric]);
  const summary = useLoad(() => api.get<Summary>(`/api/dashboard/summary?range=${range}`), [range]);
  const channels = useLoad(() => api.get<Channels>(`/api/dashboard/channels?range=${range}`), [range]);
  useInterval(live.reload, 15000);
  useInterval(series.reload, 60000);
  useInterval(summary.reload, 120000);

  const colors = useMemo(() => {
    const out: Record<number, string> = {};
    const seen: Record<string, number> = {};
    for (const s of live.data?.sources ?? series.data?.series ?? []) {
      const base = theme?.channels?.[s.kind] ?? "#888888";
      out[s.id] = shade(base, (seen[s.kind] = (seen[s.kind] ?? -1) + 1));
    }
    return out;
  }, [live.data, series.data, theme]);

  const sources = live.data?.sources ?? [];
  const online = sources.filter((s) => s.online).length;
  const peakToday = sources.reduce((a, s) => a + s.peak_today, 0);

  const labelFor = (iso: string) => {
    const d = new Date(iso);
    if (series.data?.granularity === "day") return d.toLocaleDateString(lang, { day: "numeric", month: "short" });
    if (series.data?.granularity === "hour") return d.toLocaleString(lang, { weekday: "short", hour: "2-digit", minute: "2-digit" });
    return d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
  };

  const baseOption = (subset?: Series["series"]) => {
    const data = series.data;
    const text = cssVar("--muted", "#5d6b80");
    const grid = cssVar("--border", "#e2e7ef");
    const list = subset ?? data?.series ?? [];
    const bar = data?.granularity === "day" && metric === "live_minutes";
    return {
      animationDuration: 300,
      color: list.map((s) => colors[s.id]),
      tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v == null ? "–" : fmt(v, lang, 1)) },
      legend: subset ? { show: false } : { bottom: 0, textStyle: { color: text }, icon: "roundRect" },
      grid: { left: 8, right: 16, top: 16, bottom: subset ? 8 : 36, containLabel: true },
      xAxis: {
        type: "category", boundaryGap: bar, data: (data?.buckets ?? []).map(labelFor),
        axisLabel: { color: text, hideOverlap: true }, axisLine: { lineStyle: { color: grid } },
      },
      yAxis: { type: "value", minInterval: 1, axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
      series: list.map((s) => ({
        name: s.name, type: bar ? "bar" : "line", data: s.values, showSymbol: false, smooth: 0.25, connectNulls: false,
        stack: mode === "stacked" ? "total" : undefined,
        areaStyle: mode === "stacked" || subset ? { opacity: 0.22 } : undefined,
        lineStyle: { width: 2 }, emphasis: { focus: "series" },
      })),
    };
  };

  const hasStreams = sources.length > 0;
  const hasChannels = (channels.data?.sources.length ?? 0) > 0;
  const noSources = live.data && channels.data && !hasStreams && !hasChannels;
  return (
    <div className="page">
      <PageHead help="dashboard" title={t("dashboard.title")} subtitle={t("dashboard.welcome", { name: user?.display_name })}
        actions={
          <div className="seg" role="group" aria-label={t("dashboard.period")}>
            {(["24h", "7d", "30d", "90d"] as const).map((r) => (
              <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>{t(`dashboard.range.${r}`)}</button>
            ))}
          </div>
        } />

      {noSources ? (
        <Card>
          <div className="empty">
            <Activity />
            <h2>{t("dashboard.noSourcesTitle")}</h2>
            <p>{t("dashboard.noSourcesText")}</p>
            <div className="row" style={{ justifyContent: "center", marginTop: 12 }}>
              {user?.role === "admin" && <Link className="btn" to="/admin/sources"><Plus /> {t("dashboard.addSource")}</Link>}
              <Link className="btn secondary" to="/help/owncast-icecast"><BookOpen /> {t("dashboard.readHow")}</Link>
            </div>
          </div>
        </Card>
      ) : (
        <>
          {hasChannels && <ChannelsCard data={channels.data!} rangeLabel={t(`dashboard.rangeLong.${range}`)} />}
          <GoalsCard />
          {hasStreams && <>
          <div className="kpis">
            <div className="kpi">
              <div className="kpi-label"><span className={`live-dot${online ? " on" : ""}`} /> {t("dashboard.liveNow")}</div>
              <div className="kpi-value">{fmt(live.data?.total ?? 0, lang)}</div>
              <div className="kpi-sub">{t("dashboard.sourcesOnline", { online, total: sources.length })}</div>
            </div>
            <div className="kpi">
              <div className="kpi-label"><TrendingUp size={15} /> {t("dashboard.peakToday")}</div>
              <div className="kpi-value">{fmt(peakToday, lang)}</div>
              <div className="kpi-sub">{t("dashboard.peakTodayHint")}</div>
            </div>
            <div className="kpi">
              <div className="kpi-label"><Clock size={15} /> {t("dashboard.minutes")}</div>
              <div className="kpi-value">{fmt(summary.data?.total_minutes ?? 0, lang)}</div>
              <div className="kpi-sub">{t(`dashboard.rangeLong.${range}`)}</div>
            </div>
            <div className="kpi">
              <div className="kpi-label"><TrendingUp size={15} /> {t("dashboard.peakRange")}</div>
              <div className="kpi-value">{fmt(summary.data?.peak ?? 0, lang)}</div>
              <div className="kpi-sub">{t(`dashboard.rangeLong.${range}`)}</div>
            </div>
          </div>

          <div className="kpis">
            {sources.map((s) => (
              <div className="kpi" key={s.id}>
                <span className="kpi-bar" style={{ background: colors[s.id] }} />
                <div className="kpi-label">
                  {s.kind === "owncast" ? <Tv size={15} /> : <Radio size={15} />} {s.name}
                  <span className={`badge${s.online ? " good" : ""}`} style={{ marginLeft: "auto" }}>{s.online ? t("dashboard.online") : t("dashboard.offline")}</span>
                </div>
                <div className="kpi-value">{fmt(s.audience, lang)}</div>
                <div className="kpi-sub">{t(s.kind === "owncast" ? "dashboard.viewersNow" : "dashboard.listenersNow")} · {t("dashboard.peak")} {fmt(s.peak_today, lang)}</div>
                {s.last_error && <div className="kpi-sub" style={{ color: "var(--critical)" }}>{errorText(s.last_error)}</div>}
                {s.items.length > 1 && (
                  <ul className="items-list">
                    {s.items.map((it) => <li key={it.id}><span title={it.now_playing ?? undefined}>{it.title}</span><b>{fmt(it.value, lang)}</b></li>)}
                  </ul>
                )}
                {s.items.length === 1 && s.items[0].kind === "broadcast" && <div className="kpi-sub">{s.items[0].title}</div>}
              </div>
            ))}
          </div>

          <Card title={t("dashboard.audience")} subtitle={t(`dashboard.metricHint.${metric}`)}>
            <div className="toolbar">
              <div className="seg">
                {(["live_avg", "live_peak", "live_minutes"] as const).map((m) => (
                  <button key={m} type="button" aria-pressed={metric === m} onClick={() => setMetric(m)}>{t(`dashboard.metric.${m}`)}</button>
                ))}
              </div>
              <div className="seg">
                {(["stacked", "overlay", "separate"] as const).map((m) => (
                  <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}>{t(`dashboard.mode.${m}`)}</button>
                ))}
              </div>
            </div>
            {series.error && <Alert kind="error">{errorText(String(series.error))}</Alert>}
            {mode === "separate" ? (
              <div className="small-multiples">
                {(series.data?.series ?? []).map((s) => (
                  <div key={s.id}>
                    <div className="source-kind small"><i style={{ background: colors[s.id] }} /> {s.name}</div>
                    <Chart className="chart small" option={baseOption([s])} />
                  </div>
                ))}
              </div>
            ) : (
              <Chart option={baseOption()} />
            )}
          </Card>

          <div className="grid two">
            <Card title={t("dashboard.perSource")}>
              <div className="table-wrap"><table>
                <thead><tr><th>{t("dashboard.source")}</th><th className="num">{t("dashboard.metric.live_minutes")}</th><th className="num">{t("dashboard.metric.live_avg")}</th><th className="num">{t("dashboard.metric.live_peak")}</th></tr></thead>
                <tbody>
                  {(summary.data?.sources ?? []).map((s) => (
                    <tr key={s.id}>
                      <td><span className="source-kind"><i style={{ background: colors[s.id] }} />{s.name}</span></td>
                      <td className="num">{fmt(s.minutes, lang)}</td><td className="num">{fmt(s.avg, lang, 1)}</td><td className="num">{fmt(s.peak, lang)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </Card>
            <Card title={t("dashboard.topItems")} subtitle={t("dashboard.topItemsHint")}>
              {summary.data?.top_items.length ? (
                <div className="table-wrap"><table>
                  <thead><tr><th>{t("dashboard.item")}</th><th className="num">{t("dashboard.metric.live_minutes")}</th><th className="num">{t("dashboard.metric.live_peak")}</th></tr></thead>
                  <tbody>
                    {summary.data.top_items.map((it) => (
                      <tr key={it.id}>
                        <td><b>{it.title}</b><div className="muted small">{it.source}{it.published_at && it.kind === "broadcast" ? ` · ${new Date(it.published_at).toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" })}` : ""}</div></td>
                        <td className="num">{fmt(it.minutes, lang)}</td><td className="num">{fmt(it.peak, lang)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              ) : <p className="muted">{t("dashboard.noData")}</p>}
            </Card>
          </div>
          </>}
        </>
      )}
    </div>
  );
}
