import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Clock } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { Alert, Card, PageHead, useLoad } from "../components/ui";
import Chart, { cssVar } from "../components/Chart";
import { channel, fmt, kindIcon } from "./Content";

interface Cell { weekday: number; hour: number; items: number; avg: number; index: number | null }
interface BestTimes {
  source: { id: number; name: string; kind: string }; days: number; measure: "views" | "interactions"; items: number; average: number;
  min_items: number; few: boolean; grid: Cell[]; by_day: Omit<Cell, "hour">[]; by_hour: Omit<Cell, "weekday">[]; best: Cell[];
}
const SPANS = [30, 90, 180, 365] as const;
const WITH_ITEMS = ["wordpress", "youtube", "facebook", "instagram", "threads", "x", "bluesky", "mastodon"];

/** Monday-first weekday names in the user's language. */
function weekdays(lang: string, style: "short" | "long" = "short") {
  const monday = new Date(2024, 0, 1); // a Monday
  return Array.from({ length: 7 }, (_, i) => new Date(monday.getTime() + i * 86400000).toLocaleDateString(lang, { weekday: style }));
}
/** The channel colour mixed with white, for the low end of the heat map. */
function tint(hex: string, amount: number) {
  const n = parseInt(hex.replace("#", "").slice(0, 6), 16);
  const mix = (c: number) => Math.round(c + (255 - c) * (1 - amount));
  return `#${[(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => mix(c).toString(16).padStart(2, "0")).join("")}`;
}
const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;

