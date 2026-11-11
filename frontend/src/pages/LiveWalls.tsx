import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, ExternalLink, MonitorPlay, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { Alert, Card, Field, Modal, PageHead, Switch, useLoad } from "../components/ui";
import { errorText } from "../i18n";
import { kindIcon } from "./Content";

type Layout = "rotate" | "overview" | "stories";
interface Wall { id: number; name: string; title: string; source_ids: number[]; allow_ips: string; enabled: boolean; layout: Layout; rotate_seconds: number; show_authors: boolean; url: string; rotated_at: string | null }
interface SourceRef { id: number; name: string; kind: string }
interface Walls { walls: Wall[]; sources: SourceRef[]; base_url: string }
interface WallConfig { public_url: string; trusted_proxies: string; default_url: string }
interface Snapshot {
  title: string;
  channels: { id: number; name: string; kind: string; color: string; unit: string; now: number; online: boolean; bars: number[] }[];
  socials: { id: number; name: string; kind: string; color: string; measure: "views" | "interactions"; value: number; days: number[] }[];
  top: { id: number; title: string; value: number }[];
}

const empty = { name: "", title: "", source_ids: [] as number[], allow_ips: "", enabled: true, layout: "rotate" as Layout, rotate_seconds: 30, show_authors: true };
type Draft = typeof empty & { id?: number };
const toDraft = (w: Wall): Draft => ({ id: w.id, name: w.name, title: w.title, source_ids: w.source_ids, allow_ips: w.allow_ips, enabled: w.enabled, layout: w.layout, rotate_seconds: w.rotate_seconds, show_authors: w.show_authors });

function Preview({ id }: { id: number }) {
  const { t, i18n } = useTranslation();
  const snap = useLoad(() => api.get<Snapshot>(`/api/livewalls/${id}/preview`), [id]);
  if (snap.error) return <Alert kind="error">{errorText(snap.error)}</Alert>;
  if (!snap.data) return null;
  const socials = snap.data.socials ?? [];
  if (!snap.data.channels.length && !socials.length) return <p className="muted small">{t("livewalls.noChannels")}</p>;
  const fmt = new Intl.NumberFormat(i18n.language);
  return (
    <div className="stack">
    <div className="wall-preview">
      {snap.data.channels.map((c) => {
        const max = Math.max(1, ...c.bars);
        return (
          <div key={c.id} className="wall-mini" style={{ ["--c" as string]: c.color }}>
            <div className="wall-mini-head">{kindIcon(c.kind)} {c.name}<span className={`wall-dot${c.online ? " on" : ""}`} /></div>
            <div className="wall-mini-now">{fmt.format(c.now)} <span>{t(`livewalls.unit.${c.unit}`)}</span></div>
            <div className="wall-mini-bars">{c.bars.map((b, i) => <i key={i} style={{ height: `${Math.max(3, (b / max) * 100)}%` }} />)}</div>
          </div>
        );
      })}
      {socials.map((c) => {
        const max = Math.max(1, ...c.days);
        return (
          <div key={`s${c.id}`} className="wall-mini" style={{ ["--c" as string]: c.color }}>
            <div className="wall-mini-head">{kindIcon(c.kind)} {c.name}</div>
            <div className="wall-mini-now">{fmt.format(c.value)} <span>{t(`livewalls.unit.${c.measure}Day`)}</span></div>
            <div className="wall-mini-bars">{c.days.map((b, i) => <i key={i} style={{ height: `${Math.max(3, (b / max) * 100)}%` }} />)}</div>
          </div>
        );
      })}
    </div>
    {snap.data.top?.length ? <p className="muted small">{t("livewalls.topPreview", { title: snap.data.top[0].title, n: fmt.format(snap.data.top[0].value) })}</p> : null}
    </div>
  );
}

