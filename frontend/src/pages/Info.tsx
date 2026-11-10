import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowDownCircle, ExternalLink, FlaskConical, RefreshCw, Rocket } from "lucide-react";
import { api, ApiError, type Job, type NoteSection, type Release } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { formatBytes, formatDate } from "../lib/format";
import { Alert, Card, Modal, PageHead, Tabs, useLoad } from "../components/ui";

interface InfoData {
  build: { version: string; commit: string | null; channel: string | null; built_at: string | null };
  channel: "production" | "test";
  python: string;
  database?: string | null;
  os?: string;
  disk?: { total: number; free: number } | null;
  jobs?: Job[];
}

interface ReleasesData {
  channel: "production" | "test";
  check: { update_available: boolean; latest: Release | null; channel_mismatch: boolean };
  releases: Release[];
}

const SECTIONS: NoteSection[] = ["added", "changed", "removed", "fixed"];

function ReleaseNotes({ release }: { release: Release }) {
  const { t, i18n } = useTranslation();
  const notes = release.notes[i18n.language] ?? release.notes.en;
  const available = SECTIONS.filter((s) => notes?.[s]?.length);
  const [tab, setTab] = useState<NoteSection>(available[0] ?? "added");
  if (!notes || available.length === 0) return <p className="muted small">{t("info.noNotes")}</p>;
  return (
    <>
      <Tabs
        tabs={SECTIONS.map((s) => ({ id: s, label: t(`info.sections.${s}`), count: notes[s]?.length ?? 0 }))}
        value={tab}
        onChange={setTab}
      />
      {notes[tab]?.length ? (
        <ul>{notes[tab].map((line, i) => <li key={i}>{line}</li>)}</ul>
      ) : (
        <p className="muted small" style={{ marginTop: 10 }}>{t("info.nothingInSection")}</p>
      )}
    </>
  );
}

export function JobLog({ jobId, onDone }: { jobId: number; onDone?: (job: Job) => void }) {
  const { t } = useTranslation();
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    let stop = false;
    let failures = 0;
    const poll = async () => {
      try {
        const j = await api.get<Job>(`/api/system/jobs/${jobId}`);
        failures = 0;
        if (stop) return;
        setJob(j);
        if (j.status === "succeeded" || j.status === "failed") return onDone?.(j);
      } catch {
        failures++; // expected while the web service restarts during an update
        if (failures > 60) return;
      }
      setTimeout(poll, 2000);
    };
    poll();
    return () => {
      stop = true;
    };
  }, [jobId, onDone]);
  return (
    <div className="stack">
      <div className="row">
        <b>{t(`jobs.kinds.${job?.kind ?? "update"}`)}</b>
        <span className={`badge ${job?.status === "succeeded" ? "good" : job?.status === "failed" ? "critical" : "warning"}`}>
          {t(`jobs.status.${job?.status ?? "queued"}`)}
        </span>
      </div>
      {job?.status === "queued" && <p className="muted small">{t("jobs.queuedHint")}</p>}
      <pre className="log">{job?.log || "…"}</pre>
    </div>
  );
}

