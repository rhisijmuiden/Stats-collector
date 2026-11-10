import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { ArrowDown, ArrowUp, Check, LayoutGrid, Pencil, Plus, Share2, Sparkles, Trash2, X } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { Alert, Card, Field, Modal, PageHead, Switch, useLoad } from "../components/ui";
import Chart, { cssVar, shade } from "../components/Chart";
import { errorText } from "../i18n";
import { fmt, fmtSeconds, type Item, ItemModal, ItemsTable, kindIcon, type Range, RangePicker } from "./Content";
import { GoalsCard } from "./Goals";

type Measure = "reach" | "views" | "interactions" | "watch_minutes" | "followers";
type Split = "none" | "platform" | "source";
type Mode = "stacked" | "overlay" | "separate";
type Platform = "website" | "youtube" | "facebook" | "instagram" | "bluesky" | "mastodon" | "owncast" | "icecast";
export interface Widget {
  id: string; type: "kpi" | "chart" | "top" | "editors" | "goals"; title: string; size: "small" | "half" | "full";
  measure: Measure; sources: number[]; platforms: Platform[]; split: Split; mode: Mode; chart: "line" | "area" | "bar";
  sort: string; kind: string; limit: number;
}
interface Dashboard { id: number; name: string; widgets: Widget[]; shared: boolean; position: number; mine: boolean; can_edit: boolean }
interface Data {
  kind: "level" | "total"; granularity: "hour" | "day"; buckets: string[]; total: number; previous: number | null; change: number | null;
  series: { key: string; name: string; kind: string; platform: string; values: (number | null)[]; total: number }[]; daily_only: number[];
}
interface SourceRef { id: number; name: string; kind: string }

const MEASURES: Measure[] = ["reach", "views", "interactions", "watch_minutes", "followers"];
const PLATFORMS: Platform[] = ["website", "facebook", "instagram", "bluesky", "mastodon", "youtube", "owncast", "icecast"];
const SORTS = ["views", "reach", "visitors", "shares", "comments", "likes", "minutes", "published"];
const KINDS = ["", "article", "post", "video", "broadcast", "mount"];
const STORE = "sc.dashboard";

export const newWidget = (type: Widget["type"]): Widget => ({
  id: Math.random().toString(36).slice(2, 10), type, title: "", size: type === "kpi" ? "small" : type === "chart" ? "full" : "half",
  measure: "reach", sources: [], platforms: [], split: "platform", mode: "stacked", chart: "area", sort: "views", kind: "", limit: 10,
});

function useData(w: Widget, range: Range) {
  const q = new URLSearchParams({ measure: w.measure, range, split: w.type === "kpi" ? "none" : w.split });
  w.sources.forEach((s) => q.append("sources", String(s)));
  w.platforms.forEach((p) => q.append("platforms", p));
  return useLoad(() => api.get<Data>(`/api/dashboards/data?${q}`), [q.toString()]);
}

const widgetTitle = (w: Widget, t: TFunction) =>
  w.title || (w.type === "kpi" || w.type === "chart" ? t(`dashboards.measure.${w.measure}`) : t(`dashboards.type.${w.type}`));

const fmtMeasure = (v: number, _m: Measure, lang: string) => fmt(v, lang);

function Kpi({ w, range }: { w: Widget; range: Range }) {
  const { t, i18n } = useTranslation();
  const d = useData(w, range);
  const c = d.data?.change;
  return (
    <div className="kpi dash-kpi">
      <div className="kpi-label">{widgetTitle(w, t)}</div>
      {d.error ? <div className="muted small">{errorText(d.error)}</div> : (
        <>
          <div className="kpi-value">{d.data ? fmtMeasure(d.data.total, w.measure, i18n.language) : "…"}</div>
          <div className="kpi-sub">
            {c == null ? t("dashboards.noCompare") : <span className={c >= 0 ? "up" : "down"}>{c >= 0 ? "▲" : "▼"} {fmt(Math.abs(c), i18n.language, 1)}%</span>}
            {c != null && ` ${t("dashboards.vsPrevious")}`}
          </div>
        </>
      )}
    </div>
  );
}

