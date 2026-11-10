import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowDown, ArrowUp, Check, Clock, ExternalLink, FileText, History, Pencil, Plus, Send, Trash2, X, Zap } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { Alert, Card, Field, Modal, PageHead, Switch, useLoad } from "../components/ui";
import { errorText } from "../i18n";
import { newWidget, type SourceRef, type Widget, WidgetForm, widgetTitle } from "./Dashboards";
import { periodText } from "./ReportView";

type Period = "yesterday" | "last_week" | "last_month" | "last_7d" | "last_30d" | "last_90d";
type Schedule = "none" | "daily" | "weekly" | "monthly";
interface Run {
  id: number; report_id: number; title: string; start: string; end: string; created_at: string; trigger: "manual" | "schedule";
  status: "generated" | "sent" | "failed"; sent_at: string | null; recipients: string[]; error: string; expires_at: string; link: string | null;
}
interface Report {
  id: number; name: string; title: string; intro: string; blocks: Widget[]; period: Period; language: "en" | "nl";
  schedule: Schedule; send_time: string; weekday: number; monthday: number; recipient_users: number[]; recipient_emails: string[];
  attach_pdf: boolean; link_days: number; enabled: boolean; next_run_at: string | null; mine: boolean; can_send: boolean; last_run: Run | null;
}
interface Person { id: number; name: string; email: string; role: string }

const PERIODS: Period[] = ["last_month", "last_week", "yesterday", "last_7d", "last_30d", "last_90d"];
const SCHEDULES: Schedule[] = ["none", "daily", "weekly", "monthly"];
const SEES_EDITORS = ["admin", "editor_in_chief"];

const EXAMPLE_BLOCKS = (): Widget[] => [
  { ...newWidget("kpi"), measure: "reach" },
  { ...newWidget("kpi"), measure: "views" },
  { ...newWidget("kpi"), measure: "interactions" },
  { ...newWidget("chart"), measure: "reach", split: "platform", mode: "stacked" },
  { ...newWidget("chart"), measure: "followers", split: "platform", mode: "overlay", chart: "line", size: "half" },
  { ...newWidget("top"), sort: "views", limit: 10 },
];

function blank(lang: "en" | "nl"): Report {
  return {
    id: 0, name: "", title: "", intro: "", blocks: EXAMPLE_BLOCKS(), period: "last_month", language: lang, schedule: "none",
    send_time: "08:00", weekday: 0, monthday: 1, recipient_users: [], recipient_emails: [], attach_pdf: true, link_days: 30,
    enabled: true, next_run_at: null, mine: true, can_send: false, last_run: null,
  };
}