export default function InfoPage() {
  const { t, i18n } = useTranslation();
  const { user, toast } = useApp();
  const isAdmin = user?.role === "admin";
  const info = useLoad(() => api.get<InfoData>("/api/system/info"));
  const [force, setForce] = useState(false);
  const rel = useLoad(() => api.get<ReleasesData>(`/api/system/releases${force ? "?force=true" : ""}`), [force]);
  const [filter, setFilter] = useState<"all" | "production" | "test">("all");
  const [confirm, setConfirm] = useState<Release | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);

  const channel = info.data?.channel ?? rel.data?.channel ?? "test";
  const current = info.data?.build.version;
  const releases = useMemo(
    () => (rel.data?.releases ?? []).filter((r) => filter === "all" || r.channel === filter),
    [rel.data, filter],
  );

  const check = async () => {
    setChecking(true);
    setForce(true);
    rel.reload();
    setTimeout(() => setChecking(false), 800);
  };

  const switchChannel = async (c: "production" | "test") => {
    try {
      await api.put("/api/system/channel", { channel: c });
      toast("success", t("info.channelSaved", { channel: t(`info.channels.${c}`) }));
      info.reload();
      rel.reload();
    } catch (e) {
      toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));
    }
  };

  const install = async (r: Release) => {
    setConfirm(null);
    try {
      const job = await api.post<Job>("/api/system/update", { version: r.version });
      setJobId(job.id);
    } catch (e) {
      toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));
    }
  };

  const latest = rel.data?.check.latest;
  return (
    <div className="page">
      <PageHead
        title={t("info.title")}
        subtitle={t("info.subtitle")}
        actions={
          <button className="btn secondary" onClick={check} disabled={checking}>
            <RefreshCw /> {t("info.checkUpdates")}
          </button>
        }
      />

      <div className="grid two">
        <Card title={t("info.version")}>
          {info.data ? (
            <dl className="kv">
              <dt>{t("info.version")}</dt>
              <dd className="row">
                {info.data.build.version}
                <span className={`badge ${channel}`}>{t(`info.channels.${channel}`)}</span>
              </dd>
              <dt>{t("info.commit")}</dt>
              <dd><code>{info.data.build.commit?.slice(0, 10) ?? "–"}</code></dd>
              <dt>{t("info.builtAt")}</dt>
              <dd>{formatDate(info.data.build.built_at, i18n.language)}</dd>
              <dt>Python</dt>
              <dd>{info.data.python}</dd>
              {isAdmin && (
                <>
                  <dt>{t("info.database")}</dt>
                  <dd>{info.data.database ?? "–"}</dd>
                  <dt>{t("info.os")}</dt>
                  <dd>{info.data.os}</dd>
                  <dt>{t("info.disk")}</dt>
                  <dd>{info.data.disk ? t("info.diskFree", { free: formatBytes(info.data.disk.free), total: formatBytes(info.data.disk.total) }) : "–"}</dd>
                </>
              )}
            </dl>
          ) : (
            <p className="muted">{info.error ? errorText(info.error) : t("common.loading")}</p>
          )}
        </Card>

        <Card title={t("info.updates")}>
          <div className="stack">
            {rel.error && <Alert kind="warning">{errorText(rel.error)}</Alert>}
            {rel.data && (rel.data.check.update_available && latest ? (
              <Alert kind="success">
                <b>{t("info.updateAvailableTo", { version: latest.version })}</b>
                <div className="small muted">{formatDate(latest.published_at, i18n.language)}</div>
              </Alert>
            ) : (
              <Alert>{t("info.upToDate")}</Alert>
            ))}
            {rel.data?.check.channel_mismatch && latest && (
              <Alert kind="warning">{t("info.channelMismatch", { version: latest.version })}</Alert>
            )}
            {isAdmin && (
              <>
                <div className="field">
                  <span>{t("info.channel")}</span>
                  <div className="seg">
                    {(["production", "test"] as const).map((c) => (
                      <button key={c} type="button" aria-pressed={channel === c} onClick={() => channel !== c && switchChannel(c)}>
                        {c === "production" ? <Rocket size={14} /> : <FlaskConical size={14} />} {t(`info.channels.${c}`)}
                      </button>
                    ))}
                  </div>
                  <small>{t(`info.channelHelp.${channel}`)}</small>
                </div>
                {latest && rel.data?.check.update_available && (
                  <div className="row">
                    <button className="btn" onClick={() => setConfirm(latest)}>
                      <ArrowDownCircle /> {t("info.updateNow")}
                    </button>
                  </div>
                )}
              </>
            )}
            {!isAdmin && <p className="muted small">{t("info.adminOnly")}</p>}
          </div>
        </Card>
      </div>

      {jobId !== null && (
        <Card title={t("info.updateProgress")}>
          <JobLog jobId={jobId} onDone={(j) => {
            if (j.status === "succeeded") {
              toast("success", t("info.updateDone"));
              setTimeout(() => window.location.reload(), 1500);
            }
          }} />
        </Card>
      )}

      <Card
        title={t("info.releases")}
        subtitle={t("info.releasesIntro")}
        actions={
          <div className="seg">
            {(["all", "production", "test"] as const).map((f) => (
              <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                {f === "all" ? t("common.all") : t(`info.channels.${f}`)}
              </button>
            ))}
          </div>
        }
      >
        <div className="stack">
          {rel.data && releases.length === 0 && <p className="muted">{t("info.noReleases")}</p>}
          {releases.map((r) => (
            <article key={r.tag} className={`release${r.version === current ? " current" : ""}`}>
              <header>
                <div className="row">
                  <h3>{r.name}</h3>
                  <span className={`badge ${r.channel}`}>{t(`info.channels.${r.channel}`)}</span>
                  {r.version === current && <span className="badge accent">{t("info.installed")}</span>}
                  <span className="muted small">{formatDate(r.published_at, i18n.language)}</span>
                </div>
                <div className="row">
                  <a className="btn ghost" href={r.url} target="_blank" rel="noreferrer"><ExternalLink /> GitHub</a>
                  {isAdmin && r.version !== current && r.asset_url && (
                    <button className="btn secondary" onClick={() => setConfirm(r)}>{t("info.install")}</button>
                  )}
                </div>
              </header>
              <div className="notes"><ReleaseNotes release={r} /></div>
            </article>
          ))}
        </div>
      </Card>

      {isAdmin && info.data?.jobs && info.data.jobs.length > 0 && (
        <Card title={t("jobs.recent")}>
          <div className="table-wrap">
            <table>
              <thead><tr><th>{t("jobs.job")}</th><th>{t("jobs.state")}</th><th>{t("jobs.started")}</th><th>{t("jobs.finished")}</th></tr></thead>
              <tbody>
                {info.data.jobs.map((j) => (
                  <tr key={j.id}>
                    <td>{t(`jobs.kinds.${j.kind}`)} {j.params?.version ? String(j.params.version) : j.params?.type ? t(`backup.types.${String(j.params.type)}`) : ""}</td>
                    <td><span className={`badge ${j.status === "succeeded" ? "good" : j.status === "failed" ? "critical" : "warning"}`}>{t(`jobs.status.${j.status}`)}</span></td>
                    <td>{formatDate(j.started_at, i18n.language)}</td>
                    <td>{formatDate(j.finished_at, i18n.language)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {confirm && (
        <Modal title={t("info.confirmTitle", { version: confirm.version })} onClose={() => setConfirm(null)}>
          <div className="stack">
            <p>{t("info.confirmText")}</p>
            {confirm.channel !== channel && <Alert kind="warning">{t("info.confirmOtherChannel")}</Alert>}
            <div className="row end">
              <button className="btn secondary" onClick={() => setConfirm(null)}>{t("common.cancel")}</button>
              <button className="btn" onClick={() => install(confirm)}>{t("info.install")}</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