function AddressCard({ onSaved }: { onSaved: () => void }) {
  const { t } = useTranslation();
  const { toast } = useApp();
  const cfg = useLoad(() => api.get<WallConfig>("/api/livewalls/config"));
  const [draft, setDraft] = useState<WallConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const value = draft ?? cfg.data;
  if (!value) return null;
  const save = async () => {
    setBusy(true);
    try {
      setDraft(await api.put<WallConfig>("/api/livewalls/config", { public_url: value.public_url, trusted_proxies: value.trusted_proxies }));
      toast("success", t("livewalls.addressSaved")); onSaved();
    } catch (e) { toast("error", errorText(e instanceof ApiError ? e.detail : String(e))); } finally { setBusy(false); }
  };
  return (
    <Card title={t("livewalls.addressTitle")} subtitle={t("livewalls.addressText")}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <div className="grid two">
          <Field label={t("livewalls.publicUrl")} hint={t("livewalls.publicUrlHint", { url: value.default_url })}>
            <input type="url" maxLength={300} value={value.public_url} placeholder={value.default_url} onChange={(e) => setDraft({ ...value, public_url: e.target.value })} />
          </Field>
          <Field label={t("livewalls.proxies")} hint={t("livewalls.proxiesHint")}>
            <input maxLength={1000} value={value.trusted_proxies} placeholder="192.0.2.20" onChange={(e) => setDraft({ ...value, trusted_proxies: e.target.value })} />
          </Field>
        </div>
        <div className="row end"><button type="submit" className="btn" disabled={busy}>{t("common.save")}</button></div>
      </form>
    </Card>
  );
}