function Archive({ report, onClose }: { report: Report; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const runs = useLoad(() => api.get<Run[]>(`/api/reports/${report.id}/runs`), [report.id]);
  const lang = i18n.language;
  return (
    <Modal title={t("reports.archiveTitle", { name: report.name })} onClose={onClose}>
      {runs.error && <Alert kind="error">{errorText(runs.error)}</Alert>}
      {runs.data && (runs.data.length ? (
        <div className="table-wrap"><table>
          <thead><tr><th>{t("reports.made")}</th><th>{t("reports.periodLabel")}</th><th>{t("reports.status")}</th><th>{t("reports.recipients")}</th><th /></tr></thead>
          <tbody>{runs.data.map((r) => (
            <tr key={r.id}>
              <td className="nowrap">{new Date(r.created_at).toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" })}<div className="muted small">{t(`reports.trigger.${r.trigger}`)}</div></td>
              <td>{periodText(r.start, r.end, lang)}</td>
              <td><span className={`badge ${r.status === "sent" ? "good" : r.status === "failed" ? "critical" : ""}`}>{t(`reports.statuses.${r.status}`)}</span>{r.error && <div className="muted small">{r.error}</div>}</td>
              <td className="small">{r.recipients.join(", ") || "–"}</td>
              <td className="nowrap">
                <a className="btn ghost small" href={`/reports/runs/${r.id}`} target="_blank" rel="noreferrer"><ExternalLink /> {t("reports.open")}</a>
                <a className="btn ghost small" href={`/api/reports/runs/${r.id}/pdf`}><FileText /> PDF</a>
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <p className="muted">{t("reports.noRuns")}</p>)}
    </Modal>
  );
}

function Editor({ initial, people, sources, canSend, onSaved, onClose }: {
  initial: Report; people: Person[]; sources: SourceRef[]; canSend: boolean; onSaved: (r: Report) => void; onClose: () => void;
}) {
  const { t } = useTranslation();
  const { toast } = useApp();
  const [r, setR] = useState(initial);
  const [emails, setEmails] = useState(initial.recipient_emails.join(", "));
  const [form, setForm] = useState<{ widget: Widget; index: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<Report>) => setR((x) => ({ ...x, ...patch }));
  const blocks = (fn: (b: Widget[]) => Widget[]) => setR((x) => ({ ...x, blocks: fn([...x.blocks]) }));
  const hasEditors = r.blocks.some((b) => b.type === "editors");
  const types: Widget["type"][] = canSend ? ["kpi", "chart", "top", "editors", "goals", "text"] : ["kpi", "chart", "top", "goals", "text"];
  const toggleUser = (id: number) => set({ recipient_users: r.recipient_users.includes(id) ? r.recipient_users.filter((x) => x !== id) : [...r.recipient_users, id] });

  const save = async () => {
    setBusy(true);
    const body = {
      name: r.name, title: r.title, intro: r.intro, blocks: r.blocks, period: r.period, language: r.language,
      schedule: canSend ? r.schedule : "none", send_time: r.send_time, weekday: r.weekday, monthday: r.monthday,
      recipient_users: canSend ? r.recipient_users : [], recipient_emails: canSend ? emails.split(/[\s,;]+/).filter(Boolean) : [],
      attach_pdf: r.attach_pdf, link_days: r.link_days, enabled: r.enabled,
    };
    try {
      const out = r.id ? await api.put<Report>(`/api/reports/${r.id}`, body) : await api.post<Report>("/api/reports", body);
      toast("success", t("reports.saved"));
      onSaved(out);
    } catch (e) {
      toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <Card title={t(r.id ? "reports.edit" : "reports.new")} actions={
        <div className="row">
          <button type="button" className="btn ghost" onClick={onClose}><X /> {t("common.cancel")}</button>
          <button type="button" className="btn" disabled={busy || !r.name.trim()} onClick={save}><Check /> {t("common.save")}</button>
        </div>
      }>
        <div className="stack">
        <div className="grid two">
          <Field label={t("reports.name")} hint={t("reports.nameHint")}><input value={r.name} maxLength={200} onChange={(e) => set({ name: e.target.value })} /></Field>
          <Field label={t("reports.titleLabel")} hint={t("reports.titleHint")}><input value={r.title} maxLength={200} placeholder={r.name} onChange={(e) => set({ title: e.target.value })} /></Field>
          <Field label={t("reports.period")} hint={t("reports.periodHint")}>
            <select value={r.period} onChange={(e) => set({ period: e.target.value as Period })}>{PERIODS.map((p) => <option key={p} value={p}>{t(`reports.periods.${p}`)}</option>)}</select>
          </Field>
          <Field label={t("reports.language")} hint={t("reports.languageHint")}>
            <select value={r.language} onChange={(e) => set({ language: e.target.value as "en" | "nl" })}><option value="en">English</option><option value="nl">Nederlands</option></select>
          </Field>
        </div>
        <Field label={t("reports.intro")} hint={t("reports.introHint")}><textarea className="prose" rows={3} maxLength={5000} value={r.intro} onChange={(e) => set({ intro: e.target.value })} /></Field>
        </div>
      </Card>

      <Card title={t("reports.blocks")} subtitle={t("reports.blocksHint")} actions={
        <button type="button" className="btn secondary" onClick={() => setForm({ widget: newWidget("kpi"), index: -1 })}><Plus /> {t("reports.addBlock")}</button>
      }>
        {r.blocks.length ? (
          <ol className="block-list">
            {r.blocks.map((b, i) => (
              <li key={b.id}>
                <span className="badge">{t(`dashboards.type.${b.type}`)}</span>
                <span className="grow">{b.type === "text" ? (b.title || (b.text ?? "").slice(0, 80) || "…") : widgetTitle(b, t)}</span>
                <span className="muted small">{t(`dashboards.sizes.${b.size}`)}</span>
                <button type="button" className="btn ghost small" aria-label={t("dashboards.moveUp")} title={t("dashboards.moveUp")} disabled={i === 0} onClick={() => blocks((bs) => { [bs[i - 1], bs[i]] = [bs[i], bs[i - 1]]; return bs; })}><ArrowUp /></button>
                <button type="button" className="btn ghost small" aria-label={t("dashboards.moveDown")} title={t("dashboards.moveDown")} disabled={i === r.blocks.length - 1} onClick={() => blocks((bs) => { [bs[i + 1], bs[i]] = [bs[i], bs[i + 1]]; return bs; })}><ArrowDown /></button>
                <button type="button" className="btn ghost small" aria-label={t("common.edit")} title={t("common.edit")} onClick={() => setForm({ widget: b, index: i })}><Pencil /></button>
                <button type="button" className="btn ghost small" aria-label={t("common.delete")} title={t("common.delete")} onClick={() => blocks((bs) => bs.filter((_, n) => n !== i))}><Trash2 /></button>
              </li>
            ))}
          </ol>
        ) : <p className="muted">{t("reports.noBlocks")}</p>}
      </Card>

      {canSend ? (
        <Card title={t("reports.delivery")} subtitle={t("reports.deliveryHint")}>
          <div className="stack">
          <div className="grid three">
            <Field label={t("reports.schedule")}>
              <select value={r.schedule} onChange={(e) => set({ schedule: e.target.value as Schedule })}>{SCHEDULES.map((s) => <option key={s} value={s}>{t(`reports.schedules.${s}`)}</option>)}</select>
            </Field>
            {r.schedule === "weekly" && (
              <Field label={t("reports.weekday")}>
                <select value={r.weekday} onChange={(e) => set({ weekday: Number(e.target.value) })}>{[0, 1, 2, 3, 4, 5, 6].map((d) => <option key={d} value={d}>{t(`reports.weekdays.${d}`)}</option>)}</select>
              </Field>
            )}
            {r.schedule === "monthly" && (
              <Field label={t("reports.monthday")} hint={t("reports.monthdayHint")}>
                <input type="number" min={1} max={28} value={r.monthday} onChange={(e) => set({ monthday: Math.max(1, Math.min(28, Number(e.target.value) || 1)) })} />
              </Field>
            )}
            {r.schedule !== "none" && (
              <Field label={t("reports.time")} hint={t("reports.timeHint")}><input type="time" value={r.send_time} onChange={(e) => set({ send_time: e.target.value })} /></Field>
            )}
          </div>
          <Field label={t("reports.users")} hint={hasEditors ? t("reports.editorsOnly") : undefined}>
            <div className="chips">
              {people.filter((p) => !hasEditors || SEES_EDITORS.includes(p.role)).map((p) => (
                <button key={p.id} type="button" className="chip" aria-pressed={r.recipient_users.includes(p.id)} onClick={() => toggleUser(p.id)} title={p.email}>{p.name}</button>
              ))}
            </div>
          </Field>
          {!hasEditors && (
            <Field label={t("reports.emails")} hint={t("reports.emailsHint")}>
              <textarea className="prose" rows={2} value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="name@example.org, …" />
            </Field>
          )}
          <div className="grid two">
            <Field label={t("reports.linkDays")} hint={t("reports.linkDaysHint")}>
              <input type="number" min={1} max={365} value={r.link_days} onChange={(e) => set({ link_days: Math.max(1, Math.min(365, Number(e.target.value) || 30)) })} />
            </Field>
            <div className="stack">
              <Switch checked={r.attach_pdf} onChange={(v) => set({ attach_pdf: v })} label={t("reports.attachPdf")} />
              <Switch checked={r.enabled} onChange={(v) => set({ enabled: v })} label={t("reports.enabled")} />
            </div>
          </div>
          </div>
        </Card>
      ) : (
        <Alert kind="info">{t("reports.editorNote")}</Alert>
      )}

      {form && (
        <WidgetForm initial={form.widget} adding={form.index < 0} sources={sources} types={types} onClose={() => setForm(null)}
          onSave={(w) => { blocks((bs) => (form.index < 0 ? [...bs, w] : bs.map((x, n) => (n === form.index ? w : x)))); setForm(null); }} />
      )}
    </div>
  );
}

export default function ReportsPage() {
  const { t, i18n } = useTranslation();
  const { user, toast } = useApp();
  const canSend = !!user && SEES_EDITORS.includes(user.role);
  const list = useLoad(() => api.get<Report[]>("/api/reports"));
  const people = useLoad(() => (canSend ? api.get<Person[]>("/api/reports/recipients") : Promise.resolve([] as Person[])), [canSend]);
  const sources = useLoad(() => api.get<{ sources: SourceRef[] }>("/api/content/filters"));
  const [draft, setDraft] = useState<Report | null>(null);
  const [archive, setArchive] = useState<Report | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const lang = i18n.language;
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const generate = async (r: Report) => {
    const tab = window.open("", "_blank");
    setBusy(r.id);
    try {
      const run = await api.post<Run>(`/api/reports/${r.id}/generate`);
      if (tab) tab.location.href = run.link ?? `/reports/runs/${run.id}`;
      list.reload();
    } catch (e) { tab?.close(); fail(e); } finally { setBusy(null); }
  };
  const send = async (r: Report) => {
    if (!window.confirm(t("reports.confirmSend", { name: r.name }))) return;
    setBusy(r.id);
    try {
      const run = await api.post<Run>(`/api/reports/${r.id}/send`);
      toast("success", t("reports.sent", { count: run.recipients.length }));
      list.reload();
    } catch (e) { fail(e); list.reload(); } finally { setBusy(null); }
  };
  const remove = async (r: Report) => {
    if (!window.confirm(t("reports.confirmDelete", { name: r.name }))) return;
    try { await api.del(`/api/reports/${r.id}`); list.reload(); } catch (e) { fail(e); }
  };
  const when = (r: Report) => {
    if (r.schedule === "none") return t("reports.onDemand");
    const day = r.schedule === "weekly" ? t(`reports.weekdays.${r.weekday}`) : r.schedule === "monthly" ? t("reports.onDay", { day: r.monthday }) : "";
    return t(`reports.when.${r.schedule}`, { day, time: r.send_time });
  };

  if (draft) {
    return (
      <div className="page">
        <PageHead help="reports" title={t("reports.title")} subtitle={t("reports.subtitle")} />
        <Editor initial={draft} people={people.data ?? []} sources={sources.data?.sources ?? []} canSend={canSend}
          onClose={() => setDraft(null)} onSaved={() => { setDraft(null); list.reload(); }} />
      </div>
    );
  }

  return (
    <div className="page">
      <PageHead help="reports" title={t("reports.title")} subtitle={t("reports.subtitle")}
        actions={<button type="button" className="btn" onClick={() => setDraft(blank(lang === "nl" ? "nl" : "en"))}><Plus /> {t("reports.new")}</button>} />
      {list.error && <Alert kind="error">{errorText(list.error)}</Alert>}
      {list.data && !list.data.length && (
        <Card><div className="empty"><FileText /><h2>{t("reports.noneTitle")}</h2><p>{t("reports.noneText")}</p>
          <button type="button" className="btn" onClick={() => setDraft(blank(lang === "nl" ? "nl" : "en"))}><Plus /> {t("reports.new")}</button></div></Card>
      )}
      <div className="report-list">
        {list.data?.map((r) => (
          <Card key={r.id} title={r.name} subtitle={`${t(`reports.periods.${r.period}`)} · ${when(r)}`} actions={
            <div className="row">
              <button type="button" className="btn ghost small" onClick={() => setArchive(r)}><History /> {t("reports.archive")}</button>
              <button type="button" className="btn ghost small" onClick={() => setDraft(r)}><Pencil /> {t("common.edit")}</button>
              <button type="button" className="btn ghost small" aria-label={t("common.delete")} title={t("common.delete")} onClick={() => remove(r)}><Trash2 /></button>
            </div>
          }>
            <div className="report-row">
              <div className="grow small">
                {r.schedule !== "none" && (r.enabled && r.next_run_at
                  ? <div><Clock size={14} /> {t("reports.nextRun", { date: new Date(r.next_run_at).toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" }) })}</div>
                  : <div className="muted">{t("reports.paused")}</div>)}
                {r.last_run ? (
                  <div className="muted">
                    {t("reports.lastRun", { date: new Date(r.last_run.created_at).toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" }) })}{" · "}
                    <span className={r.last_run.status === "failed" ? "down" : undefined}>{t(`reports.statuses.${r.last_run.status}`)}</span>
                    {r.last_run.error && ` · ${r.last_run.error}`}
                  </div>
                ) : <div className="muted">{t("reports.noRuns")}</div>}
                <div className="muted">{t("reports.blockCount", { count: r.blocks.length })}{r.recipient_users.length + r.recipient_emails.length > 0 && ` · ${t("reports.recipientCount", { count: r.recipient_users.length + r.recipient_emails.length })}`}</div>
              </div>
              <button type="button" className="btn secondary" disabled={busy === r.id} onClick={() => generate(r)}><Zap /> {t("reports.generate")}</button>
              {r.can_send && <button type="button" className="btn" disabled={busy === r.id} onClick={() => send(r)}><Send /> {t("reports.sendNow")}</button>}
            </div>
          </Card>
        ))}
      </div>
      {archive && <Archive report={archive} onClose={() => setArchive(null)} />}
    </div>
  );
}