function ChartWidget({ w, range, onMode }: { w: Widget; range: Range; onMode: (m: Mode) => void }) {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  const lang = i18n.language;
  const d = useData(w, range).data;
  const colors = useMemo(() => {
    const seen: Record<string, number> = {};
    return (d?.series ?? []).map((s) => s.key === "total" ? cssVar("--accent", "#0e9f8e") : shade(theme?.channels?.[s.platform] ?? "#3E7BFA", (seen[s.platform] = (seen[s.platform] ?? -1) + 1)));
  }, [d, theme]);
  const name = (s: Data["series"][number]) => (w.split === "platform" ? t(`dashboards.platform.${s.key}`) : s.key === "total" ? t("dashboards.total") : s.name);
  const option = (subset: number[], small: boolean) => {
    if (!d) return {};
    const text = cssVar("--muted", "#5d6b80");
    const grid = cssVar("--border", "#e2e7ef");
    const stack = w.mode === "stacked" && !small;
    return {
      animationDuration: 300,
      color: subset.map((i) => colors[i]),
      tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v == null ? "–" : fmt(v, lang)) },
      legend: small ? { show: false } : { bottom: 0, textStyle: { color: text }, icon: "roundRect" },
      grid: { left: 8, right: 12, top: small ? 8 : 16, bottom: small ? 4 : 36, containLabel: true },
      xAxis: {
        type: "category", data: d.buckets.map((b) => new Date(b)[d.granularity === "day" ? "toLocaleDateString" : "toLocaleTimeString"](lang, d.granularity === "day" ? { day: "numeric", month: "short" } : { hour: "2-digit", minute: "2-digit" })),
        axisLabel: { color: text, hideOverlap: true }, axisLine: { lineStyle: { color: grid } },
      },
      yAxis: { type: "value", scale: d.kind === "level" && !stack, axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
      series: subset.map((i) => {
        const s = d.series[i];
        const bar = w.chart === "bar";
        return {
          name: name(s), type: bar ? "bar" : "line", data: s.values, showSymbol: false, smooth: 0.25, connectNulls: d.kind === "level",
          ...(stack ? { stack: "total" } : {}),
          ...(!bar && (w.chart === "area" || stack) ? { areaStyle: { opacity: stack ? 0.35 : 0.12 } } : {}),
          ...(bar ? { itemStyle: { borderRadius: stack ? 0 : [3, 3, 0, 0] } } : {}),
        };
      }),
    };
  };
  const all = (d?.series ?? []).map((_, i) => i);
  return (
    <Card title={widgetTitle(w, t)} subtitle={d ? `${t("dashboards.total")}: ${fmtMeasure(d.total, w.measure, lang)}${d.change != null ? ` (${d.change >= 0 ? "+" : ""}${fmt(d.change, lang, 1)}%)` : ""}` : undefined}
      actions={w.split !== "none" && (d?.series.length ?? 0) > 1 ? (
        <div className="seg" role="group" aria-label={t("dashboards.mode")}>
          {(["stacked", "overlay", "separate"] as const).map((m) => <button key={m} type="button" aria-pressed={w.mode === m} onClick={() => onMode(m)}>{t(`dashboards.modes.${m}`)}</button>)}
        </div>
      ) : undefined}>
      {d && !d.series.length && <p className="muted small">{t("dashboards.noData")}</p>}
      {d && d.daily_only.length > 0 && <p className="muted small">{t("dashboards.dailyOnly")}</p>}
      {d && d.series.length > 0 && (w.mode === "separate" && d.series.length > 1 ? (
        <div className="multiples">
          {all.map((i) => (
            <div key={d.series[i].key} className="multiple">
              <div className="multiple-head"><i style={{ background: colors[i] }} />{kindIcon(d.series[i].kind)} {name(d.series[i])}<b>{fmtMeasure(d.series[i].total, w.measure, lang)}</b></div>
              <Chart option={option([i], true)} className="chart small" />
            </div>
          ))}
        </div>
      ) : <Chart option={option(all, false)} />)}
    </Card>
  );
}

function TopWidget({ w, range }: { w: Widget; range: Range }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<number | null>(null);
  const q = new URLSearchParams({ range, sort: w.sort, limit: String(w.limit) });
  if (w.kind) q.set("kind", w.kind);
  const top = useLoad(() => api.get<{ items: Item[] }>(`/api/content/top?${q}`), [q.toString()]);
  return (
    <Card title={widgetTitle(w, t)}>
      {top.error && <Alert kind="error">{errorText(top.error)}</Alert>}
      {top.data && (top.data.items.length ? <ItemsTable items={top.data.items} onOpen={setOpen} showAuthors={false} /> : <p className="muted small">{t("dashboards.noData")}</p>)}
      {open != null && <ItemModal id={open} range={range} onClose={() => setOpen(null)} />}
    </Card>
  );
}

