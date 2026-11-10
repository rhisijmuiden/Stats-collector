import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Pencil, Plus, Target, Trash2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { formatDate, formatDay } from "../lib/format";
import { Alert, Card, Field, Modal, PageHead, Switch, useLoad } from "../components/ui";
import Chart, { cssVar } from "../components/Chart";
import { fmtInt } from "./Followers";

type Metric = "followers" | "views" | "reach" | "interactions" | "watch_minutes";
type Status = "reached" | "on_track" | "behind" | "missed";
const METRICS: Metric[] = ["followers", "views", "reach", "interactions", "watch_minutes"];
export interface Goal {
  id: number; name: string; metric: Metric; source_ids: number[]; sources: { id: number; name: string; kind: string }[];
  target: number; start_date: string; end_date: string | null; notify: boolean; notify_emails: string[]; archived: boolean;
  kind: "level" | "total"; current: number; baseline: number; progress: number; rate_per_day: number; needed_per_day: number | null;
  forecast: number | null; status: Status; spark?: number[];
  days?: string[]; values?: number[]; targets?: number[];
  revisions?: { target: number; end_date: string | null; note: string; changed_by: string | null; changed_at: string }[];
}
interface Draft {
  id?: number; name: string; metric: Metric; source_ids: number[]; target: string; start_date: string; end_date: string;
  notify: boolean; notify_emails: string; note: string; archived: boolean;
}

const STATUS_CLASS: Record<Status, string> = { reached: "good", on_track: "accent", behind: "warning", missed: "critical" };
const today = () => new Date().toISOString().slice(0, 10);

export function GoalProgress({ goal }: { goal: Goal }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  return (
    <div className="goal-progress">
      <div className="row between small">
        <span><b>{fmtInt(goal.current, lang)}</b> <span className="muted">/ {fmtInt(goal.target, lang)}</span></span>
        <span className={`badge ${STATUS_CLASS[goal.status]}`}>{t(`goals.status.${goal.status}`)}</span>
      </div>
      <div className={`progress ${goal.status}`}><span style={{ width: `${goal.progress}%` }} /></div>
    </div>
  );
}

