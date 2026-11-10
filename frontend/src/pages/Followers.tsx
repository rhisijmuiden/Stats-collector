import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AtSign, Cloud, Facebook, Instagram, MessageSquare, Users, Youtube } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { Alert, Card, PageHead, useLoad } from "../components/ui";
import Chart, { cssVar, shade } from "../components/Chart";

type Kind = "youtube" | "facebook" | "instagram" | "threads" | "bluesky" | "mastodon";
interface Followers {
  range: Range; days: string[]; total: number; total_change: number; total_values: (number | null)[];
  sources: { id: number; name: string; kind: Kind; current: number | null; change: number; gained: number; values: (number | null)[] }[];
}
type Range = "30d" | "90d" | "365d";

const ICONS: Record<Kind, JSX.Element> = { youtube: <Youtube size={15} />, facebook: <Facebook size={15} />, instagram: <Instagram size={15} />, threads: <AtSign size={15} />, bluesky: <Cloud size={15} />, mastodon: <MessageSquare size={15} /> };
export const fmtInt = (n: number, lang: string) => new Intl.NumberFormat(lang, { maximumFractionDigits: 0 }).format(n);
const signed = (n: number, lang: string) => (n > 0 ? "+" : n < 0 ? "−" : "±") + fmtInt(Math.abs(n), lang);

export default function FollowersPage() {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  const lang = i18n.language;
  const [range, setRange] = useState<Range>("90d");
  const [stacked, setStacked] = useState(true);
  const data = useLoad(() => api.get<Followers>(`/api/followers?range=${range}`), [range]);
  const d = data.data;

  const colors = useMemo(() => {
    const seen: Record<string, number> = {};
    return Object.fromEntries((d?.sources ?? []).map((s) => [s.id, shade(theme?.channels?.[s.kind] ?? "#3E7BFA", (seen[s.kind] = (seen[s.kind] ?? -1) + 1))]));
  }, [d, theme]);

  const option = useMemo(() => {
    if (!d) return {};
    const text = cssVar("--muted", "#5d6b80");
    const grid = cssVar("--border", "#e2e7ef");
    return {
      animationDuration: 300,
      color: d.sources.map((s) => colors[s.id]),
      tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v == null ? "–" : fmtInt(v, lang)) },
      legend: { bottom: 0, textStyle: { color: text }, icon: "roundRect" },
      grid: { left: 8, right: 16, top: 16, bottom: 36, containLabel: true },
      xAxis: { type: "category", data: d.days.map((x) => new Date(x).toLocaleDateString(lang, { day: "numeric", month: "short" })), axisLabel: { color: text, hideOverlap: true }, axisLine: { lineStyle: { color: grid } } },
      yAxis: { type: "value", scale: !stacked, axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
      series: d.sources.map((s) => ({
        name: s.name, type: "line", data: s.values, showSymbol: false, smooth: true, connectNulls: true,
        ...(stacked ? { stack: "followers", areaStyle: { opacity: 0.35 } } : {}),
      })),
    };
  }, [d, colors, lang, stacked]);

  return (
    <div className="page">
      <PageHead help="followers-and-goals" title={t("followers.title")} subtitle={t("followers.subtitle")}
        actions={<div className="seg">{(["30d", "90d", "365d"] as const).map((r) => <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>{t(`followers.range.${r}`)}</button>)}</div>} />
      {data.error && <Alert kind="error">{errorText(data.error)}</Alert>}
      {d && (d.sources.length === 0 ? (
        <Card><div className="empty"><Users /><h2>{t("followers.noneTitle")}</h2><p>{t("followers.noneText")}</p></div></Card>
      ) : (
        <Card title={t("followers.chartTitle")} subtitle={t("followers.chartHint")}
          actions={<div className="seg">{([true, false] as const).map((v) => <button key={String(v)} type="button" aria-pressed={stacked === v} onClick={() => setStacked(v)}>{t(v ? "followers.stacked" : "followers.separate")}</button>)}</div>}>
          <div className="kpis">
            <div className="kpi">
              <div className="kpi-label">{t("followers.total")}</div>
              <div className="kpi-value">{fmtInt(d.total, lang)}</div>
              <div className="kpi-sub">{t("followers.change", { change: signed(d.total_change, lang), period: t(`followers.range.${range}`) })}</div>
            </div>
            {d.sources.map((s) => (
              <div className="kpi" key={s.id}>
                <span className="kpi-bar" style={{ background: colors[s.id] }} />
                <div className="kpi-label">{ICONS[s.kind]} {s.name}</div>
                <div className="kpi-value">{s.current == null ? "–" : fmtInt(s.current, lang)}</div>
                <div className="kpi-sub">{t("followers.sourceSub", { change: signed(s.change, lang), gained: fmtInt(s.gained, lang) })}</div>
              </div>
            ))}
          </div>
          <Chart option={option} />
        </Card>
      ))}
    </div>
  );
}
