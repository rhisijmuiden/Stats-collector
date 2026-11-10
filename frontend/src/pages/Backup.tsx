import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { DatabaseBackup, Pencil, Plus, PlugZap, RotateCcw, Trash2 } from "lucide-react";
import { api, ApiError, type Job } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { formatBytes, formatDate } from "../lib/format";
import { Alert, Card, Field, Modal, PageHead, Switch, useLoad } from "../components/ui";
import { JobLog } from "./Info";

interface Target {
  id?: number; name: string; kind: "ftp" | "ftps" | "sftp"; host: string; port: number | null; username: string;
  auth_method: "password" | "key"; secret_set?: boolean; path: string; ftps_mode: "explicit" | "implicit";
  verify_tls: boolean; enabled: boolean;
}
interface Settings {
  schedule_enabled: boolean; full_every: "daily" | "weekly" | "monthly"; full_weekday: number;
  incremental_every_hours: number; time: string; retention_full: number; include_uploads: boolean;
  encryption_passphrase_set: boolean;
}
interface RecordRow { label: string; kind: "full" | "incr"; base_label: string | null; size_bytes: number; targets: string[]; app_version: string; created_at: string }
interface Manifest { label: string; kind: "full" | "incr"; base: string | null; created_at: string; app_version: string }

const EMPTY: Target = { name: "", kind: "sftp", host: "", port: null, username: "", auth_method: "password", path: "stats-collector", ftps_mode: "explicit", verify_tls: true, enabled: true };