function GoalChart({ goal }: { goal: Goal }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const option = useMemo(() => {
    const text = cssVar("--muted", "#5d6b80");
    const grid = cssVar("--border", "#e2e7ef");
    const accent = cssVar("--accent", "#0E9F8E");
    const days = [...(goal.days ?? [])];
    const values: (number | null)[] = [...(goal.values ?? [])];
    const targets: (number | null)[] = [...(goal.targets ?? [])];
    const forecast: (number | null)[] = values.map(() => null);
    // Extend the axis to the end date with the trend line and the current target.
    if (goal.end_date && days.length && goal.forecast != null && goal.end_date > days[days.length - 1]) {
      forecast[forecast.length - 1] = values[values.length - 1];
      const last = new Date(days[days.length - 1]);
      const end = new Date(goal.end_date);
      const steps = Math.round((end.getTime() - last.getTime()) / 86400000);
      for (let i = 1; i <= steps; i++) {
        const d = new Date(last.getTime() + i * 86400000);
        days.push(d.toISOString().slice(0, 10));
        values.push(null);
        targets.push(goal.target);
        forecast.push(i === steps ? goal.forecast : null);
      }
    }
    return {
      animationDuration: 300,
      tooltip: { trigger: "axis", valueFormatter: (v: number | null) => (v == null ? "–" : fmtInt(v, lang)) },
      legend: { bottom: 0, textStyle: { color: text } },
      grid: { left: 8, right: 16, top: 16, bottom: 36, containLabel: true },
      xAxis: { type: "category", data: days.map((x) => new Date(x).toLocaleDateString(lang, { day: "numeric", month: "short" })), axisLabel: { color: text, hideOverlap: true }, axisLine: { lineStyle: { color: grid } } },
      yAxis: { type: "value", scale: goal.kind === "level", axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
      series: [
        { name: t(`goals.metric.${goal.metric}`), type: "line", data: values, showSymbol: false, smooth: true, color: accent, areaStyle: { opacity: 0.12 } },
        { name: t("goals.target"), type: "line", step: "end", data: targets, showSymbol: false, color: cssVar("--critical", "#d93036"), lineStyle: { type: "dashed" } },
        { name: t("goals.trend"), type: "line", data: forecast, connectNulls: true, showSymbol: false, color: text, lineStyle: { type: "dotted" } },
      ],
    };
  }, [goal, lang, t]);
  return <Chart option={option} />;
}

function GoalDetail({ id, onClose, onEdit }: { id: number; onClose: () => void; onEdit?: (g: Goal) => void }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const goal = useLoad(() => api.get<Goal>(`/api/goals/${id}`), [id]);
  const g = goal.data;
  return (
    <Modal title={g?.name ?? "…"} onClose={onClose}>
      {goal.error && <Alert kind="error">{errorText(goal.error)}</Alert>}
      {g && (
        <div className="stack">
          <div className="muted small">{t(`goals.metric.${g.metric}`)} · {g.sources.length ? g.sources.map((s) => s.name).join(", ") : t("goals.allSources")} · {formatDay(g.start_date, lang)} – {g.end_date ? formatDay(g.end_date, lang) : t("goals.noEnd")}</div>
          <GoalProgress goal={g} />
          <div className="kpis">
            <div className="kpi"><div className="kpi-label">{t("goals.pace")}</div><div className="kpi-value">{fmtInt(g.rate_per_day, lang)}</div><div className="kpi-sub">{t("goals.perDay")}</div></div>
            {g.needed_per_day != null && <div className="kpi"><div className="kpi-label">{t("goals.needed")}</div><div className="kpi-value">{fmtInt(g.needed_per_day, lang)}</div><div className="kpi-sub">{t("goals.perDay")}</div></div>}
            {g.forecast != null && g.end_date && <div className="kpi"><div className="kpi-label">{t("goals.forecast")}</div><div className="kpi-value">{fmtInt(g.forecast, lang)}</div><div className="kpi-sub">{t("goals.onDate", { date: formatDay(g.end_date, lang) })}</div></div>}
          </div>
          <GoalChart goal={g} />
          <h3 className="small-title">{t("goals.history")}</h3>
          <div className="table-wrap"><table>
            <thead><tr><th>{t("goals.changedAt")}</th><th className="num">{t("goals.target")}</th><th>{t("goals.endDate")}</th><th>{t("goals.note")}</th><th>{t("goals.changedBy")}</th></tr></thead>
            <tbody>{(g.revisions ?? []).slice().reverse().map((r, i) => (
              <tr key={i}><td className="nowrap">{formatDate(r.changed_at, lang)}</td><td className="num">{fmtInt(r.target, lang)}</td><td>{r.end_date ? formatDay(r.end_date, lang) : "–"}</td><td>{r.note || "–"}</td><td>{r.changed_by ?? "–"}</td></tr>
            ))}</tbody>
          </table></div>
          <div className="row end">
            {onEdit && <button className="btn secondary" onClick={() => onEdit(g)}><Pencil /> {t("common.edit")}</button>}
            <button className="btn secondary" onClick={onClose}>{t("common.close")}</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

export function GoalsCard() {
  const { t } = useTranslation();
  const goals = useLoad(() => api.get<Goal[]>("/api/goals"));
  if (!goals.data?.length) return null;
  return (
    <Card title={t("goals.title")} actions={<Link className="btn ghost" to="/goals">{t("goals.all")}</Link>}>
      <div className="goal-grid">
        {goals.data.slice(0, 6).map((g) => (
          <Link key={g.id} to={`/goals?open=${g.id}`} className="goal-tile">
            <div className="goal-name">{g.name}</div>
            <GoalProgress goal={g} />
          </Link>
        ))}
      </div>
    </Card>
  );
}

export default function GoalsPage() {
  const { t, i18n } = useTranslation();
  const { user, toast } = useApp();
  const lang = i18n.language;
  const canEdit = user?.role === "admin" || user?.role === "editor_in_chief";
  const [archived, setArchived] = useState(false);
  const list = useLoad(() => api.get<Goal[]>(`/api/goals?archived=${archived}`), [archived]);
  const filters = useLoad(() => api.get<{ sources: { id: number; name: string; kind: string }[] }>("/api/content/filters"));
  const [open, setOpen] = useState<number | null>(() => Number(new URLSearchParams(window.location.search).get("open")) || null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const edit = (g?: Goal) => {
    setOpen(null);
    setDraft(g ? {
      id: g.id, name: g.name, metric: g.metric, source_ids: g.source_ids, target: String(g.target), start_date: g.start_date,
      end_date: g.end_date ?? "", notify: g.notify, notify_emails: g.notify_emails.join(", "), note: "", archived: g.archived,
    } : { name: "", metric: "followers", source_ids: [], target: "", start_date: today(), end_date: "", notify: false, notify_emails: "", note: "", archived: false });
  };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    const d = draft!;
    const body = {
      name: d.name, metric: d.metric, source_ids: d.source_ids, target: Number(d.target), start_date: d.start_date,
      end_date: d.end_date || null, notify: d.notify, notify_emails: d.notify_emails.split(/[\s,;]+/).filter(Boolean), note: d.note, archived: d.archived,
    };
    try {
      if (d.id) await api.put(`/api/goals/${d.id}`, body); else await api.post("/api/goals", body);
      toast("success", t("common.saved"));
      setDraft(null);
      list.reload();
    } catch (err) { fail(err); }
  };
  const remove = async () => {
    if (!window.confirm(t("goals.confirmDelete", { name: draft!.name }))) return;
    try { await api.del(`/api/goals/${draft!.id}`); setDraft(null); list.reload(); } catch (err) { fail(err); }
  };
  const sources = filters.data?.sources ?? [];
  const toggleSource = (id: number) => setDraft({ ...draft!, source_ids: draft!.source_ids.includes(id) ? draft!.source_ids.filter((x) => x !== id) : [...draft!.source_ids, id] });

  return (
    <div className="page">
      <PageHead help="followers-and-goals" title={t("goals.title")} subtitle={t("goals.subtitle")}
        actions={<>
          <div className="seg">{([false, true] as const).map((v) => <button key={String(v)} type="button" aria-pressed={archived === v} onClick={() => setArchived(v)}>{t(v ? "goals.archived" : "goals.active")}</button>)}</div>
          {canEdit && <button className="btn" onClick={() => edit()}><Plus /> {t("goals.add")}</button>}
        </>} />
      {list.error && <Alert kind="error">{errorText(list.error)}</Alert>}
      {list.data && (list.data.length ? (
        <div className="goal-cards">
          {list.data.map((g) => (
            <button key={g.id} type="button" className="card goal-card" onClick={() => setOpen(g.id)}>
              <div className="row between">
                <h2>{g.name}</h2>
                {canEdit && <span className="btn ghost" role="button" aria-label={t("common.edit")} onClick={(ev) => { ev.stopPropagation(); edit(g); }}><Pencil /></span>}
              </div>
              <div className="muted small">{t(`goals.metric.${g.metric}`)} · {g.sources.length ? g.sources.map((s) => s.name).join(", ") : t("goals.allSources")}</div>
              <GoalProgress goal={g} />
              <div className="muted small">
                {g.end_date ? t("goals.until", { date: formatDay(g.end_date, lang) }) : t("goals.noEnd")}
                {g.forecast != null && g.end_date && g.status !== "reached" ? ` · ${t("goals.forecastShort", { value: fmtInt(g.forecast, lang) })}` : ""}
              </div>
            </button>
          ))}
        </div>
      ) : <Card><div className="empty"><Target /><h2>{t("goals.noneTitle")}</h2><p>{t(canEdit ? "goals.noneText" : "goals.noneTextReader")}</p></div></Card>)}

      {open != null && <GoalDetail id={open} onClose={() => setOpen(null)} onEdit={canEdit ? edit : undefined} />}
      {draft && (
        <Modal title={draft.id ? t("goals.edit") : t("goals.add")} onClose={() => setDraft(null)}>
          <form className="stack" onSubmit={save}>
            <Field label={t("goals.name")}><input required maxLength={200} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder={t("goals.namePlaceholder")} /></Field>
            <div className="grid two">
              <Field label={t("goals.metricLabel")} hint={t(`goals.metricHint.${draft.metric}`)}>
                <select value={draft.metric} onChange={(e) => setDraft({ ...draft, metric: e.target.value as Metric })}>
                  {METRICS.map((m) => <option key={m} value={m}>{t(`goals.metric.${m}`)}</option>)}
                </select>
              </Field>
              <Field label={t("goals.target")}><input required type="number" min={1} step="any" value={draft.target} onChange={(e) => setDraft({ ...draft, target: e.target.value })} /></Field>
              <Field label={t("goals.startDate")}><input required type="date" value={draft.start_date} onChange={(e) => setDraft({ ...draft, start_date: e.target.value })} /></Field>
              <Field label={t("goals.endDate")} hint={t("goals.endHint")}><input type="date" value={draft.end_date} min={draft.start_date} onChange={(e) => setDraft({ ...draft, end_date: e.target.value })} /></Field>
            </div>
            <Field label={t("goals.sources")} hint={t("goals.sourcesHint")}>
              <div className="choice-list">{sources.map((s) => (
                <button key={s.id} type="button" className={`btn ${draft.source_ids.includes(s.id) ? "" : "secondary"}`} aria-pressed={draft.source_ids.includes(s.id)} onClick={() => toggleSource(s.id)}>{s.name}</button>
              ))}</div>
            </Field>
            {draft.id && <Field label={t("goals.note")} hint={t("goals.noteHint")}><input maxLength={500} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} /></Field>}
            <Switch checked={draft.notify} onChange={(v) => setDraft({ ...draft, notify: v })} label={t("goals.notify")} />
            {draft.notify && <Field label={t("goals.notifyEmails")} hint={t("goals.notifyHint")}><input value={draft.notify_emails} onChange={(e) => setDraft({ ...draft, notify_emails: e.target.value })} placeholder="hoofdredactie@example.org" /></Field>}
            {draft.id && <Switch checked={draft.archived} onChange={(v) => setDraft({ ...draft, archived: v })} label={t("goals.archive")} />}
            <div className="row end">
              {draft.id && <button type="button" className="btn ghost" onClick={remove}><Trash2 /> {t("common.delete")}</button>}
              <button type="button" className="btn secondary" onClick={() => setDraft(null)}>{t("common.cancel")}</button>
              <button className="btn">{t("common.save")}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
