import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Globe, Youtube } from "lucide-react";
import { useApp } from "../lib/app";
import { Card } from "./ui";
import Chart, { cssVar, shade } from "./Chart";

export interface Channels {
  granularity: "hour" | "day"; buckets: string[]; total_views: number;
  sources: { id: number; name: string; kind: "wordpress" | "youtube"; views: number; visitors: number; watch_minutes: number;
    subscribers: number | null; subscribers_gained: number; values: (number | null)[]; last_ok_at: string | null }[];
}

const fmt = (n: number, lang: string) => new Intl.NumberFormat(lang, { maximumFractionDigits: 0 }).format(n);

/** Website and YouTube views on the dashboard: a tile per source and the views stacked per hour or day. */
export default function ChannelsCard({ data, rangeLabel }: { data: Channels; rangeLabel: string }) {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  const lang = i18n.language;
  const colors = useMemo(() => {
    const seen: Record<string, number> = {};
    return Object.fromEntries(data.sources.map((s) => {
      const key = s.kind === "wordpress" ? "website" : s.kind;
      return [s.id, shade(theme?.channels?.[key] ?? "#3E7BFA", (seen[key] = (seen[key] ?? -1) + 1))];
    }));
  }, [data, theme]);
  const option = useMemo(() => {
    const text = cssVar("--muted", "#5d6b80");
    const grid = cssVar("--border", "#e2e7ef");
    const label = (iso: string) => {
      const d = new Date(iso);
      return data.granularity === "day" ? d.toLocaleDateString(lang, { day: "numeric", month: "short" }) : d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
    };
    return {
      animationDuration: 300,
      color: data.sources.map((s) => colors[s.id]),
      tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v == null ? "–" : fmt(v, lang)) },
      legend: { bottom: 0, textStyle: { color: text }, icon: "roundRect" },
      grid: { left: 8, right: 16, top: 16, bottom: 36, containLabel: true },
      xAxis: { type: "category", data: data.buckets.map(label), axisLabel: { color: text, hideOverlap: true }, axisLine: { lineStyle: { color: grid } } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
      series: data.sources.map((s) => ({ name: s.name, type: "bar", stack: "views", data: s.values, barMaxWidth: 28, emphasis: { focus: "series" } })),
    };
  }, [data, colors, lang]);

  return (
    <Card title={t("dashboard.channelsTitle")} subtitle={t("dashboard.channelsHint")} actions={<Link className="btn ghost" to="/content">{t("dashboard.toContent")}</Link>}>
      <div className="kpis">
        <div className="kpi">
          <div className="kpi-label">{t("dashboard.totalViews")}</div>
          <div className="kpi-value">{fmt(data.total_views, lang)}</div>
          <div className="kpi-sub">{rangeLabel}</div>
        </div>
        {data.sources.map((s) => (
          <div className="kpi" key={s.id}>
            <span className="kpi-bar" style={{ background: colors[s.id] }} />
            <div className="kpi-label">{s.kind === "youtube" ? <Youtube size={15} /> : <Globe size={15} />} {s.name}</div>
            <div className="kpi-value">{fmt(s.views, lang)}</div>
            <div className="kpi-sub">
              {s.kind === "youtube"
                ? t("dashboard.ytSub", { minutes: fmt(s.watch_minutes, lang), subscribers: fmt(s.subscribers ?? 0, lang), gained: fmt(s.subscribers_gained, lang) })
                : t("dashboard.webSub", { visitors: fmt(s.visitors, lang) })}
            </div>
          </div>
        ))}
      </div>
      <Chart option={option} />
    </Card>
  );
}