export default function Backup() {
  const { t, i18n } = useTranslation();
  const { toast } = useApp();
  const targets = useLoad(() => api.get<Target[]>("/api/backup/targets"));
  const records = useLoad(() => api.get<RecordRow[]>("/api/backup/records"));
  const loaded = useLoad(() => api.get<Settings>("/api/settings/backup"));
  const [cfg, setCfg] = useState<Settings | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const [draft, setDraft] = useState<Target | null>(null);
  const [secret, setSecret] = useState("");
  const [job, setJob] = useState<{ id: number; purpose: "backup" | "test" | "restore" | "list"; targetId?: number } | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<number | "">("");
  const [remote, setRemote] = useState<Manifest[] | null>(null);
  const [restorePick, setRestorePick] = useState<Manifest | null>(null);
  const [confirmText, setConfirmText] = useState("");
  useEffect(() => { if (loaded.data) setCfg(loaded.data); }, [loaded.data]);

  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const saveSettings = async (e: FormEvent) => {
    e.preventDefault();
    if (!cfg) return;
    try {
      setCfg(await api.put<Settings>("/api/settings/backup", { ...cfg, encryption_passphrase: passphrase || undefined }));
      setPassphrase("");
      toast("success", t("common.saved"));
    } catch (err) { fail(err); }
  };

  const saveTarget = async (e: FormEvent) => {
    e.preventDefault();
    if (!draft) return;
    try {
      const body = { ...draft, secret: secret || undefined };
      if (draft.id) await api.put(`/api/backup/targets/${draft.id}`, body);
      else await api.post("/api/backup/targets", body);
      setDraft(null); setSecret("");
      targets.reload();
      toast("success", t("common.saved"));
    } catch (err) { fail(err); }
  };

  const enqueue = async (url: string, body: unknown, purpose: "backup" | "test" | "restore" | "list", targetId?: number) => {
    try {
      const j = await api.post<Job>(url, body);
      setJob({ id: j.id, purpose, targetId });
    } catch (err) { fail(err); }
  };

  const onJobDone = (j: Job) => {
    if (job?.purpose === "backup") records.reload();
    if (job?.purpose === "list" && j.status === "succeeded") setRemote((j.result.remote_backups as Manifest[]) ?? []);
    if (j.status === "succeeded" && job?.purpose !== "list") toast("success", t("jobs.succeeded"));
  };

  const weekdays = Array.from({ length: 7 }, (_, i) =>
    new Date(2024, 0, 1 + i).toLocaleDateString(i18n.language === "nl" ? "nl-NL" : "en-GB", { weekday: "long" }));

  return (
    <div className="page">
      <PageHead help="backup"
        title={t("backup.title")}
        subtitle={t("backup.subtitle")}
        actions={
          <>
            <button className="btn secondary" onClick={() => enqueue("/api/backup/run", { type: "incr" }, "backup")}>{t("backup.runIncr")}</button>
            <button className="btn" onClick={() => enqueue("/api/backup/run", { type: "full" }, "backup")}><DatabaseBackup /> {t("backup.runFull")}</button>
          </>
        }
      />

      {job && <Card title={t(`backup.jobTitle.${job.purpose}`)} actions={<button className="btn ghost" onClick={() => setJob(null)}>{t("common.close")}</button>}><JobLog key={job.id} jobId={job.id} onDone={onJobDone} /></Card>}

      <Card title={t("backup.targets")} subtitle={t("backup.targetsIntro")} actions={<button className="btn secondary" onClick={() => { setDraft({ ...EMPTY }); setSecret(""); }}><Plus /> {t("backup.addTarget")}</button>}>
        {targets.data?.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>{t("backup.name")}</th><th>{t("backup.protocol")}</th><th>{t("backup.location")}</th><th>{t("backup.state")}</th><th /></tr></thead>
            <tbody>
              {targets.data.map((tg) => (
                <tr key={tg.id}>
                  <td><b>{tg.name}</b></td>
                  <td>{t(`backup.kinds.${tg.kind}`)}</td>
                  <td><code>{tg.username}@{tg.host}{tg.port ? `:${tg.port}` : ""}/{tg.path}</code></td>
                  <td>{tg.enabled ? <span className="badge good">{t("backup.enabled")}</span> : <span className="badge">{t("backup.disabled")}</span>}</td>
                  <td><div className="row end" style={{ flexWrap: "nowrap" }}>
                    <button className="btn ghost" onClick={() => enqueue(`/api/backup/targets/${tg.id}/test`, {}, "test", tg.id)}><PlugZap /> {t("backup.test")}</button>
                    <button className="btn ghost" aria-label={t("common.edit")} onClick={() => { setDraft(tg); setSecret(""); }}><Pencil /></button>
                    <button className="btn ghost" aria-label={t("common.delete")} onClick={async () => { if (window.confirm(t("backup.confirmDeleteTarget"))) { await api.del(`/api/backup/targets/${tg.id}`).catch(fail); targets.reload(); } }}><Trash2 /></button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        ) : <Alert kind="warning">{t("backup.noTargets")}</Alert>}
      </Card>

      {cfg && (
        <form onSubmit={saveSettings}>
          <Card title={t("backup.schedule")} actions={<button className="btn">{t("common.save")}</button>}>
            <div className="stack">
              <Switch checked={cfg.schedule_enabled} onChange={(v) => setCfg({ ...cfg, schedule_enabled: v })} label={t("backup.scheduleEnabled")} />
              <div className="grid three">
                <Field label={t("backup.fullEvery")}>
                  <select value={cfg.full_every} onChange={(e) => setCfg({ ...cfg, full_every: e.target.value as Settings["full_every"] })}>
                    {(["daily", "weekly", "monthly"] as const).map((f) => <option key={f} value={f}>{t(`backup.every.${f}`)}</option>)}
                  </select>
                </Field>
                {cfg.full_every === "weekly" && (
                  <Field label={t("backup.weekday")}>
                    <select value={cfg.full_weekday} onChange={(e) => setCfg({ ...cfg, full_weekday: Number(e.target.value) })}>
                      {weekdays.map((d, i) => <option key={i} value={i}>{d}</option>)}
                    </select>
                  </Field>
                )}
                <Field label={t("backup.time")}><input type="time" value={cfg.time} onChange={(e) => setCfg({ ...cfg, time: e.target.value })} /></Field>
                <Field label={t("backup.incrEvery")} hint={t("backup.hours")}><input type="number" min={1} max={168} value={cfg.incremental_every_hours} onChange={(e) => setCfg({ ...cfg, incremental_every_hours: Number(e.target.value) })} /></Field>
                <Field label={t("backup.retention")} hint={t("backup.retentionHint")}><input type="number" min={1} max={52} value={cfg.retention_full} onChange={(e) => setCfg({ ...cfg, retention_full: Number(e.target.value) })} /></Field>
              </div>
              <Switch checked={cfg.include_uploads} onChange={(v) => setCfg({ ...cfg, include_uploads: v })} label={t("backup.includeFiles")} />
              <Field label={t("backup.passphrase")} hint={cfg.encryption_passphrase_set ? t("backup.passphraseSet") : t("backup.passphraseHint")}>
                <input type="password" autoComplete="new-password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} placeholder={cfg.encryption_passphrase_set ? "••••••••" : ""} />
              </Field>
              {!cfg.encryption_passphrase_set && <Alert kind="warning">{t("backup.noEncryption")}</Alert>}
            </div>
          </Card>
        </form>
      )}

      <Card title={t("backup.history")}>
        {records.data?.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>{t("backup.when")}</th><th>{t("backup.type")}</th><th>{t("backup.size")}</th><th>{t("backup.uploadedTo")}</th><th>{t("info.version")}</th></tr></thead>
            <tbody>{records.data.map((r) => (
              <tr key={r.label}>
                <td>{formatDate(r.created_at, i18n.language)}</td>
                <td><span className={`badge ${r.kind === "full" ? "accent" : ""}`}>{t(`backup.types.${r.kind}`)}</span></td>
                <td>{formatBytes(r.size_bytes)}</td>
                <td>{r.targets.join(", ") || <span className="badge warning">{t("backup.localOnly")}</span>}</td>
                <td>{r.app_version}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <p className="muted">{t("backup.noBackups")}</p>}
      </Card>

      <Card title={t("backup.restore")} subtitle={t("backup.restoreIntro")}>
        <div className="stack">
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <select value={restoreTarget} onChange={(e) => { setRestoreTarget(e.target.value ? Number(e.target.value) : ""); setRemote(null); }}>
              <option value="">{t("backup.chooseTarget")}</option>
              {targets.data?.map((tg) => <option key={tg.id} value={tg.id}>{tg.name}</option>)}
            </select>
            <button className="btn secondary" disabled={!restoreTarget} onClick={() => enqueue(`/api/backup/targets/${restoreTarget}/test`, {}, "list", Number(restoreTarget))}>{t("backup.loadRemote")}</button>
          </div>
          {remote && remote.length === 0 && <p className="muted">{t("backup.remoteEmpty")}</p>}
          {remote && remote.length > 0 && (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("backup.when")}</th><th>{t("backup.type")}</th><th>{t("info.version")}</th><th /></tr></thead>
              <tbody>{[...remote].reverse().map((m) => (
                <tr key={m.label}>
                  <td>{formatDate(m.created_at, i18n.language)}</td>
                  <td><span className={`badge ${m.kind === "full" ? "accent" : ""}`}>{t(`backup.types.${m.kind}`)}</span></td>
                  <td>{m.app_version}</td>
                  <td><div className="row end"><button className="btn secondary" onClick={() => { setRestorePick(m); setConfirmText(""); }}><RotateCcw /> {t("backup.restoreThis")}</button></div></td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      </Card>

      {draft && (
        <Modal title={draft.id ? t("backup.editTarget") : t("backup.addTarget")} onClose={() => setDraft(null)}>
          <form className="stack" onSubmit={saveTarget}>
            <Field label={t("backup.name")}><input required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="NAS" /></Field>
            <Field label={t("backup.protocol")}>
              <div className="seg">
                {(["sftp", "ftps", "ftp"] as const).map((k) => <button key={k} type="button" aria-pressed={draft.kind === k} onClick={() => setDraft({ ...draft, kind: k })}>{t(`backup.kinds.${k}`)}</button>)}
              </div>
            </Field>
            {draft.kind === "ftp" && <Alert kind="warning">{t("backup.ftpWarning")}</Alert>}
            <div className="grid two">
              <Field label={t("backup.host")}><input required value={draft.host} onChange={(e) => setDraft({ ...draft, host: e.target.value })} /></Field>
              <Field label={t("backup.port")} hint={t("backup.portDefault", { port: draft.kind === "sftp" ? 22 : 21 })}><input type="number" value={draft.port ?? ""} onChange={(e) => setDraft({ ...draft, port: e.target.value ? Number(e.target.value) : null })} /></Field>
              <Field label={t("email.username")}><input required value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} /></Field>
              <Field label={t("backup.path")}><input value={draft.path} onChange={(e) => setDraft({ ...draft, path: e.target.value })} /></Field>
            </div>
            {draft.kind === "sftp" && (
              <div className="seg">
                {(["password", "key"] as const).map((a) => <button key={a} type="button" aria-pressed={draft.auth_method === a} onClick={() => setDraft({ ...draft, auth_method: a })}>{t(`backup.auth.${a}`)}</button>)}
              </div>
            )}
            <Field label={draft.kind === "sftp" && draft.auth_method === "key" ? t("backup.privateKey") : t("email.password")} hint={draft.secret_set ? t("common.secretKept") : undefined}>
              {draft.kind === "sftp" && draft.auth_method === "key"
                ? <textarea value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" />
                : <input type="password" autoComplete="new-password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={draft.secret_set ? "••••••••" : ""} />}
            </Field>
            {draft.kind === "ftps" && (
              <div className="grid two">
                <Field label={t("backup.ftpsMode")}>
                  <select value={draft.ftps_mode} onChange={(e) => setDraft({ ...draft, ftps_mode: e.target.value as Target["ftps_mode"] })}>
                    <option value="explicit">{t("backup.explicit")}</option><option value="implicit">{t("backup.implicit")}</option>
                  </select>
                </Field>
                <Switch checked={draft.verify_tls} onChange={(v) => setDraft({ ...draft, verify_tls: v })} label={t("email.verifyTls")} />
              </div>
            )}
            <Switch checked={draft.enabled} onChange={(v) => setDraft({ ...draft, enabled: v })} label={t("backup.enabled")} />
            <div className="row end">
              <button type="button" className="btn secondary" onClick={() => setDraft(null)}>{t("common.cancel")}</button>
              <button className="btn">{t("common.save")}</button>
            </div>
          </form>
        </Modal>
      )}

      {restorePick && (
        <Modal title={t("backup.confirmRestoreTitle")} onClose={() => setRestorePick(null)}>
          <div className="stack">
            <Alert kind="warning">{t("backup.confirmRestoreText", { when: formatDate(restorePick.created_at, i18n.language) })}</Alert>
            <Field label={t("backup.typeRestore")}><input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder="RESTORE" /></Field>
            <div className="row end">
              <button className="btn secondary" onClick={() => setRestorePick(null)}>{t("common.cancel")}</button>
              <button className="btn danger" disabled={confirmText !== "RESTORE"} onClick={() => {
                enqueue("/api/backup/restore", { target_id: restoreTarget, label: restorePick.label, confirm: confirmText }, "restore");
                setRestorePick(null);
              }}>{t("backup.restoreNow")}</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