export default function LiveWallsPage() {
  const { t } = useTranslation();
  const { toast } = useApp();
  const data = useLoad(() => api.get<Walls>("/api/livewalls"));
  const [edit, setEdit] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));
  const copy = async (text: string) => { try { await navigator.clipboard.writeText(text); toast("success", t("livewalls.copied")); } catch { /* ignore */ } };
  const sources = data.data?.sources ?? [];

  const save = async () => {
    if (!edit) return;
    setBusy(true);
    const body = { name: edit.name, title: edit.title, source_ids: edit.source_ids, allow_ips: edit.allow_ips, enabled: edit.enabled, layout: edit.layout, rotate_seconds: edit.rotate_seconds, show_authors: edit.show_authors };
    try {
      if (edit.id) await api.put(`/api/livewalls/${edit.id}`, body); else await api.post("/api/livewalls", body);
      setEdit(null); data.reload(); toast("success", t("livewalls.saved"));
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const rotate = async (w: Wall) => {
    if (!window.confirm(t("livewalls.confirmRotate", { name: w.name }))) return;
    try { await api.post(`/api/livewalls/${w.id}/rotate`, {}); data.reload(); toast("success", t("livewalls.rotated")); } catch (e) { fail(e); }
  };
  const remove = async (w: Wall) => {
    if (!window.confirm(t("livewalls.confirmDelete", { name: w.name }))) return;
    try { await api.del(`/api/livewalls/${w.id}`); data.reload(); } catch (e) { fail(e); }
  };
  const toggle = (id: number) => edit && setEdit({ ...edit, source_ids: edit.source_ids.includes(id) ? edit.source_ids.filter((x) => x !== id) : [...edit.source_ids, id] });

  return (
    <div className="page">
      <PageHead help="live-wall" title={t("livewalls.title")} subtitle={t("livewalls.subtitle")}
        actions={<button className="btn" onClick={() => setEdit({ ...empty, name: t("livewalls.defaultName") })}><Plus /> {t("livewalls.add")}</button>} />
      {data.error && <Alert kind="error">{errorText(data.error)}</Alert>}
      {data.data && <Alert kind="info">{t("livewalls.proxyHint", { url: data.data.base_url })}</Alert>}
      {data.data && !data.data.walls.length && (
        <Card><div className="empty"><MonitorPlay /><h2>{t("livewalls.noneTitle")}</h2><p>{t("livewalls.noneText")}</p></div></Card>
      )}
      {data.data?.walls.map((w) => (
        <Card key={w.id} title={w.name} subtitle={w.title || undefined}
          actions={<div className="row">
            <span className={`badge${w.enabled ? " good" : ""}`}>{t(w.enabled ? "livewalls.on" : "livewalls.off")}</span>
            <button className="btn ghost" title={t("common.edit")} aria-label={t("common.edit")} onClick={() => setEdit(toDraft(w))}><Pencil /></button>
            <button className="btn ghost" title={t("livewalls.rotate")} aria-label={t("livewalls.rotate")} onClick={() => rotate(w)}><RefreshCw /></button>
            <button className="btn ghost" title={t("common.delete")} aria-label={t("common.delete")} onClick={() => remove(w)}><Trash2 /></button>
          </div>}>
          <div className="stack">
            <div className="copy-field">
              <input readOnly value={w.url} onFocus={(e) => e.target.select()} aria-label={t("livewalls.link")} />
              <button type="button" className="btn secondary" onClick={() => copy(w.url)}><Copy /> {t("livewalls.copy")}</button>
              <a className="btn secondary" href={w.url} target="_blank" rel="noreferrer"><ExternalLink /> {t("livewalls.open")}</a>
            </div>
            <div className="muted small row">
              <span>{t("livewalls.channels")}: {w.source_ids.length ? w.source_ids.map((id) => sources.find((s) => s.id === id)?.name).filter(Boolean).join(", ") : t("livewalls.allChannels")}</span>
              <span>{t("livewalls.layout")}: {t(`livewalls.layouts.${w.layout}`)}{w.layout === "rotate" ? ` (${t("livewalls.everySeconds", { n: w.rotate_seconds })})` : ""}</span>
              <span>{t("livewalls.allowIps")}: {w.allow_ips || t("livewalls.everyone")}</span>
            </div>
            {w.enabled && <Preview id={w.id} />}
          </div>
        </Card>
      ))}
      <AddressCard onSaved={data.reload} />
      {edit && (
        <Modal title={t(edit.id ? "livewalls.edit" : "livewalls.add")} onClose={() => setEdit(null)}>
          <form className="stack" onSubmit={(e) => { e.preventDefault(); save(); }}>
            <Field label={t("livewalls.name")}><input required maxLength={200} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label={t("livewalls.wallTitle")} hint={t("livewalls.wallTitleHint")}><input maxLength={200} value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></Field>
            <Field label={t("livewalls.channels")} hint={t("livewalls.channelsHint")}>
              <div className="chips">{sources.map((s) => <button key={s.id} type="button" className="chip" aria-pressed={edit.source_ids.includes(s.id)} onClick={() => toggle(s.id)}>{kindIcon(s.kind)} {s.name}</button>)}</div>
            </Field>
            <div className="grid two">
              <Field label={t("livewalls.layout")} hint={t(`livewalls.layoutHint.${edit.layout}`)}>
                <select value={edit.layout} onChange={(e) => setEdit({ ...edit, layout: e.target.value as Layout })}>
                  {(["rotate", "overview", "stories"] as Layout[]).map((l) => <option key={l} value={l}>{t(`livewalls.layouts.${l}`)}</option>)}
                </select>
              </Field>
              {edit.layout === "rotate" && (
                <Field label={t("livewalls.rotateSeconds")} hint={t("livewalls.rotateSecondsHint")}>
                  <input type="number" min={10} max={300} required value={edit.rotate_seconds} onChange={(e) => setEdit({ ...edit, rotate_seconds: Number(e.target.value) })} />
                </Field>
              )}
            </div>
            <Switch checked={edit.show_authors} onChange={(v) => setEdit({ ...edit, show_authors: v })} label={t("livewalls.showAuthors")} />
            <Field label={t("livewalls.allowIps")} hint={t("livewalls.allowIpsHint")}><input value={edit.allow_ips} maxLength={1000} placeholder="192.0.2.10, 198.51.100.0/24" onChange={(e) => setEdit({ ...edit, allow_ips: e.target.value })} /></Field>
            <Switch checked={edit.enabled} onChange={(v) => setEdit({ ...edit, enabled: v })} label={t("livewalls.enabled")} />
            <div className="row end">
              <button type="button" className="btn secondary" onClick={() => setEdit(null)}>{t("common.cancel")}</button>
              <button type="submit" className="btn" disabled={busy}>{t("common.save")}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