export default function BestTimesPage() {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  const lang = i18n.language;
  const filters = useLoad(() => api.get<{ sources: { id: number; name: string; kind: string }[] }>("/api/content/filters"));
  // The website first: it has the most items.
  const sources = (filters.data?.sources ?? []).filter((s) => WITH_ITEMS.includes(s.kind))
    .sort((a, b) => WITH_ITEMS.indexOf(a.kind) - WITH_ITEMS.indexOf(b.kind));
  const [source, setSource] = useState<number | null>(null);
  const [days, setDays] = useState<number>(90);
  useEffect(() => { if (source == null && sources.length) setSource(sources[0].id); }, [sources, source]);
  const data = useLoad(() => (source == null ? Promise.resolve(null) : api.get<BestTimes>(`/api/best-times?source_id=${source}&days=${days}`)), [source, days]);
  const d = data.data;
  const color = theme?.channels?.[channel(d?.source.kind ?? "")] ?? cssVar("--accent", "#0E9F8E");
  const days7 = useMemo(() => weekdays(lang), [lang]);
  const daysLong = useMemo(() => weekdays(lang, "long"), [lang]);
  const measure = d ? t(`bestTimes.measure.${d.measure}`) : "";

  const heat = useMemo(() => {
    if (!d) return null;
    const text = cssVar("--muted", "#5d6b80");
    // The scale stops at the 90th percentile, so one outlier does not make every other hour pale.
    const sorted = d.grid.map((c) => c.avg).sort((a, b) => a - b);
    const max = Math.max(1, sorted[Math.floor((sorted.length - 1) * 0.9)] ?? 1);
    return {
      animationDuration: 300,
      tooltip: {
        formatter: (p: { data: [number, number, number, number] }) => {
          const [h, wd, avg, n] = p.data;
          return `<b>${daysLong[wd]} ${hh(h)}</b><br/>${t("bestTimes.tipAvg", { value: fmt(avg, lang), measure })}<br/>${t("bestTimes.tipItems", { count: n })}`;
        },
      },
      grid: { left: 8, right: 8, top: 8, bottom: 56, containLabel: true },
      xAxis: { type: "category", data: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0")), splitArea: { show: false }, axisLabel: { color: text }, axisLine: { show: false }, axisTick: { show: false } },
      yAxis: { type: "category", data: days7, inverse: true, axisLabel: { color: text }, axisLine: { show: false }, axisTick: { show: false } },
      visualMap: {
        dimension: 2, min: 0, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemHeight: 160, itemWidth: 10,
        text: [t("bestTimes.more"), t("bestTimes.less")], textStyle: { color: text },
        inRange: { color: [tint(color, 0.18), color] },
      },
      series: [{
        type: "heatmap",
        data: d.grid.map((c) => [c.hour, c.weekday, c.avg, c.items]),
        itemStyle: { borderColor: cssVar("--surface", "#fff"), borderWidth: 2, borderRadius: 4 },
        emphasis: { itemStyle: { borderColor: cssVar("--text", "#152033"), borderWidth: 1 } },
      }],
    };
  }, [d, days7, daysLong, color, lang, measure, t]);

  const bars = (labels: string[], values: (number | null)[]) => {
    const text = cssVar("--muted", "#5d6b80");
    const grid = cssVar("--border", "#e2e7ef");
    return {
      animationDuration: 300,
      tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v == null ? "–" : `${v} (${t("bestTimes.index")})`) },
      grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: true },
      xAxis: { type: "category", data: labels, axisLabel: { color: text }, axisLine: { lineStyle: { color: grid } } },
      yAxis: { type: "value", axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
      series: [{
        type: "bar", data: values.map((v) => (v == null ? null : { value: v, itemStyle: { color: v >= 100 ? color : cssVar("--border", "#c8d0dc"), borderRadius: [4, 4, 0, 0] } })),
        markLine: { silent: true, symbol: "none", data: [{ yAxis: 100 }], lineStyle: { color: text, type: "dashed" }, label: { show: false } },
      }],
    };
  };

  return (
    <div className="page">
      <PageHead help="best-times" title={t("bestTimes.title")} subtitle={t("bestTimes.subtitle")}
        actions={<>
          <select className="auto-width" value={source ?? ""} onChange={(e) => setSource(Number(e.target.value))} aria-label={t("bestTimes.channel")}>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <div className="seg">{SPANS.map((n) => <button key={n} type="button" aria-pressed={days === n} onClick={() => setDays(n)}>{t("bestTimes.days", { count: n })}</button>)}</div>
        </>} />
      {data.error && <Alert kind="error">{errorText(data.error)}</Alert>}
      {filters.data && !sources.length && <Card><div className="empty"><Clock /><h2>{t("bestTimes.noSourcesTitle")}</h2><p>{t("bestTimes.noSourcesText")}</p></div></Card>}
      {d && (
        <>
          <div className="kpis">
            <div className="kpi"><span className="kpi-bar" style={{ background: color }} /><div className="kpi-label">{kindIcon(d.source.kind)} {d.source.name}</div><div className="kpi-value">{fmt(d.items, lang)}</div><div className="kpi-sub">{t("bestTimes.itemsSub", { days: d.days })}</div></div>
            <div className="kpi"><div className="kpi-label">{t("bestTimes.average")}</div><div className="kpi-value">{fmt(d.average, lang)}</div><div className="kpi-sub">{t("bestTimes.averageSub", { measure })}</div></div>
            {d.best[0] && <div className="kpi"><div className="kpi-label">{t("bestTimes.bestSlot")}</div><div className="kpi-value">{days7[d.best[0].weekday]} {hh(d.best[0].hour)}</div><div className="kpi-sub">{t("bestTimes.bestSub", { index: d.best[0].index })}</div></div>}
          </div>
          {d.items === 0 ? (
            <Card><div className="empty"><Clock /><h2>{t("bestTimes.noneTitle")}</h2><p>{t("bestTimes.noneText")}</p></div></Card>
          ) : (
            <div className="best-layout">
              <Card title={t("bestTimes.heatTitle")} subtitle={t("bestTimes.heatHint", { measure })}>
                {heat && <Chart option={heat} className="chart heat" />}
              </Card>
              <Card title={t("bestTimes.topTitle")} subtitle={t("bestTimes.topHint", { count: d.min_items })}>
                {d.few && d.best.length > 0 && <p className="muted small">{t("bestTimes.tooFew", { count: d.min_items })}</p>}
                {d.best.length ? (
                  <ol className="best-list">
                    {d.best.map((c, i) => (
                      <li key={`${c.weekday}-${c.hour}`}>
                        <span className="rank">{i + 1}</span>
                        <div><b>{daysLong[c.weekday]} {hh(c.hour)}–{hh((c.hour + 1) % 24)}</b><div className="muted small">{t("bestTimes.tipItems", { count: c.items })}</div></div>
                        <div className="num"><b>{fmt(c.avg, lang)}</b><div className="muted small">{c.index != null ? t("bestTimes.vsUsual", { index: c.index }) : ""}</div></div>
                      </li>
                    ))}
                  </ol>
                ) : null}
              </Card>
              <Card title={t("bestTimes.byDay")}><Chart className="chart small" option={bars(days7, d.by_day.map((x) => x.index))} /></Card>
              <Card title={t("bestTimes.byHour")}><Chart className="chart small" option={bars(d.by_hour.map((x) => String(x.hour).padStart(2, "0")), d.by_hour.map((x) => x.index))} /></Card>
            </div>
          )}
          <p className="muted small">{t("bestTimes.how")}</p>
        </>
      )}
    </div>
  );
}
