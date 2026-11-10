import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Download, Globe, KeyRound, Pencil, PlugZap, Plus, Radio, RefreshCw, Trash2, Tv } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { formatDate } from "../lib/format";
import { Alert, Card, Field, Modal, PageHead, Switch, useLoad } from "../components/ui";

type Kind = "icecast" | "owncast" | "wordpress";
interface Source {
  id?: number; kind: Kind; name: string; url: string; mounts: string[]; admin_user: string; admin_password_set?: boolean;
  verify_tls: boolean; poll_seconds: number; enabled: boolean; webhook_url?: string | null; items?: number;
  last_poll_at?: string | null; last_ok_at?: string | null; last_error?: string | null; last_error_at?: string | null;
  site_key?: string | null; ingest_url?: string; secret?: string | null; site_name?: string | null; plugin_version?: string | null;
}
interface TestResult { ok: boolean; error?: string; online?: boolean; info?: Record<string, unknown>; items?: { id: string; title: string; value: number; online: boolean }[] }

const EMPTY: Source = { kind: "icecast", name: "", url: "", mounts: [], admin_user: "admin", verify_tls: true, poll_seconds: 30, enabled: true };

export default function Sources() {
  const { t, i18n } = useTranslation();
  const { toast, theme } = useApp();
  const list = useLoad(() => api.get<Source[]>("/api/sources"));
  const [draft, setDraft] = useState<Source | null>(null);
  const [mountsText, setMountsText] = useState("");
  const [password, setPassword] = useState("");
  const [test, setTest] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const open = (s: Source) => { setDraft(s); setMountsText(s.mounts.join(", ")); setPassword(""); setTest(null); };
  const body = () => ({
    ...draft!, mounts: mountsText.split(/[\s,]+/).filter(Boolean), admin_password: password || (draft!.id ? null : ""),
  });

  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      if (draft!.id) { await api.put(`/api/sources/${draft!.id}`, body()); setDraft(null); }
      else {
        const created = await api.post<Source>("/api/sources", body());
        // A new website keeps the dialog open: the secret is shown only now.
        if (created.kind === "wordpress") setDraft(created); else setDraft(null);
      }
      toast("success", t("common.saved"));
      list.reload();
    } catch (err) { fail(err); }
  };

  const runTest = async () => {
    setBusy(true);
    setTest(null);
    try { setTest(await api.post<TestResult>("/api/sources/test", { ...body(), id: draft!.id ?? null })); }
    catch (err) { fail(err); }
    finally { setBusy(false); }
  };

  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); toast("success", t("sources.copied")); } catch { /* ignore */ }
  };

  const icon = (k: Kind) => (k === "owncast" ? <Tv size={16} /> : k === "wordpress" ? <Globe size={16} /> : <Radio size={16} />);
  const web = draft?.kind === "wordpress";
  const renewKey = async () => {
    if (!window.confirm(t("sources.renewKeyConfirm"))) return;
    try { setDraft(await api.post<Source>(`/api/sources/${draft!.id}/rotate-key`)); list.reload(); }
    catch (err) { fail(err); }
  };
  return (
    <div className="page">
      <PageHead help="owncast-icecast" title={t("sources.title")} subtitle={t("sources.subtitle")}
        actions={<button className="btn" onClick={() => open({ ...EMPTY })}><Plus /> {t("sources.add")}</button>} />

      <Card>
        {list.data?.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>{t("sources.name")}</th><th>{t("sources.kind")}</th><th>{t("sources.url")}</th><th>{t("sources.status")}</th><th className="num">{t("sources.items")}</th><th /></tr></thead>
            <tbody>
              {list.data.map((s) => (
                <tr key={s.id}>
                  <td><b>{s.name}</b></td>
                  <td><span className="source-kind"><i style={{ background: theme?.channels?.[s.kind === "wordpress" ? "website" : s.kind] }} />{icon(s.kind)} {t(`sources.kinds.${s.kind}`)}</span></td>
                  <td><code>{s.url}</code>{s.kind === "icecast" && s.mounts.length > 0 && <div className="muted small">{s.mounts.join(", ")}</div>}{s.kind === "wordpress" && s.plugin_version && <div className="muted small">{t("sources.pluginVersion", { version: s.plugin_version })}</div>}</td>
                  <td>
                    {!s.enabled ? <span className="badge">{t("sources.disabled")}</span>
                      : s.last_error ? <span className="badge critical" title={formatDate(s.last_error_at, i18n.language)}>{errorText(s.last_error)}</span>
                      : s.last_ok_at ? <span className="badge good" title={formatDate(s.last_ok_at, i18n.language)}>{t("sources.ok")}</span>
                      : <span className="badge">{t("sources.waiting")}</span>}
                  </td>
                  <td className="num">{s.items}</td>
                  <td><div className="row end" style={{ flexWrap: "nowrap" }}>
                    {s.kind !== "wordpress" && <button className="btn ghost" title={t("sources.pollNow")} aria-label={t("sources.pollNow")} onClick={async () => { await api.post(`/api/sources/${s.id}/poll`).catch(fail); list.reload(); }}><RefreshCw /></button>}
                    <button className="btn ghost" aria-label={t("common.edit")} onClick={() => open(s)}><Pencil /></button>
                    <button className="btn ghost" aria-label={t("common.delete")} onClick={async () => { if (window.confirm(t("sources.confirmDelete", { name: s.name }))) { await api.del(`/api/sources/${s.id}`).catch(fail); list.reload(); } }}><Trash2 /></button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        ) : list.data ? <Alert kind="info">{t("sources.none")}</Alert> : null}
      </Card>

      {draft && (
        <Modal title={draft.id ? t("sources.edit") : t("sources.add")} onClose={() => setDraft(null)}>
          <form className="stack" onSubmit={save}>
            {!draft.id && (
              <Field label={t("sources.kind")}>
                <div className="seg">
                  {(["icecast", "owncast", "wordpress"] as const).map((k) => (
                    <button key={k} type="button" aria-pressed={draft.kind === k} onClick={() => { setDraft({ ...draft, kind: k }); setTest(null); }}>{icon(k)} {t(`sources.kinds.${k}`)}</button>
                  ))}
                </div>
              </Field>
            )}
            <div className="grid two">
              <Field label={t("sources.name")}><input required maxLength={200} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder={draft.kind === "icecast" ? "Radio" : web ? "Website" : "TV"} /></Field>
              <Field label={t("sources.url")} hint={t(`sources.urlHint.${draft.kind}`)}><input required type="url" value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} placeholder={draft.kind === "icecast" ? "https://radio.example.org:8000" : web ? "https://www.example.org" : "https://live.example.org"} /></Field>
            </div>
            {draft.kind === "icecast" && (
              <Field label={t("sources.mounts")} hint={t("sources.mountsHint")}><input value={mountsText} onChange={(e) => setMountsText(e.target.value)} placeholder="/live, /jazz" /></Field>
            )}
            {!web && <div className="grid two">
              {draft.kind === "icecast" && <Field label={t("sources.adminUser")}><input value={draft.admin_user} onChange={(e) => setDraft({ ...draft, admin_user: e.target.value })} /></Field>}
              <Field label={t("sources.adminPassword")} hint={draft.admin_password_set ? t("common.secretKept") : t(`sources.passwordHint.${draft.kind}`)}>
                <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={draft.admin_password_set ? "••••••••" : ""} />
              </Field>
            </div>}
            {web ? <Switch checked={draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} label={t("sources.enabled")} /> : <div className="grid two">
              <Field label={t("sources.pollSeconds")} hint={t("sources.pollHint")}><input type="number" min={10} max={3600} value={draft.poll_seconds} onChange={(e) => setDraft({ ...draft, poll_seconds: Number(e.target.value) })} /></Field>
              <div className="stack">
                <Switch checked={draft.verify_tls} onChange={(v) => setDraft({ ...draft, verify_tls: v })} label={t("email.verifyTls")} />
                <Switch checked={draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} label={t("sources.enabled")} />
              </div>
            </div>}
            {web && (draft.id ? (
              <div className="stack">
                <Alert kind="info">{t("sources.wpSteps")}</Alert>
                <Field label={t("sources.ingestUrl")}>
                  <div className="copy-field"><input readOnly value={draft.ingest_url ?? ""} onFocus={(e) => e.target.select()} /><button type="button" className="btn secondary" onClick={() => copy(draft.ingest_url ?? "")}><Copy /> {t("sources.copy")}</button></div>
                </Field>
                <Field label={t("sources.siteKey")}>
                  <div className="copy-field"><input readOnly value={draft.site_key ?? ""} onFocus={(e) => e.target.select()} /><button type="button" className="btn secondary" onClick={() => copy(draft.site_key ?? "")}><Copy /> {t("sources.copy")}</button></div>
                </Field>
                <Field label={t("sources.siteSecret")} hint={draft.secret ? t("sources.secretOnce") : t("sources.secretHidden")}>
                  {draft.secret ? (
                    <div className="copy-field"><input readOnly value={draft.secret} onFocus={(e) => e.target.select()} /><button type="button" className="btn secondary" onClick={() => copy(draft.secret!)}><Copy /> {t("sources.copy")}</button></div>
                  ) : <button type="button" className="btn secondary" onClick={renewKey}><KeyRound /> {t("sources.renewKey")}</button>}
                </Field>
              </div>
            ) : <Alert kind="info">{t("sources.wpAfterSave")}</Alert>)}
            {draft.kind === "owncast" && (
              <Field label={t("sources.webhook")} hint={draft.webhook_url ? t("sources.webhookHint") : t("sources.webhookAfterSave")}>
                {draft.webhook_url ? (
                  <div className="copy-field">
                    <input readOnly value={draft.webhook_url} onFocus={(e) => e.target.select()} />
                    <button type="button" className="btn secondary" onClick={() => copy(draft.webhook_url!)}><Copy /> {t("sources.copy")}</button>
                    <button type="button" className="btn ghost" onClick={async () => {
                      if (!window.confirm(t("sources.renewConfirm"))) return;
                      try { const s = await api.post<Source>(`/api/sources/${draft.id}/rotate-webhook`); setDraft({ ...draft, webhook_url: s.webhook_url }); }
                      catch (err) { fail(err); }
                    }}>{t("sources.renew")}</button>
                  </div>
                ) : <span className="muted small">—</span>}
              </Field>
            )}
            {test && (test.ok ? (
              <Alert kind="success">
                <b>{t("sources.testOk")}</b> {String(test.info?.server ?? "")} {test.info?.version ? `(${String(test.info.version)})` : ""}
                {test.items?.length ? (
                  <ul className="items-list">{test.items.map((i) => <li key={i.id}><span>{i.title} <span className="muted">{i.id}</span></span><b>{i.online ? i.value : t("dashboard.offline")}</b></li>)}</ul>
                ) : <div>{test.online ? "" : t("sources.testOffline")}</div>}
                {draft.kind === "icecast" && Array.isArray(test.info?.mounts_found) && <div className="muted small">{t("sources.mountsFound")}: {(test.info!.mounts_found as string[]).join(", ") || "—"}</div>}
              </Alert>
            ) : <Alert kind="error">{t("sources.testFailed")}: {errorText(test.error ?? "")}</Alert>)}
            <div className="row end">
              {web && <a className="btn secondary" href="/api/sources/wordpress-plugin.zip" download><Download /> {t("sources.downloadPlugin")}</a>}
              {!web && <button type="button" className="btn secondary" disabled={busy || !draft.url} onClick={runTest}><PlugZap /> {busy ? t("sources.testing") : t("sources.test")}</button>}
              <button type="button" className="btn secondary" onClick={() => setDraft(null)}>{t("common.cancel")}</button>
              <button className="btn">{t("common.save")}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