interface EditorRow { id: number; name: string; published: number; avg_read_seconds: number; metrics: { views: number }; social?: { views: number } }
function EditorsWidget({ w, range }: { w: Widget; range: Range }) {
  const { t, i18n } = useTranslation();
  const list = useLoad(() => api.get<{ editors: EditorRow[] }>(`/api/editors?range=${range}`), [range]);
  const rows = (list.data?.editors ?? []).slice(0, w.limit);
  const max = Math.max(1, ...rows.map((e) => e.metrics.views));
  return (
    <Card title={widgetTitle(w, t)}>
      {list.error && <p className="muted small">{list.error === "forbidden" ? t("dashboards.editorsHidden") : errorText(list.error)}</p>}
      {list.data && (rows.length ? (
        <div className="table-wrap"><table>
          <thead><tr><th>{t("editors.name")}</th><th className="num">{t("editors.published")}</th><th>{t("content.views")}</th><th className="num">{t("content.avgRead")}</th><th className="num">{t("editors.socialViews")}</th></tr></thead>
          <tbody>{rows.map((e) => (
            <tr key={e.id}><td>{e.name}</td><td className="num">{e.published}</td>
              <td className="meter-cell"><div><span className="meter"><span style={{ width: `${(e.metrics.views / max) * 100}%` }} /></span><b>{fmt(e.metrics.views, i18n.language)}</b></div></td>
              <td className="num">{fmtSeconds(e.avg_read_seconds)}</td><td className="num">{e.social?.views ? fmt(e.social.views, i18n.language) : "–"}</td></tr>
          ))}</tbody>
        </table></div>
      ) : <p className="muted small">{t("dashboards.noData")}</p>)}
    </Card>
  );
}

