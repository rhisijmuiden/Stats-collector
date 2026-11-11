import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Newspaper, Pencil, Plus, Radio, Search, Trash2, X } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { formatDate, formatDay } from "../lib/format";
import { Alert, Card, Field, Modal, PageHead, useLoad } from "../components/ui";
import Chart, { cssVar } from "../components/Chart";
import { channel, fmt, ItemModal, kindIcon } from "./Content";

interface ChannelSum { platform: string; items: number; views: number; interactions: number; listener_minutes: number; peak: number }
interface Slot { source_id: number; start: string; end: string; label: string }
interface StoryCard {
  id: number; name: string; description: string; item_ids: number[]; excluded_ids: number[]; keywords: string[]; radio: Slot[];
  start_date: string; end_date: string | null; totals: { items: number; channels: number; views: number; interactions: number; listener_minutes: number };
  channels: ChannelSum[];
}
interface StoryItem {
  id: number; title: string; kind: string; url: string | null; source: { id: number; name: string; kind: string } | null; published_at: string | null;
  why: "picked" | "linked" | "keyword"; views: number; interactions: number; listener_minutes: number; peak: number; authors: string[];
}
interface RadioResult { source: { id: number; name: string; kind: string }; label: string; start: string; end: string; avg: number; peak: number; listener_minutes: number; samples: number }
interface StoryDetail extends Omit<StoryCard, "radio"> { days: string[]; series: Record<string, { views: number[]; interactions: number[] }>; items: StoryItem[]; radio: RadioResult[] }
interface Found { id: number; title: string; published_at: string | null; source: { id: number; name: string; kind: string } | null }
interface Draft {
  id?: number; name: string; description: string; picked: Found[]; excluded_ids: number[]; keywords: string; start_date: string; end_date: string;
  radio: { source_id: number; start: string; end: string; label: string }[];
}

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
/** "2026-11-10T08:10" in the browser's time zone ↔ ISO with offset. */
const toLocalInput = (iso: string) => { const d = new Date(iso); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const fromLocalInput = (v: string) => new Date(v).toISOString();

function ChannelChips({ channels }: { channels: ChannelSum[] }) {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  return (
    <div className="story-channels">
      {channels.map((c) => (
        <span key={c.platform} className="story-chip" style={{ ["--c" as string]: theme?.channels?.[c.platform] ?? cssVar("--accent", "#0E9F8E") }}>
          {kindIcon(c.platform === "website" ? "wordpress" : c.platform)}
          <b>{fmt(c.views || c.interactions || c.listener_minutes, i18n.language)}</b>
          <small>{t(c.views ? "stories.views" : c.interactions ? "stories.interactions" : "stories.minutes")}</small>
        </span>
      ))}
    </div>
  );
}

function StoryView({ id, onClose, onEdit, canEdit }: { id: number; onClose: () => void; onEdit: (s: StoryDetail) => void; canEdit: boolean }) {
  const { t, i18n } = useTranslation();
  const { theme, toast } = useApp();
  const lang = i18n.language;
  const story = useLoad(() => api.get<StoryDetail>(`/api/stories/${id}`), [id]);
  const [item, setItem] = useState<number | null>(null);
  const s = story.data;
  const option = useMemo(() => {
    if (!s) return null;
    const text = cssVar("--muted", "#5d6b80");
    const grid = cssVar("--border", "#e2e7ef");
    return {
      animationDuration: 300,
      tooltip: { trigger: "axis", valueFormatter: (v: number) => fmt(v, lang) },
      legend: { bottom: 0, textStyle: { color: text } },
      grid: { left: 8, right: 16, top: 16, bottom: 36, containLabel: true },
      xAxis: { type: "category", data: s.days.map((d) => new Date(d).toLocaleDateString(lang, { day: "numeric", month: "short" })), axisLabel: { color: text, hideOverlap: true }, axisLine: { lineStyle: { color: grid } } },
      yAxis: { type: "value", axisLabel: { color: text }, splitLine: { lineStyle: { color: grid } } },
      series: Object.entries(s.series).map(([p, v]) => ({
        name: t(`editors.platform.${p}`, { defaultValue: p }), type: "bar", stack: "views", data: v.views.map((x, i) => x || v.interactions[i]),
        color: theme?.channels?.[p] ?? "#3E7BFA", itemStyle: { borderRadius: 2 },
      })),
    };
  }, [s, lang, t, theme]);
  if (item != null) return <ItemModal id={item} range="30d" onClose={() => setItem(null)} />;
  const exclude = async (itemId: number) => {
    if (!s) return;
    try {
      await api.put(`/api/stories/${s.id}`, {
        name: s.name, description: s.description, item_ids: s.item_ids.filter((x) => x !== itemId), excluded_ids: [...s.excluded_ids, itemId],
        keywords: s.keywords, radio: s.radio.map((r) => ({ source_id: r.source.id, start: r.start, end: r.end, label: r.label })), start_date: s.start_date, end_date: s.end_date,
      });
      story.reload();
    } catch (e) { toast("error", errorText(e instanceof ApiError ? e.detail : String(e))); }
  };
  const radio = s?.radio ?? [];
  return (
    <Modal title={s?.name ?? "…"} onClose={onClose}>
      {story.error && <Alert kind="error">{errorText(story.error)}</Alert>}
      {s && (
        <div className="stack">
          <div className="muted small">{formatDay(s.start_date, lang)} – {s.end_date ? formatDay(s.end_date, lang) : t("stories.today")}{s.keywords.length ? ` · ${t("stories.keywordsShort")}: ${s.keywords.join(", ")}` : ""}</div>
          {s.description && <p className="small">{s.description}</p>}
          <div className="kpis">
            <div className="kpi"><div className="kpi-label">{t("stories.totalViews")}</div><div className="kpi-value">{fmt(s.totals.views, lang)}</div><div className="kpi-sub">{t("stories.onChannels", { count: s.totals.channels })}</div></div>
            <div className="kpi"><div className="kpi-label">{t("stories.totalInteractions")}</div><div className="kpi-value">{fmt(s.totals.interactions, lang)}</div></div>
            {s.totals.listener_minutes > 0 && <div className="kpi"><div className="kpi-label">{t("stories.totalMinutes")}</div><div className="kpi-value">{fmt(s.totals.listener_minutes, lang)}</div></div>}
            <div className="kpi"><div className="kpi-label">{t("stories.items")}</div><div className="kpi-value">{fmt(s.totals.items, lang)}</div></div>
          </div>
          <div className="kpis">
            {s.channels.map((c) => (
              <div className="kpi" key={c.platform}>
                <span className="kpi-bar" style={{ background: theme?.channels?.[c.platform] }} />
                <div className="kpi-label">{kindIcon(c.platform === "website" ? "wordpress" : c.platform)} {t(`editors.platform.${c.platform}`, { defaultValue: c.platform })}</div>
                <div className="kpi-value">{fmt(c.views || c.interactions || c.listener_minutes, lang)}</div>
                <div className="kpi-sub">{t(c.views ? "stories.views" : c.interactions ? "stories.interactions" : "stories.minutes")} · {t("stories.itemCount", { count: c.items })}</div>
              </div>
            ))}
          </div>
          {option && Object.keys(s.series).length > 0 && <Chart option={option} />}
          <h3 className="small-title">{t("stories.itemsTitle")}</h3>
          {s.items.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("content.title_")}</th><th>{t("stories.why")}</th><th className="num">{t("stories.views")}</th><th className="num">{t("stories.interactions")}</th>{canEdit && <th />}</tr></thead>
              <tbody>{s.items.map((i) => (
                <tr key={i.id}>
                  <td>
                    <button type="button" className="link-btn" onClick={() => setItem(i.id)}>{i.title || "–"}</button>
                    <div className="muted small source-kind"><i style={{ background: theme?.channels?.[channel(i.source?.kind ?? "")] }} />{kindIcon(i.source?.kind)} {i.source?.name}{i.published_at ? ` · ${formatDate(i.published_at, lang)}` : ""}{i.authors.length ? ` · ${i.authors.join(", ")}` : ""}</div>
                  </td>
                  <td><span className={`badge ${i.why === "picked" ? "accent" : ""}`}>{t(`stories.reason.${i.why}`)}</span></td>
                  <td className="num">{i.views ? fmt(i.views, lang) : i.listener_minutes ? `${fmt(i.listener_minutes, lang)} min` : "–"}</td>
                  <td className="num">{fmt(i.interactions, lang)}</td>
                  {canEdit && <td className="num"><button className="btn ghost" title={t("stories.remove")} aria-label={t("stories.remove")} onClick={() => exclude(i.id)}><X /></button></td>}
                </tr>
              ))}</tbody>
            </table></div>
          ) : <p className="muted small">{t("stories.noItems")}</p>}
          {radio.length > 0 && (
            <>
              <h3 className="small-title">{t("stories.radioTitle")}</h3>
              <div className="table-wrap"><table>
                <thead><tr><th>{t("stories.slot")}</th><th className="num">{t("stories.avg")}</th><th className="num">{t("stories.peak")}</th><th className="num">{t("stories.totalMinutes")}</th></tr></thead>
                <tbody>{radio.map((r, n) => (
                  <tr key={n}>
                    <td><b>{r.label || r.source.name}</b><div className="muted small"><Radio size={12} /> {r.source.name} · {formatDate(r.start, lang)} – {new Date(r.end).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" })}</div></td>
                    <td className="num">{fmt(r.avg, lang, 1)}</td><td className="num">{fmt(r.peak, lang)}</td><td className="num">{fmt(r.listener_minutes, lang)}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            </>
          )}
          <div className="row end">
            {canEdit && <button className="btn secondary" onClick={() => onEdit(s)}><Pencil /> {t("common.edit")}</button>}
            <button className="btn secondary" onClick={onClose}>{t("common.close")}</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function ItemPicker({ picked, onAdd }: { picked: Found[]; onAdd: (f: Found) => void }) {
  const { t, i18n } = useTranslation();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Found[] | null>(null);
  const search = async () => setFound(await api.get<Found[]>(`/api/content/find?side=any&q=${encodeURIComponent(q.trim())}`));
  return (
    <div className="stack">
      <div className="row">
        <label className="search" style={{ flex: 1 }}><Search size={15} /><input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void search(); } }} placeholder={t("stories.searchItems")} aria-label={t("stories.searchItems")} /></label>
        <button type="button" className="btn secondary" onClick={search}>{t("stories.search")}</button>
      </div>
      {found && (
        <ul className="pick-list">
          {found.filter((f) => !picked.some((p) => p.id === f.id)).map((f) => (
            <li key={f.id}>
              <span>{kindIcon(f.source?.kind)} {f.title} <small className="muted">{f.source?.name}{f.published_at ? ` · ${formatDay(f.published_at, i18n.language)}` : ""}</small></span>
              <button type="button" className="btn ghost" onClick={() => onAdd(f)}><Plus /> {t("stories.add")}</button>
            </li>
          ))}
          {!found.length && <li className="muted small">{t("stories.nothingFound")}</li>}
        </ul>
      )}
    </div>
  );
}

export default function StoriesPage() {
  const { t, i18n } = useTranslation();
  const { user, toast, theme } = useApp();
  const lang = i18n.language;
  const canEdit = user?.role !== "staff";
  const list = useLoad(() => api.get<StoryCard[]>("/api/stories"));
  const streams = useLoad(() => api.get<{ id: number; name: string; kind: string }[]>("/api/stories/streams"));
  const [open, setOpen] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const edit = async (s?: StoryCard | StoryDetail) => {
    setOpen(null);
    if (!s) {
      setDraft({ name: "", description: "", picked: [], excluded_ids: [], keywords: "", start_date: daysAgo(7), end_date: "", radio: [] });
      return;
    }
    const detail = await api.get<StoryDetail>(`/api/stories/${s.id}`);
    const picked = detail.items.filter((i) => i.why === "picked").map((i) => ({ id: i.id, title: i.title, published_at: i.published_at, source: i.source }));
    setDraft({
      id: s.id, name: s.name, description: s.description, picked, excluded_ids: s.excluded_ids, keywords: s.keywords.join(", "),
      start_date: s.start_date, end_date: s.end_date ?? "",
      radio: detail.radio.map((r) => ({ source_id: r.source.id, start: toLocalInput(r.start), end: toLocalInput(r.end), label: r.label })),
    });
  };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    const d = draft!;
    const body = {
      name: d.name, description: d.description, item_ids: d.picked.map((p) => p.id), excluded_ids: d.excluded_ids.filter((x) => !d.picked.some((p) => p.id === x)),
      keywords: d.keywords.split(",").map((k) => k.trim()).filter(Boolean), start_date: d.start_date, end_date: d.end_date || null,
      radio: d.radio.filter((r) => r.start && r.end).map((r) => ({ ...r, start: fromLocalInput(r.start), end: fromLocalInput(r.end) })),
    };
    try {
      const saved = d.id ? await api.put<StoryCard>(`/api/stories/${d.id}`, body) : await api.post<StoryCard>("/api/stories", body);
      toast("success", t("common.saved"));
      setDraft(null);
      list.reload();
      setOpen(saved.id);
    } catch (err) { fail(err); }
  };
  const remove = async () => {
    if (!window.confirm(t("stories.confirmDelete", { name: draft!.name }))) return;
    try { await api.del(`/api/stories/${draft!.id}`); setDraft(null); list.reload(); } catch (err) { fail(err); }
  };
  const setSlot = (n: number, patch: Partial<Draft["radio"][number]>) => setDraft({ ...draft!, radio: draft!.radio.map((r, i) => (i === n ? { ...r, ...patch } : r)) });

  return (
    <div className="page">
      <PageHead help="stories" title={t("stories.title")} subtitle={t("stories.subtitle")}
        actions={canEdit && <button className="btn" onClick={() => edit()}><Plus /> {t("stories.new")}</button>} />
      {list.error && <Alert kind="error">{errorText(list.error)}</Alert>}
      {list.data && (list.data.length ? (
        <div className="goal-cards">
          {list.data.map((s) => {
            const total = s.channels.reduce((a, c) => a + (c.views || c.interactions || c.listener_minutes), 0) || 1;
            return (
              <button key={s.id} type="button" className="card goal-card story-card" onClick={() => setOpen(s.id)}>
                <h2>{s.name}</h2>
                <div className="muted small">{formatDay(s.start_date, lang)} – {s.end_date ? formatDay(s.end_date, lang) : t("stories.today")} · {t("stories.itemCount", { count: s.totals.items })}</div>
                <div className="story-total"><b>{fmt(s.totals.views, lang)}</b> <span className="muted small">{t("stories.viewsAll")}</span></div>
                <div className="story-split" aria-hidden>
                  {s.channels.map((c) => <span key={c.platform} style={{ flexGrow: (c.views || c.interactions || c.listener_minutes) / total, background: theme?.channels?.[c.platform] }} />)}
                </div>
                <ChannelChips channels={s.channels} />
              </button>
            );
          })}
        </div>
      ) : <Card><div className="empty"><Newspaper /><h2>{t("stories.noneTitle")}</h2><p>{t(canEdit ? "stories.noneText" : "stories.noneTextReader")}</p></div></Card>)}

      {open != null && <StoryView id={open} onClose={() => setOpen(null)} onEdit={(s) => void edit(s)} canEdit={canEdit} />}
      {draft && (
        <Modal title={draft.id ? t("stories.edit") : t("stories.new")} onClose={() => setDraft(null)}>
          <form className="stack" onSubmit={save}>
            <Field label={t("stories.name")}><input required maxLength={200} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder={t("stories.namePlaceholder")} /></Field>
            <Field label={t("stories.description")}><textarea rows={2} maxLength={2000} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></Field>
            <div className="grid two">
              <Field label={t("stories.startDate")}><input required type="date" value={draft.start_date} max={today()} onChange={(e) => setDraft({ ...draft, start_date: e.target.value })} /></Field>
              <Field label={t("stories.endDate")} hint={t("stories.endHint")}><input type="date" value={draft.end_date} min={draft.start_date} onChange={(e) => setDraft({ ...draft, end_date: e.target.value })} /></Field>
            </div>
            <Field label={t("stories.picked")} hint={t("stories.pickedHint")}>
              <div className="stack">
                {draft.picked.length > 0 && (
                  <ul className="pick-list">
                    {draft.picked.map((p) => (
                      <li key={p.id}><span>{kindIcon(p.source?.kind)} {p.title} <small className="muted">{p.source?.name}</small></span>
                        <button type="button" className="btn ghost" aria-label={t("stories.remove")} onClick={() => setDraft({ ...draft, picked: draft.picked.filter((x) => x.id !== p.id) })}><X /></button></li>
                    ))}
                  </ul>
                )}
                <ItemPicker picked={draft.picked} onAdd={(f) => setDraft({ ...draft, picked: [...draft.picked, f] })} />
              </div>
            </Field>
            <Field label={t("stories.keywords")} hint={t("stories.keywordsHint")}><input value={draft.keywords} onChange={(e) => setDraft({ ...draft, keywords: e.target.value })} placeholder={t("stories.keywordsPlaceholder")} /></Field>
            <Field label={t("stories.radio")} hint={t("stories.radioHint")}>
              <div className="stack">
                {draft.radio.map((r, n) => (
                  <div key={n} className="slot-row">
                    <select value={r.source_id} onChange={(e) => setSlot(n, { source_id: Number(e.target.value) })} aria-label={t("stories.stream")}>
                      {(streams.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                    <input type="datetime-local" value={r.start} onChange={(e) => setSlot(n, { start: e.target.value })} aria-label={t("stories.from")} />
                    <input type="datetime-local" value={r.end} min={r.start} onChange={(e) => setSlot(n, { end: e.target.value })} aria-label={t("stories.to")} />
                    <input value={r.label} maxLength={200} onChange={(e) => setSlot(n, { label: e.target.value })} placeholder={t("stories.slotLabel")} aria-label={t("stories.slotLabel")} />
                    <button type="button" className="btn ghost" aria-label={t("stories.remove")} onClick={() => setDraft({ ...draft, radio: draft.radio.filter((_, i) => i !== n) })}><X /></button>
                  </div>
                ))}
                {(streams.data ?? []).length > 0
                  ? <div><button type="button" className="btn secondary" onClick={() => setDraft({ ...draft, radio: [...draft.radio, { source_id: streams.data![0].id, start: "", end: "", label: "" }] })}><Radio /> {t("stories.addSlot")}</button></div>
                  : <span className="muted small">{t("stories.noStreams")}</span>}
              </div>
            </Field>
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
