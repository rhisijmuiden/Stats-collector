import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink, FileText, Globe, Radio, Search, Tv } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/app";
import { Alert, Card, Modal, PageHead, useLoad } from "../components/ui";
import Chart, { cssVar } from "../components/Chart";
import { errorText } from "../i18n";
import { formatDate } from "../lib/format";

export type Range = "24h" | "7d" | "30d" | "90d" | "365d";
export const RANGES: Range[] = ["24h", "7d", "30d", "90d", "365d"];
export type MetricKey = "views" | "visitors" | "read_seconds" | "reads" | "shares" | "comments" | "minutes" | "peak";

export interface Item {
  id: number; title: string; kind: string; url: string | null; category: string | null; tags: string[];
  source: { id: number; name: string; kind: string } | null; published_at: string | null; ended_at: string | null;
  metrics: Record<MetricKey, number>; avg_read_seconds: number; comments_total: number;
  authors?: { id: number; name: string; role: string }[];
}
interface Top { items: Item[]; start: string; end: string }
interface Filters { sources: { id: number; name: string; kind: string }[]; categories: string[]; people: { id: number; name: string }[]; can_see_editors: boolean }
export interface Detail {
  granularity: "hour" | "day"; buckets: string[]; item: Item;
  series: Partial<Record<MetricKey, number[]>>; dimensions: { referrer?: { key: string; value: number }[]; device?: { key: string; value: number }[] };
}

export const fmt = (n: number, lang: string, digits = 0) => new Intl.NumberFormat(lang, { maximumFractionDigits: digits }).format(n);
export const fmtSeconds = (s: number) => {
  if (!s) return "–";
  const m = Math.floor(s / 60);
  return m ? `${m}:${String(Math.round(s % 60)).padStart(2, "0")}` : `${Math.round(s)} s`;
};
export const channel = (kind: string) => (kind === "wordpress" ? "website" : kind);
export const kindIcon = (kind: string | undefined) =>
  kind === "owncast" ? <Tv size={15} /> : kind === "icecast" ? <Radio size={15} /> : <Globe size={15} />;

export function RangePicker({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  const { t } = useTranslation();
  return (
    <div className="seg" role="group" aria-label={t("dashboard.period")}>
      {RANGES.map((r) => <button key={r} type="button" aria-pressed={value === r} onClick={() => onChange(r)}>{t(`dashboard.range.${r}`)}</button>)}
    </div>
  );
}

/** Bars for views (or listening minutes for streams) with unique visitors as a line. */
export function MetricsChart({ granularity, buckets, series, color }: Pick<Detail, "granularity" | "buckets" | "series"> & { color: string }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const option = useMemo(() => {
    const text = cssVar("--muted", "#5d6b80");
    const grid = cssVar("--border", "#e2e7ef");
    const web = !!series.views?.some(Boolean) || !series.minutes?.some(Boolean);
    const main = web ? series.views : series.minutes;
    const label = (iso: string) => {
      const d = new Date(iso);
      return granularity === "day" ? d.toLocaleDateString(lang, { day: "numeric", month: "short" }) : d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
    };
    const list: object[] = [{ name: t(web ? "content.views" : "content.minutes"), type: "bar", data: main ?? buckets.map(() => 0), itemStyle: { color, borderRadius: [3, 3, 0, 0] } }];
    if (web && series.visitors) list.push({ name: t("content.visitors"), type: "line", data: series.visitors, showSymbol: false, smooth: 0.25, lineStyle: { width: 2 }, itemStyle: { color: cssVar("--text", "#1a2233") } });
    return {
      animationDuration: 300,
      tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v == null ? "–" : fmt(v, lang, 1)) },
      legend: { bottom: 0, textStyle: { color: text }, icon: "roundRect" },
      grid: { left: 8, right: 16, top: 16, bottom: 36, containLabel: true },
      xAxis: { type: "category", data: buckets.map(label), axisLabel: { color: text, hideOverlap: true }, axisLine: { lineStyle: { color: grid } } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
      series: list,
    };
  }, [granularity, buckets, series, color, lang, t]);
  return <Chart option={option} />;
}

