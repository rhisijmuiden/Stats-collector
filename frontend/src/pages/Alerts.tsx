import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { BellRing, Mail, Pencil, Plus, Search, Send, Trash2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { formatDate } from "../lib/format";
import { Alert, Card, Field, Modal, PageHead, Switch, useLoad } from "../components/ui";
import { channel, fmt, ItemModal, kindIcon } from "./Content";

type Scope = "item" | "channel";
interface Rule {
  id: number; name: string; scope: Scope; source_ids: number[]; sources: { id: number; name: string; kind: string }[];
  factor: number; min_value: number; teams_webhook_set: boolean; emails: string[]; language: "en" | "nl";
  quiet_start: string; quiet_end: string; enabled: boolean; alerts_7d: number;
}
interface Event {
  id: number; rule: string | null; title: string; source: { id: number; name: string; kind: string } | null; item_id: number | null;
  measure: string; value: number; usual: number; factor: number | null; at: string; delivered: string[]; error: string;
}
interface Draft {
  id?: number; name: string; scope: Scope; source_ids: number[]; factor: string; min_value: string; teams_webhook: string;
  teams_set: boolean; emails: string; language: "en" | "nl"; quiet_start: string; quiet_end: string; enabled: boolean;
}

export default function AlertsPage() {
  const { t, i18n } = useTranslation();
  const { user, toast, theme } = useApp();
  const lang = i18n.language;
  const canEdit = user?.role === "admin" || user?.role === "editor_in_chief";
  const data = useLoad(() => api.get<{ rules: Rule[]; events: Event[] }>("/api/alerts"));
  const filters = useLoad(() => api.get<{ sources: { id: number; name: string; kind: string }[] }>("/api/content/filters"));
  const [draft, setDraft] = useState<Draft | null>(null);
  const [item, setItem] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const edit = (r?: Rule) => setDraft(r ? {
    id: r.id, name: r.name, scope: r.scope, source_ids: r.source_ids, factor: String(r.factor), min_value: String(r.min_value),
    teams_webhook: "", teams_set: r.teams_webhook_set, emails: r.emails.join(", "), language: r.language,
    quiet_start: r.quiet_start, quiet_end: r.quiet_end, enabled: r.enabled,
  } : {
    name: "", scope: "item", source_ids: [], factor: "3", min_value: "500", teams_webhook: "", teams_set: false, emails: "",
    language: (lang === "nl" ? "nl" : "en"), quiet_start: "23:00", quiet_end: "07:00", enabled: true,
  });
  const body = (d: Draft) => ({
    name: d.name, scope: d.scope, source_ids: d.source_ids, factor: Number(d.factor), min_value: Number(d.min_value),
    teams_webhook: d.teams_webhook.trim() || null, emails: d.emails.split(/[\s,;]+/).filter(Boolean), language: d.language,
    quiet_start: d.quiet_start, quiet_end: d.quiet_end, enabled: d.enabled,
  });
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      if (draft!.id) await api.put(`/api/alerts/${draft!.id}`, body(draft!)); else await api.post("/api/alerts", body(draft!));
      toast("success", t("common.saved"));
      setDraft(null);
      data.reload();
    } catch (err) { fail(err); }
  };
  const remove = async () => {
    if (!window.confirm(t("alerts.confirmDelete", { name: draft!.name }))) return;
    try { await api.del(`/api/alerts/${draft!.id}`); setDraft(null); data.reload(); } catch (err) { fail(err); }
  };
  const test = async (r: Rule) => {
    try {
      const res = await api.post<{ delivered: string[]; error: string }>(`/api/alerts/${r.id}/test`);
      if (res.delivered.length) toast("success", t("alerts.testSent", { to: res.delivered.map((d) => t(`alerts.via.${d}`)).join(", ") }));
      if (res.error) toast("error", res.error);
    } catch (err) { fail(err); }
  };
  const checkNow = async () => {
    setBusy(true);
    try {
      const res = await api.post<{ found: number }>("/api/alerts/check");
      toast("success", t("alerts.checked", { count: res.found }));
      data.reload();
    } catch (err) { fail(err); } finally { setBusy(false); }
  };
  const sources = filters.data?.sources ?? [];
  const toggle = (id: number) => setDraft({ ...draft!, source_ids: draft!.source_ids.includes(id) ? draft!.source_ids.filter((x) => x !== id) : [...draft!.source_ids, id] });

  return (
    <div className="page">
      <PageHead help="alerts" title={t("alerts.title")} subtitle={t("alerts.subtitle")}
        actions={canEdit && <>
          <button className="btn secondary" disabled={busy} onClick={checkNow}><Search /> {t("alerts.checkNow")}</button>
          <button className="btn" onClick={() => edit()}><Plus /> {t("alerts.add")}</button>
        </>} />
      {data.error && <Alert kind="error">{errorText(data.error)}</Alert>}
      {data.data && (data.data.rules.length ? (
        <div className="goal-cards">
          {data.data.rules.map((r) => (
            <section key={r.id} className={`card alert-rule${r.enabled ? "" : " off"}`}>
              <div className="row between">
                <h2>{r.name}</h2>
                <span className={`badge ${r.enabled ? "good" : ""}`}>{t(r.enabled ? "alerts.on" : "alerts.off")}</span>
              </div>
              <div className="muted small">{t(`alerts.scope.${r.scope}`)} · {r.sources.length ? r.sources.map((s) => s.name).join(", ") : t("alerts.allChannels")}</div>
              <div className="alert-rule-facts">
                <div><b>{fmt(r.factor, lang, 1)}×</b><span>{t("alerts.factorShort")}</span></div>
                <div><b>{fmt(r.min_value, lang)}</b><span>{t("alerts.minShort")}</span></div>
                <div><b>{r.alerts_7d}</b><span>{t("alerts.last7")}</span></div>
              </div>
              <div className="row small muted">
                {r.teams_webhook_set && <span className="badge accent">Teams</span>}
                {r.emails.length > 0 && <span className="badge"><Mail size={12} /> {r.emails.length}</span>}
                {r.quiet_start && r.quiet_end && <span>{t("alerts.quietShort", { start: r.quiet_start, end: r.quiet_end })}</span>}
              </div>
              {canEdit && (
                <div className="row end">
                  <button className="btn ghost" onClick={() => test(r)}><Send /> {t("alerts.test")}</button>
                  <button className="btn secondary" onClick={() => edit(r)}><Pencil /> {t("common.edit")}</button>
                </div>
              )}
            </section>
          ))}
        </div>
      ) : <Card><div className="empty"><BellRing /><h2>{t("alerts.noneTitle")}</h2><p>{t(canEdit ? "alerts.noneText" : "alerts.noneTextReader")}</p></div></Card>)}

      {data.data && (
        <Card title={t("alerts.recent")} subtitle={t("alerts.recentHint")}>
          {data.data.events.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("alerts.when")}</th><th>{t("alerts.what")}</th><th className="num">{t("alerts.value")}</th><th className="num">{t("alerts.usual")}</th><th className="num">{t("alerts.factor")}</th><th>{t("alerts.sent")}</th></tr></thead>
              <tbody>{data.data.events.map((e) => (
                <tr key={e.id} className={e.item_id ? "clickable" : undefined} onClick={e.item_id ? () => setItem(e.item_id) : undefined}>
                  <td className="nowrap">{formatDate(e.at, lang)}</td>
                  <td>
                    <b>{e.title}</b>
                    {e.source && <div className="muted small"><span className="source-kind"><i style={{ background: theme?.channels?.[channel(e.source.kind)] }} />{kindIcon(e.source.kind)} {e.source.name}{e.rule ? ` · ${e.rule}` : ""}</span></div>}
                  </td>
                  <td className="num">{fmt(e.value, lang)} <span className="muted small">{t(`alerts.measure.${e.measure}`, { defaultValue: e.measure })}</span></td>
                  <td className="num">{fmt(e.usual, lang)}</td>
                  <td className="num"><span className="badge warning">{e.factor != null ? `${fmt(e.factor, lang, 1)}×` : "–"}</span></td>
                  <td className="small">{e.delivered.length ? e.delivered.map((d) => t(`alerts.via.${d}`)).join(", ") : <span className="muted">–</span>}{e.error && <div className="critical-text">{e.error}</div>}</td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <p className="muted small">{t("alerts.noEvents")}</p>}
        </Card>
      )}

      {item != null && <ItemModal id={item} range="7d" onClose={() => setItem(null)} />}
      {draft && (
        <Modal title={draft.id ? t("alerts.edit") : t("alerts.add")} onClose={() => setDraft(null)}>
          <form className="stack" onSubmit={save}>
            <Field label={t("alerts.name")}><input required maxLength={200} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder={t("alerts.namePlaceholder")} /></Field>
            <Field label={t("alerts.scopeLabel")} hint={t(`alerts.scopeHint.${draft.scope}`)}>
              <div className="seg">{(["item", "channel"] as const).map((s) => <button key={s} type="button" aria-pressed={draft.scope === s} onClick={() => setDraft({ ...draft, scope: s })}>{t(`alerts.scope.${s}`)}</button>)}</div>
            </Field>
            <div className="grid two">
              <Field label={t("alerts.factor")} hint={t("alerts.factorHint")}><input required type="number" min={1.2} max={100} step={0.1} value={draft.factor} onChange={(e) => setDraft({ ...draft, factor: e.target.value })} /></Field>
              <Field label={t("alerts.min")} hint={t("alerts.minHint")}><input required type="number" min={0} step={1} value={draft.min_value} onChange={(e) => setDraft({ ...draft, min_value: e.target.value })} /></Field>
            </div>
            <Field label={t("alerts.channels")} hint={t("alerts.channelsHint")}>
              <div className="choice-list">{sources.map((s) => (
                <button key={s.id} type="button" className={`btn ${draft.source_ids.includes(s.id) ? "" : "secondary"}`} aria-pressed={draft.source_ids.includes(s.id)} onClick={() => toggle(s.id)}>{s.name}</button>
              ))}</div>
            </Field>
            <Field label={t("alerts.teams")} hint={<>{t("alerts.teamsHint")}{draft.teams_set && <> {t("common.secretKept")}</>}</>}>
              <input type="url" value={draft.teams_webhook} onChange={(e) => setDraft({ ...draft, teams_webhook: e.target.value })} placeholder="https://…webhook.office.com/…" />
            </Field>
            {draft.teams_set && <Switch checked={draft.teams_webhook === "-"} onChange={(v) => setDraft({ ...draft, teams_webhook: v ? "-" : "" })} label={t("alerts.teamsRemove")} />}
            <Field label={t("alerts.emails")} hint={t("alerts.emailsHint")}><input value={draft.emails} onChange={(e) => setDraft({ ...draft, emails: e.target.value })} placeholder="desk@example.org" /></Field>
            <div className="grid two">
              <Field label={t("alerts.language")}>
                <select value={draft.language} onChange={(e) => setDraft({ ...draft, language: e.target.value as "en" | "nl" })}>
                  <option value="en">English</option><option value="nl">Nederlands</option>
                </select>
              </Field>
              <Field label={t("alerts.quiet")} hint={t("alerts.quietHint")}>
                <div className="row"><input type="time" value={draft.quiet_start} onChange={(e) => setDraft({ ...draft, quiet_start: e.target.value })} aria-label={t("alerts.quietFrom")} /><span className="muted">–</span><input type="time" value={draft.quiet_end} onChange={(e) => setDraft({ ...draft, quiet_end: e.target.value })} aria-label={t("alerts.quietTo")} /></div>
              </Field>
            </div>
            <Switch checked={draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} label={t("alerts.enabled")} />
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