function WidgetForm({ initial, adding, sources, onSave, onClose }: { initial: Widget; adding: boolean; sources: SourceRef[]; onSave: (w: Widget) => void; onClose: () => void }) {
  const { t } = useTranslation();
  const [w, setW] = useState(initial);
  const set = (patch: Partial<Widget>) => setW((x) => ({ ...x, ...patch }));
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const series = w.type === "kpi" || w.type === "chart";
  return (
    <Modal title={t(adding ? "dashboards.addWidget" : "dashboards.editWidget")} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSave(w); }}>
        <div className="grid two">
          <Field label={t("dashboards.widgetType")}>
            <select value={w.type} onChange={(e) => set({ type: e.target.value as Widget["type"] })}>
              {(["kpi", "chart", "top", "editors", "goals"] as const).map((k) => <option key={k} value={k}>{t(`dashboards.type.${k}`)}</option>)}
            </select>
          </Field>
          <Field label={t("dashboards.size")}>
            <select value={w.size} onChange={(e) => set({ size: e.target.value as Widget["size"] })}>
              {(["small", "half", "full"] as const).map((k) => <option key={k} value={k}>{t(`dashboards.sizes.${k}`)}</option>)}
            </select>
          </Field>
        </div>
        <Field label={t("dashboards.widgetTitle")} hint={t("dashboards.widgetTitleHint")}>
          <input value={w.title} maxLength={200} onChange={(e) => set({ title: e.target.value })} placeholder={widgetTitle({ ...w, title: "" }, t)} />
        </Field>
        {series && (
          <>
            <Field label={t("dashboards.measureLabel")} hint={t(`dashboards.measureHint.${w.measure}`)}>
              <select value={w.measure} onChange={(e) => set({ measure: e.target.value as Measure })}>
                {MEASURES.map((m) => <option key={m} value={m}>{t(`dashboards.measure.${m}`)}</option>)}
              </select>
            </Field>
            <Field label={t("dashboards.platforms")} hint={t("dashboards.allWhenEmpty")}>
              <div className="chips">{PLATFORMS.map((p) => <button key={p} type="button" className="chip" aria-pressed={w.platforms.includes(p)} onClick={() => set({ platforms: toggle(w.platforms, p) })}>{t(`dashboards.platform.${p}`)}</button>)}</div>
            </Field>
            <Field label={t("dashboards.sources")} hint={t("dashboards.allWhenEmpty")}>
              <div className="chips">{sources.map((s) => <button key={s.id} type="button" className="chip" aria-pressed={w.sources.includes(s.id)} onClick={() => set({ sources: toggle(w.sources, s.id) })}>{kindIcon(s.kind)} {s.name}</button>)}</div>
            </Field>
          </>
        )}
        {w.type === "chart" && (
          <div className="grid three">
            <Field label={t("dashboards.split")}>
              <select value={w.split} onChange={(e) => set({ split: e.target.value as Split })}>
                {(["platform", "source", "none"] as const).map((k) => <option key={k} value={k}>{t(`dashboards.splits.${k}`)}</option>)}
              </select>
            </Field>
            <Field label={t("dashboards.mode")}>
              <select value={w.mode} onChange={(e) => set({ mode: e.target.value as Mode })}>
                {(["stacked", "overlay", "separate"] as const).map((k) => <option key={k} value={k}>{t(`dashboards.modes.${k}`)}</option>)}
              </select>
            </Field>
            <Field label={t("dashboards.chartType")}>
              <select value={w.chart} onChange={(e) => set({ chart: e.target.value as Widget["chart"] })}>
                {(["area", "line", "bar"] as const).map((k) => <option key={k} value={k}>{t(`dashboards.charts.${k}`)}</option>)}
              </select>
            </Field>
          </div>
        )}
        {w.type === "top" && (
          <div className="grid two">
            <Field label={t("content.sortBy")}>
              <select value={w.sort} onChange={(e) => set({ sort: e.target.value })}>{SORTS.map((k) => <option key={k} value={k}>{t(`content.sort.${k}`)}</option>)}</select>
            </Field>
            <Field label={t("dashboards.itemKind")}>
              <select value={w.kind} onChange={(e) => set({ kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{t(`dashboards.kinds.${k || "all"}`)}</option>)}</select>
            </Field>
          </div>
        )}
        {(w.type === "top" || w.type === "editors") && (
          <Field label={t("dashboards.limit")}><input type="number" min={1} max={50} value={w.limit} onChange={(e) => set({ limit: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} /></Field>
        )}
        <div className="row end">
          <button type="button" className="btn secondary" onClick={onClose}>{t("common.cancel")}</button>
          <button type="submit" className="btn"><Check /> {t("common.save")}</button>
        </div>
      </form>
    </Modal>
  );
}

export default function DashboardsPage() {
  const { t } = useTranslation();
  const { user, toast } = useApp();
  const list = useLoad(() => api.get<Dashboard[]>("/api/dashboards"));
  const sources = useLoad(() => api.get<{ sources: SourceRef[] }>("/api/content/filters"));
  const [selected, setSelected] = useState<number | null>(() => { try { return Number(localStorage.getItem(STORE)) || null; } catch { return null; } });
  const [range, setRange] = useState<Range>("30d");
  const [draft, setDraft] = useState<Dashboard | null>(null);
  const [form, setForm] = useState<{ widget: Widget; index: number } | null>(null);
  const dashboards = list.data ?? [];
  const current = draft ?? dashboards.find((d) => d.id === selected) ?? dashboards[0] ?? null;
  const canShare = user?.role === "admin" || user?.role === "editor_in_chief";
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  useEffect(() => { if (current && !draft) { try { localStorage.setItem(STORE, String(current.id)); } catch { /* private mode */ } } }, [current, draft]);

  const save = async (d: Dashboard) => {
    const body = { name: d.name, widgets: d.widgets, shared: d.shared, position: d.position };
    try {
      const out = d.id ? await api.put<Dashboard>(`/api/dashboards/${d.id}`, body) : await api.post<Dashboard>("/api/dashboards", body);
      setDraft(null); setSelected(out.id); list.reload(); toast("success", t("dashboards.saved"));
    } catch (e) { fail(e); }
  };
  const remove = async (d: Dashboard) => {
    if (!window.confirm(t("dashboards.confirmDelete", { name: d.name }))) return;
    try { await api.del(`/api/dashboards/${d.id}`); setDraft(null); setSelected(null); list.reload(); } catch (e) { fail(e); }
  };
  const example = async () => {
    try { const out = await api.post<Dashboard>("/api/dashboards/example", {}); setSelected(out.id); list.reload(); } catch (e) { fail(e); }
  };
  const patchWidgets = (fn: (ws: Widget[]) => Widget[]) => current && setDraft({ ...current, widgets: fn([...current.widgets]) });
  // Switching the view of a chart is allowed for everyone; it is saved only by those who may edit.
  const [modes, setModes] = useState<Record<string, Mode>>({});
  const viewMode = (w: Widget) => (draft ? w.mode : modes[`${current?.id}:${w.id}`] ?? w.mode);

  const render = (w: Widget, i: number) => {
    const view = { ...w, mode: viewMode(w) };
    const body = w.type === "kpi" ? <Kpi w={view} range={range} />
      : w.type === "chart" ? <ChartWidget w={view} range={range} onMode={(m) => (draft ? patchWidgets((ws) => ws.map((x) => (x.id === w.id ? { ...x, mode: m } : x))) : setModes((s) => ({ ...s, [`${current?.id}:${w.id}`]: m })))} />
        : w.type === "top" ? <TopWidget w={view} range={range} />
          : w.type === "editors" ? <EditorsWidget w={view} range={range} />
            : <GoalsCard />;
    return (
      <div key={w.id} className={`dash-cell ${w.size}${draft ? " editing" : ""}`}>
        {body}
        {draft && (
          <div className="dash-tools">
            <button type="button" className="btn ghost small" aria-label={t("dashboards.moveUp")} title={t("dashboards.moveUp")} disabled={i === 0} onClick={() => patchWidgets((ws) => { [ws[i - 1], ws[i]] = [ws[i], ws[i - 1]]; return ws; })}><ArrowUp /></button>
            <button type="button" className="btn ghost small" aria-label={t("dashboards.moveDown")} title={t("dashboards.moveDown")} disabled={i === draft.widgets.length - 1} onClick={() => patchWidgets((ws) => { [ws[i + 1], ws[i]] = [ws[i], ws[i + 1]]; return ws; })}><ArrowDown /></button>
            <button type="button" className="btn ghost small" aria-label={t("common.edit")} title={t("common.edit")} onClick={() => setForm({ widget: w, index: i })}><Pencil /></button>
            <button type="button" className="btn ghost small" aria-label={t("common.delete")} title={t("common.delete")} onClick={() => patchWidgets((ws) => ws.filter((_, n) => n !== i))}><Trash2 /></button>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="page">
      <PageHead help="dashboards" title={t("dashboards.title")} subtitle={t("dashboards.subtitle")}
        actions={<RangePicker value={range} onChange={setRange} />} />
      {list.error && <Alert kind="error">{errorText(list.error)}</Alert>}
      {list.data && (
        <div className="dash-bar">
          {draft ? (
            <>
              <input className="dash-name" value={draft.name} maxLength={200} onChange={(e) => setDraft({ ...draft, name: e.target.value })} aria-label={t("dashboards.name")} />
              {canShare && <Switch checked={draft.shared} onChange={(v) => setDraft({ ...draft, shared: v })} label={t("dashboards.shared")} />}
              <span className="grow" />
              <button type="button" className="btn secondary" onClick={() => setForm({ widget: newWidget("chart"), index: -1 })}><Plus /> {t("dashboards.addWidget")}</button>
              {draft.id ? <button type="button" className="btn ghost" onClick={() => remove(draft)}><Trash2 /> {t("common.delete")}</button> : null}
              <button type="button" className="btn ghost" onClick={() => setDraft(null)}><X /> {t("common.cancel")}</button>
              <button type="button" className="btn" disabled={!draft.name.trim()} onClick={() => save(draft)}><Check /> {t("common.save")}</button>
            </>
          ) : (
            <>
              <div className="tabs" role="tablist">
                {dashboards.map((d) => (
                  <button key={d.id} type="button" role="tab" className="tab" aria-selected={current?.id === d.id} onClick={() => setSelected(d.id)}>
                    {d.name}{d.shared && <Share2 size={13} aria-label={t("dashboards.shared")} />}
                  </button>
                ))}
              </div>
              <span className="grow" />
              {current?.can_edit && <button type="button" className="btn secondary" onClick={() => setDraft(current)}><Pencil /> {t("dashboards.edit")}</button>}
              <button type="button" className="btn secondary" onClick={() => setDraft({ id: 0, name: t("dashboards.newName"), widgets: [], shared: false, position: dashboards.length, mine: true, can_edit: true })}><Plus /> {t("dashboards.new")}</button>
            </>
          )}
        </div>
      )}
      {list.data && !current && (
        <Card><div className="empty"><LayoutGrid /><h2>{t("dashboards.noneTitle")}</h2><p>{t("dashboards.noneText")}</p>
          <button type="button" className="btn" onClick={example}><Sparkles /> {t("dashboards.example")}</button></div></Card>
      )}
      {current && (current.widgets.length ? <div className="dash-grid">{current.widgets.map(render)}</div> : (
        <Card><div className="empty"><LayoutGrid /><h2>{t("dashboards.emptyTitle")}</h2><p>{t(draft ? "dashboards.emptyEdit" : "dashboards.emptyText")}</p></div></Card>
      ))}
      {form && (
        <WidgetForm initial={form.widget} adding={form.index < 0} sources={sources.data?.sources ?? []} onClose={() => setForm(null)}
          onSave={(w) => { patchWidgets((ws) => (form.index < 0 ? [...ws, w] : ws.map((x, n) => (n === form.index ? w : x)))); setForm(null); }} />
      )}
    </div>
  );
}