function Breakdown({ title, rows }: { title: string; rows?: { key: string; value: number }[] }) {
  const { t, i18n } = useTranslation();
  const total = (rows ?? []).reduce((a, r) => a + r.value, 0);
  return (
    <div>
      <h3 className="small-title">{title}</h3>
      {rows?.length ? (
        <ul className="bars-list">
          {rows.map((r) => (
            <li key={r.key}>
              <span className="bar" style={{ width: `${total ? (r.value / total) * 100 : 0}%` }} />
              <span>{t(`content.device.${r.key}`, { defaultValue: r.key })}</span><b>{fmt(r.value, i18n.language)}</b>
            </li>
          ))}
        </ul>
      ) : <div className="muted small">{t("content.noBreakdown")}</div>}
    </div>
  );
}

export function ItemModal({ id, range, onClose }: { id: number; range: Range; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  const detail = useLoad(() => api.get<Detail>(`/api/content/${id}?range=${range === "24h" ? "7d" : range}`), [id, range]);
  const d = detail.data;
  const it = d?.item;
  const web = it?.source?.kind === "wordpress";
  return (
    <Modal title={it?.title ?? t("content.loading")} onClose={onClose}>
      {detail.error && <Alert kind="error">{errorText(detail.error)}</Alert>}
      {d && it && (
        <div className="stack">
          <div className="muted small row">
            {it.source && <span className="source-kind"><i style={{ background: theme?.channels?.[channel(it.source.kind)] }} />{kindIcon(it.source.kind)} {it.source.name}</span>}
            {it.published_at && <span>{formatDate(it.published_at, i18n.language)}</span>}
            {it.category && <span className="badge">{it.category}</span>}
            {it.authors?.length ? <span>{it.authors.map((a) => a.name).join(", ")}</span> : null}
            {it.url && <a href={it.url} target="_blank" rel="noreferrer">{t("content.open")} <ExternalLink size={13} /></a>}
          </div>
          <div className="kpis">
            {(web ? (["views", "visitors", "reads", "shares"] as const) : (["minutes", "peak"] as const)).map((k) => (
              <div className="kpi" key={k}><div className="kpi-label">{t(`content.${k}`)}</div><div className="kpi-value">{fmt(it.metrics[k], i18n.language)}</div></div>
            ))}
            {web && <div className="kpi"><div className="kpi-label">{t("content.avgRead")}</div><div className="kpi-value">{fmtSeconds(it.avg_read_seconds)}</div></div>}
          </div>
          <MetricsChart granularity={d.granularity} buckets={d.buckets} series={d.series} color={theme?.channels?.[channel(it.source?.kind ?? "")] ?? "#3E7BFA"} />
          {web && (
            <div className="grid two">
              <Breakdown title={t("content.referrers")} rows={d.dimensions.referrer} />
              <Breakdown title={t("content.devices")} rows={d.dimensions.device} />
            </div>
          )}
          <div className="row end"><button className="btn secondary" onClick={onClose}>{t("common.close")}</button></div>
        </div>
      )}
    </Modal>
  );
}

export function ItemsTable({ items, onOpen, showAuthors }: { items: Item[]; onOpen: (id: number) => void; showAuthors: boolean }) {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  const lang = i18n.language;
  return (
    <div className="table-wrap"><table>
      <thead><tr>
        <th>{t("content.title_")}</th>{showAuthors && <th>{t("content.authors")}</th>}<th>{t("content.published")}</th>
        <th className="num">{t("content.views")}</th><th className="num">{t("content.visitors")}</th><th className="num">{t("content.avgRead")}</th>
        <th className="num">{t("content.reads")}</th><th className="num">{t("content.shares")}</th><th className="num">{t("content.minutes")}</th>
      </tr></thead>
      <tbody>
        {items.map((i) => (
          <tr key={i.id} className="clickable" onClick={() => onOpen(i.id)}>
            <td>
              <button type="button" className="link-btn" onClick={(e) => { e.stopPropagation(); onOpen(i.id); }}>{i.title}</button>
              <div className="muted small source-kind"><i style={{ background: theme?.channels?.[channel(i.source?.kind ?? "")] }} />{kindIcon(i.source?.kind)} {i.source?.name}{i.category ? ` · ${i.category}` : ""}</div>
            </td>
            {showAuthors && <td>{i.authors?.map((a) => a.name).join(", ") || "–"}</td>}
            <td className="nowrap">{i.published_at ? new Date(i.published_at).toLocaleDateString(lang, { day: "numeric", month: "short" }) : "–"}</td>
            <td className="num">{fmt(i.metrics.views, lang)}</td>
            <td className="num">{fmt(i.metrics.visitors, lang)}</td>
            <td className="num">{fmtSeconds(i.avg_read_seconds)}</td>
            <td className="num">{fmt(i.metrics.reads, lang)}</td>
            <td className="num">{fmt(i.metrics.shares, lang)}</td>
            <td className="num">{i.metrics.minutes ? fmt(i.metrics.minutes, lang) : "–"}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  );
}

export default function Content() {
  const { t } = useTranslation();
  const [range, setRange] = useState<Range>("7d");
  const [sort, setSort] = useState<MetricKey | "published">("views");
  const [source, setSource] = useState("");
  const [category, setCategory] = useState("");
  const [person, setPerson] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const filters = useLoad(() => api.get<Filters>("/api/content/filters"));
  const params = new URLSearchParams({ range, sort, limit: "100" });
  if (source) params.set("source", source);
  if (category) params.set("category", category);
  if (person) params.set("person", person);
  if (query) params.set("q", query);
  const top = useLoad(() => api.get<Top>(`/api/content/top?${params}`), [params.toString()]);
  const showAuthors = !!filters.data?.can_see_editors;

  return (
    <div className="page">
      <PageHead help="content" title={t("content.title")} subtitle={t("content.subtitle")} actions={<RangePicker value={range} onChange={setRange} />} />
      <Card>
        <form className="toolbar filters" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
          <label className="search"><Search size={15} /><input value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => setQuery(q.trim())} placeholder={t("content.search")} aria-label={t("content.search")} /></label>
          <select value={source} onChange={(e) => setSource(e.target.value)} aria-label={t("content.source")}>
            <option value="">{t("content.allSources")}</option>
            {filters.data?.sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label={t("content.category")}>
            <option value="">{t("content.allCategories")}</option>
            {filters.data?.categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          {!!filters.data?.people.length && (
            <select value={person} onChange={(e) => setPerson(e.target.value)} aria-label={t("content.editor")}>
              <option value="">{t("content.allEditors")}</option>
              {filters.data.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
          <select value={sort} onChange={(e) => setSort(e.target.value as MetricKey)} aria-label={t("content.sortBy")}>
            {(["views", "visitors", "read_seconds", "reads", "shares", "comments", "minutes", "published"] as const).map((k) => <option key={k} value={k}>{t("content.sortBy")}: {t(`content.sort.${k}`)}</option>)}
          </select>
        </form>
        {top.error && <Alert kind="error">{errorText(top.error)}</Alert>}
        {top.data && (top.data.items.length ? <ItemsTable items={top.data.items} onOpen={setOpen} showAuthors={showAuthors} /> : (
          <div className="empty"><FileText /><h2>{t("content.noneTitle")}</h2><p>{t("content.noneText")}</p></div>
        ))}
      </Card>
      {open != null && <ItemModal id={open} range={range} onClose={() => setOpen(null)} />}
    </div>
  );
}
