// Wall Designer: choose what a live wall shows. The middle shows the real wall page (an iframe of the
// wall service's page, fed with the wall's numbers and the design being edited); on top of it sits a
// grid of 12 x 8 cells where blocks are moved and resized. Blocks and screens: services/walldesign.py.
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent as RPointerEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft, ArrowRight, Copy, Eye, History, LayoutTemplate, Pencil, Plus, Rocket, Save, Trash2, Undo2,
} from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { Alert, Field, Modal, Switch, useLoad } from "../components/ui";
import { errorText } from "../i18n";
import { kindIcon } from "./Content";

const COLS = 12, ROWS = 8, PAD = 40, GAP = 20, W = 1920, H = 1080;
const CW = (W - 2 * PAD - (COLS - 1) * GAP) / COLS, CH = (H - 2 * PAD - (ROWS - 1) * GAP) / ROWS;

export type BlockType = "header" | "kpi" | "tiles" | "chart" | "race" | "goals" | "risers" | "ticker" | "msg";
type Metric = "live" | "views" | "interactions" | "followers";
type Period = "hour" | "today" | "7d" | "30d";
export interface Block {
  id: string; type: BlockType; x: number; y: number; w: number; h: number; title: string; metric: Metric; channels: number[];
  period: Period; viz: string; color: string; trend: boolean; countup: boolean; editors: boolean; rows: number; text: string; sub: string;
}
export interface Screen { id: string; name: string; seconds: number; background: "neon" | "aurora" | "plain"; blocks: Block[] }
export interface Design { screens: Screen[] }
interface Version { version: number; design: Design | null; created_at: string | null; created_by: string }
interface DesignResp { design: Design; custom: boolean; draft: Design | null; version: number; versions: Version[]; templates: Record<"overview" | "stories", Screen> }
interface SourceRef { id: number; name: string; kind: string }
interface WallRef { id: number; name: string; title: string; source_ids: number[]; url: string }

const TYPES: BlockType[] = ["header", "kpi", "tiles", "chart", "race", "goals", "risers", "ticker", "msg"];
const VIZ: Partial<Record<BlockType, string[]>> = {
  kpi: ["numline", "number", "gauge"], tiles: ["tiles", "bars3d", "list"], chart: ["area", "line", "bars", "donut"], race: ["race", "list"], goals: ["bar", "rings"],
};
const SIZE: Record<BlockType, [number, number]> = { header: [12, 1], kpi: [4, 2], tiles: [6, 3], chart: [4, 3], race: [6, 5], goals: [4, 3], risers: [4, 2], ticker: [12, 1], msg: [6, 2] };
const SWATCHES = ["#2FB8FF", "#2CC4B0", "#3CCB7F", "#F5A524", "#FF6B6F", "#E14FD0", "#6C5CE7", "#D8F3FF"];
const ROWS_FOR: BlockType[] = ["race", "goals", "risers"];

const uid = () => Math.random().toString(36).slice(2, 9);
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const overlap = (a: Block, b: Block) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
function clamp(b: Block): Block {
  const w = Math.max(1, Math.min(COLS, b.w)), h = Math.max(1, Math.min(ROWS, b.h));
  return { ...b, w, h, x: Math.max(0, Math.min(COLS - w, b.x)), y: Math.max(0, Math.min(ROWS - h, b.y)) };
}
function newBlock(type: BlockType, x: number, y: number): Block {
  const [w, h] = SIZE[type];
  return clamp({
    id: uid(), type, x, y, w, h, title: "", metric: type === "kpi" ? "views" : "views", channels: [], period: type === "chart" ? "hour" : "today",
    viz: (VIZ[type] ?? [""])[0], color: "auto", trend: true, countup: true, editors: true, rows: type === "race" ? 8 : type === "risers" ? 4 : 3, text: "", sub: "",
  });
}
// The first free spot for a block of w x h cells; when the screen is too full, a smaller free spot.
function freeSpot(blocks: Block[], w: number, h: number): [number, number, number, number] {
  for (let size = 0; size < w + h; size++) {
    const ww = Math.max(1, w - Math.ceil(size / 2)), hh = Math.max(1, h - Math.floor(size / 2));
    for (let y = 0; y <= ROWS - hh; y++) for (let x = 0; x <= COLS - ww; x++) {
      const probe = { x, y, w: ww, h: hh } as Block;
      if (!blocks.some((b) => overlap(b, probe))) return [x, y, ww, hh];
    }
  }
  return [0, 0, w, h];
}
function screenKey(name: string, taken: string[]): string {
  const base = name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30) || "screen";
  let key = base, n = 2;
  while (taken.includes(key)) key = `${base}-${n++}`;
  return key;
}

function BlockIcon({ type }: { type: BlockType }) {
  const shapes: Record<BlockType, JSX.Element> = {
    header: <><rect x="2" y="3" width="28" height="4" rx="1" fill="#2FB8FF" /><circle cx="5" cy="5" r="1.4" fill="#FF3B5C" /></>,
    kpi: <><text x="4" y="14" fontSize="12" fontWeight="700" fill="#D8F3FF">48k</text><path d="M2 20 9 17 16 18 23 13 30 14" stroke="#2FB8FF" strokeWidth="1.6" fill="none" /></>,
    tiles: <>{[[2, 3, "#3E7BFA"], [12, 3, "#6C5CE7"], [22, 3, "#E14FD0"], [2, 12, "#E5484D"], [12, 12, "#12A594"], [22, 12, "#F5A524"]].map(([x, y, c]) => <rect key={`${x}${y}`} x={x} y={y} width="8" height="7" rx="1.5" fill={c as string} />)}</>,
    chart: <><path d="M2 19 8 12 14 15 20 7 26 10 30 4" stroke="#2FB8FF" strokeWidth="2" fill="none" /><path d="M2 19 8 16 14 17 20 13 26 15 30 11" stroke="#E14FD0" strokeWidth="2" fill="none" /></>,
    race: <><rect x="2" y="3" width="26" height="4" rx="1" fill="#6C5CE7" /><rect x="2" y="9" width="20" height="4" rx="1" fill="#3E7BFA" /><rect x="2" y="15" width="13" height="4" rx="1" fill="#E5484D" /></>,
    goals: <><rect x="2" y="5" width="28" height="3" rx="1.5" fill="#22304A" /><rect x="2" y="5" width="19" height="3" rx="1.5" fill="#2CC4B0" /><rect x="2" y="13" width="28" height="3" rx="1.5" fill="#22304A" /><rect x="2" y="13" width="11" height="3" rx="1.5" fill="#F5A524" /></>,
    risers: <><path d="M4 18 12 10 17 14 28 4" stroke="#3CCB7F" strokeWidth="2.2" fill="none" /><path d="M22 4h6v6" stroke="#3CCB7F" strokeWidth="2.2" fill="none" /></>,
    ticker: <><rect x="2" y="8" width="7" height="6" rx="1" fill="#2FB8FF" /><rect x="11" y="10" width="19" height="2" rx="1" fill="#D8F3FF" /></>,
    msg: <><rect x="4" y="6" width="24" height="3" rx="1" fill="#D8F3FF" /><rect x="8" y="12" width="16" height="2" rx="1" fill="rgba(216,243,255,.5)" /></>,
  };
  return <span className="wd-ic" aria-hidden="true"><svg viewBox="0 0 32 22">{shapes[type]}</svg></span>;
}

export default function WallDesigner() {
  const { id } = useParams();
  const wallId = Number(id);
  const { t, i18n } = useTranslation();
  const { toast } = useApp();
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const walls = useLoad(() => api.get<{ walls: WallRef[]; sources: SourceRef[] }>("/api/livewalls"));
  const [resp, setResp] = useState<DesignResp | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [design, setDesign] = useState<Design | null>(null);
  const [history, setHistory] = useState<Design[]>([]);
  const [dirty, setDirty] = useState(false);
  const [screenIdx, setScreenIdx] = useState(0);
  const [sel, setSel] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [snapshot, setSnapshot] = useState<unknown>(null);

  const wall = walls.data?.walls.find((w) => w.id === wallId);
  const sources = useMemo(() => {
    const all = walls.data?.sources ?? [];
    return wall?.source_ids.length ? all.filter((s) => wall.source_ids.includes(s.id)) : all;
  }, [walls.data, wall]);

  const load = useCallback(async () => {
    try {
      const r = await api.get<DesignResp>(`/api/livewalls/${wallId}/design`);
      setResp(r); setDesign(clone(r.draft ?? r.design)); setDirty(false); setHistory([]); setSel(null);
      setScreenIdx(0);
    } catch (e) { setLoadError(e instanceof ApiError ? e.detail : String(e)); }
  }, [wallId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    let alive = true;
    const get = () => api.get(`/api/livewalls/${wallId}/preview`).then((s) => alive && setSnapshot(s)).catch(() => undefined);
    get();
    const timer = window.setInterval(get, 60000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [wallId]);

  const screen = design?.screens[Math.min(screenIdx, (design?.screens.length ?? 1) - 1)];
  const block = screen?.blocks.find((b) => b.id === sel) ?? null;

  /* ---------- changes with undo ---------- */
  const change = (fn: (d: Design) => void) => {
    if (!design) return;
    const next = clone(design);
    fn(next);
    setHistory((h) => [...h.slice(-49), design]);
    setDesign(next); setDirty(true);
  };
  const changeScreen = (fn: (s: Screen) => void) => change((d) => fn(d.screens[screenIdx]));
  const changeBlock = (patch: Partial<Block>) => changeScreen((s) => {
    const i = s.blocks.findIndex((b) => b.id === sel);
    if (i >= 0) s.blocks[i] = clamp({ ...s.blocks[i], ...patch });
  });
  const undo = () => {
    if (!history.length) return;
    setDesign(history[history.length - 1]); setHistory((h) => h.slice(0, -1)); setDirty(true);
  };
  const addBlock = (type: BlockType, at?: [number, number]) => {
    if (!screen) return;
    const [w, h] = SIZE[type];
    const [x, y, fw, fh] = at ? [at[0], at[1], w, h] : freeSpot(screen.blocks, w, h);
    const b = clamp({ ...newBlock(type, x, y), x, y, w: fw, h: fh });
    changeScreen((s) => { s.blocks.push(b); });
    setSel(b.id);
  };

  /* ---------- the live preview ---------- */
  const frame = useRef<HTMLIFrameElement>(null);
  const post = useCallback(() => {
    const win = frame.current?.contentWindow;
    if (!win || !design || !snapshot || !screen) return;
    win.postMessage({ type: "wall", data: snapshot, design, screen: screen.id, lang: i18n.language.startsWith("nl") ? "nl" : "en" }, window.location.origin);
  }, [design, snapshot, screen, i18n.language]);
  useEffect(() => { post(); }, [post]);
  useEffect(() => {
    const onMsg = (e: MessageEvent) => { if (e.origin === window.location.origin && e.data?.type === "wall-ready") post(); };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [post]);

  /* ---------- scaling the 1920 x 1080 stage ---------- */
  const wrap = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.4);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setScale(el.clientWidth / W));
    ro.observe(el);
    return () => ro.disconnect();
  }, [design !== null]);

  /* ---------- moving and resizing ---------- */
  const drag = useRef<{ id: string; resize: boolean; x0: number; y0: number; start: Block; moved: boolean } | null>(null);
  const onDown = (e: RPointerEvent, b: Block, resize: boolean) => {
    e.stopPropagation(); e.preventDefault();
    setSel(b.id);
    drag.current = { id: b.id, resize, x0: e.clientX, y0: e.clientY, start: b, moved: false };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onMove = (e: RPointerEvent) => {
    const d = drag.current;
    if (!d || !design) return;
    const dx = Math.round((e.clientX - d.x0) / scale / (CW + GAP)), dy = Math.round((e.clientY - d.y0) / scale / (CH + GAP));
    const s = d.start;
    const next = clamp(d.resize ? { ...s, w: s.w + dx, h: s.h + dy } : { ...s, x: s.x + dx, y: s.y + dy });
    if (d.resize) { next.x = s.x; next.y = s.y; next.w = Math.min(next.w, COLS - s.x); next.h = Math.min(next.h, ROWS - s.y); }
    const cur = screen?.blocks.find((b) => b.id === d.id);
    if (!cur || (cur.x === next.x && cur.y === next.y && cur.w === next.w && cur.h === next.h)) return;
    if (!d.moved) { d.moved = true; setHistory((h) => [...h.slice(-49), design]); }
    const copy = clone(design);
    const list = copy.screens[screenIdx].blocks;
    list[list.findIndex((b) => b.id === d.id)] = next;
    setDesign(copy); setDirty(true);
  };
  const onUp = () => { drag.current = null; };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    const type = e.dataTransfer.getData("text/x-wall-block") as BlockType;
    if (!TYPES.includes(type)) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / scale - PAD) / (CW + GAP)), y = Math.floor(((e.clientY - r.top) / scale - PAD) / (CH + GAP));
    const [w, h] = SIZE[type];
    addBlock(type, [Math.max(0, Math.min(COLS - w, x)), Math.max(0, Math.min(ROWS - h, y))]);
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName ?? "").toUpperCase();
      if (!block || preview || ["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
      const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (step) { e.preventDefault(); changeBlock({ x: block.x + step[0], y: block.y + step[1] }); }
      if (e.key === "Delete") { changeScreen((s) => { s.blocks = s.blocks.filter((b) => b.id !== block.id); }); setSel(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  /* ---------- saving ---------- */
  const saveDraft = async () => {
    if (!design) return;
    setBusy(true);
    try { await api.put(`/api/livewalls/${wallId}/design/draft`, design); setDirty(false); toast("success", t("designer.draftSaved")); } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const publish = async () => {
    if (!design) return;
    const overlaps = design.screens.some((s) => s.blocks.some((b) => s.blocks.some((o) => o !== b && overlap(o, b))));
    if (overlaps && !window.confirm(t("designer.confirmOverlap"))) return;
    setBusy(true);
    try {
      const r = await api.post<DesignResp>(`/api/livewalls/${wallId}/design/publish`, design);
      setResp(r); setDirty(false); toast("success", t("designer.published"));
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const discard = async () => {
    if (!window.confirm(t("designer.confirmDiscard"))) return;
    try { await api.del(`/api/livewalls/${wallId}/design/draft`); await load(); } catch (e) { fail(e); }
  };
  const useStandard = async () => {
    if (!window.confirm(t("designer.confirmStandard"))) return;
    setBusy(true);
    try { await api.post(`/api/livewalls/${wallId}/design/standard`, {}); await load(); setShowVersions(false); toast("success", t("designer.published")); } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const restore = (v: Version) => {
    if (!v.design || !design) return;
    setHistory((h) => [...h.slice(-49), design]);
    setDesign(clone(v.design)); setDirty(true); setScreenIdx(0); setSel(null); setShowVersions(false);
    toast("success", t("designer.restored", { n: v.version }));
  };

  /* ---------- screens ---------- */
  const addScreen = () => {
    if (!design) return;
    const name = t("designer.newScreenName", { n: design.screens.length + 1 });
    const s: Screen = { id: screenKey(name, design.screens.map((x) => x.id)), name, seconds: 30, background: "neon", blocks: [newBlock("header", 0, 0)] };
    change((d) => { d.screens.push(s); });
    setScreenIdx(design.screens.length); setSel(null);
  };
  const moveScreen = (dir: -1 | 1) => {
    const to = screenIdx + dir;
    if (!design || to < 0 || to >= design.screens.length) return;
    change((d) => { const [s] = d.screens.splice(screenIdx, 1); d.screens.splice(to, 0, s); });
    setScreenIdx(to);
  };
  const removeScreen = () => {
    if (!design || design.screens.length < 2 || !window.confirm(t("designer.confirmRemoveScreen", { name: screen?.name }))) return;
    change((d) => { d.screens.splice(screenIdx, 1); });
    setScreenIdx(Math.max(0, screenIdx - 1)); setSel(null);
  };
  const applyTemplate = (key: "overview" | "stories" | "empty") => {
    if (!resp || !screen) return;
    if (screen.blocks.length && !window.confirm(t("designer.confirmTemplate"))) return;
    const blocks = key === "empty" ? [] : clone(resp.templates[key].blocks).map((b) => ({ ...b, id: uid() }));
    changeScreen((s) => { s.blocks = blocks; });
    setSel(null);
  };

  if (loadError) return <div className="page"><Alert kind="error">{errorText(loadError)}</Alert></div>;
  if (!design || !screen || !resp) return <div className="page"><p className="muted">{t("common.loading")}</p></div>;

  const clashes = new Set(screen.blocks.filter((b) => screen.blocks.some((o) => o !== b && overlap(o, b))).map((b) => b.id));
  const vizLabel = (v: string) => t(`designer.viz.${v}`);
  const channelsFor = (b: Block) => b.type !== "header" && b.type !== "msg";
  const periodsFor = (b: Block): Period[] => b.type === "chart" ? ["hour", "7d", "30d"] : b.type === "kpi" && (b.metric === "views" || b.metric === "interactions") ? ["today", "7d", "30d"] : [];
  const linkFor = wall ? `${wall.url}?screen=${screen.id}` : "";

  return (
    <div className="page wd">
      <div className="wd-top">
        <div className="wd-title">
          <Link to="/admin/livewalls" className="muted small"><ArrowLeft size={14} /> {t("nav.livewalls")}</Link>
          <h1>{t("designer.title", { name: wall?.name ?? "" })}</h1>
        </div>
        <div className="row">
          <span className={`badge${dirty || resp.draft ? " warning" : " good"}`}>
            {dirty ? t("designer.unsaved") : resp.draft ? t("designer.draftState") : resp.custom ? t("designer.liveState", { n: resp.version }) : t("designer.standardState")}
          </span>
          <button className="btn ghost" onClick={undo} disabled={!history.length}><Undo2 /> {t("designer.undo")}</button>
          <button className="btn ghost" onClick={() => setShowVersions(true)}><History /> {t("designer.versions")}</button>
          <button className={`btn secondary${preview ? " active" : ""}`} aria-pressed={preview} onClick={() => { setPreview(!preview); setSel(null); }}>
            {preview ? <Pencil /> : <Eye />} {preview ? t("designer.edit") : t("designer.preview")}
          </button>
          <button className="btn secondary" onClick={saveDraft} disabled={busy}><Save /> {t("designer.saveDraft")}</button>
          <button className="btn" onClick={publish} disabled={busy}><Rocket /> {t("designer.publish")}</button>
        </div>
      </div>

      <div className="wd-tabs" role="tablist">
        {design.screens.map((s, i) => (
          <button key={s.id} role="tab" type="button" className="tab" aria-selected={i === screenIdx} onClick={() => { setScreenIdx(i); setSel(null); }}>
            {s.name} <span className="count">{s.seconds}s</span>
          </button>
        ))}
        {design.screens.length < 10 && <button type="button" className="tab wd-add" onClick={addScreen}><Plus size={14} /> {t("designer.addScreen")}</button>}
      </div>

      <div className="wd-body">
        <aside className="wd-pane">
          <h3>{t("designer.blocks")}</h3>
          <p className="muted small">{t("designer.blocksHint")}</p>
          <div className="wd-lib">
            {TYPES.map((type) => (
              <div key={type} className="wd-blk" draggable onDragStart={(e) => { e.dataTransfer.setData("text/x-wall-block", type); e.dataTransfer.effectAllowed = "copy"; }}>
                <BlockIcon type={type} />
                <span><b>{t(`designer.type.${type}`)}</b><small>{t(`designer.typeHint.${type}`)}</small></span>
                <button type="button" className="btn ghost" aria-label={t("designer.addBlock", { name: t(`designer.type.${type}`) })} title={t("designer.addBlock", { name: t(`designer.type.${type}`) })} onClick={() => addBlock(type)}><Plus /></button>
              </div>
            ))}
          </div>
          <h3><LayoutTemplate size={14} /> {t("designer.templates")}</h3>
          <p className="muted small">{t("designer.templatesHint")}</p>
          <div className="wd-tpl">
            {(["overview", "stories", "empty"] as const).map((k) => (
              <button key={k} type="button" onClick={() => applyTemplate(k)}>
                <span className="wd-thumb">{k !== "empty" && resp.templates[k].blocks.map((b) => (
                  <i key={b.id} style={{ left: `${(b.x / COLS) * 100}%`, top: `${(b.y / ROWS) * 100}%`, width: `${(b.w / COLS) * 100 - 2}%`, height: `${(b.h / ROWS) * 100 - 3}%` }} />
                ))}</span>
                {t(`designer.template.${k}`)}
              </button>
            ))}
          </div>
        </aside>

        <div className="wd-center">
          <div className="wd-frame" ref={wrap} style={{ height: H * scale }}>
            <div className="wd-stage" style={{ transform: `scale(${scale})` }}>
              <iframe ref={frame} src="/api/livewalls/designer-frame" title={t("designer.previewTitle")} onLoad={post} tabIndex={-1} />
              {!preview && (
                <div className="wd-overlay" onPointerMove={onMove} onPointerUp={onUp} onPointerDown={() => setSel(null)}
                  onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
                  {Array.from({ length: COLS * ROWS }, (_, i) => (
                    <i key={i} className="wd-cell" style={{ left: PAD + (i % COLS) * (CW + GAP), top: PAD + Math.floor(i / COLS) * (CH + GAP), width: CW, height: CH }} />
                  ))}
                  {screen.blocks.map((b) => (
                    <div key={b.id} className={`wd-box${b.id === sel ? " sel" : ""}${clashes.has(b.id) ? " clash" : ""}`}
                      style={{ left: PAD + b.x * (CW + GAP), top: PAD + b.y * (CH + GAP), width: b.w * CW + (b.w - 1) * GAP, height: b.h * CH + (b.h - 1) * GAP }}
                      onPointerDown={(e) => onDown(e, b, false)}>
                      <span className="wd-tag">{b.title || t(`designer.type.${b.type}`)}</span>
                      <span className="wd-rz" onPointerDown={(e) => onDown(e, b, true)} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="wd-status muted small">
            <span>1920 × 1080 · {t("designer.grid")}</span>
            {clashes.size > 0 && <span className="wd-warn">{t("designer.overlap")}</span>}
            {!snapshot && <span>{t("designer.noData")}</span>}
            {resp.draft && !dirty && <button type="button" className="link-btn" onClick={discard}>{t("designer.discard")}</button>}
          </div>
        </div>

        <aside className="wd-pane wd-props">
          {block ? (
            <div className="stack">
              <div className="wd-ph">
                <BlockIcon type={block.type} />
                <b>{t(`designer.type.${block.type}`)}</b>
                <button type="button" className="btn ghost" title={t("designer.duplicate")} aria-label={t("designer.duplicate")}
                  onClick={() => { const [x, y, w, h] = freeSpot(screen.blocks, block.w, block.h); const c = { ...clone(block), id: uid(), x, y, w, h }; changeScreen((s) => { s.blocks.push(c); }); setSel(c.id); }}><Copy /></button>
                <button type="button" className="btn ghost" title={t("common.delete")} aria-label={t("common.delete")}
                  onClick={() => { changeScreen((s) => { s.blocks = s.blocks.filter((b) => b.id !== block.id); }); setSel(null); }}><Trash2 /></button>
              </div>
              {block.type === "msg" ? (
                <>
                  <Field label={t("designer.text")}><input maxLength={200} value={block.text} onChange={(e) => changeBlock({ text: e.target.value })} /></Field>
                  <Field label={t("designer.subText")}><input maxLength={300} value={block.sub} onChange={(e) => changeBlock({ sub: e.target.value })} /></Field>
                </>
              ) : (
                <Field label={t("designer.blockTitle")} hint={t("designer.blockTitleHint")}>
                  <input maxLength={120} value={block.title} placeholder={block.type === "header" ? wall?.title || wall?.name : ""} onChange={(e) => changeBlock({ title: e.target.value })} />
                </Field>
              )}
              {(block.type === "kpi" || block.type === "chart") && (
                <Field label={t("designer.metric")}>
                  <select value={block.metric} onChange={(e) => {
                    const metric = e.target.value as Metric;
                    changeBlock({ metric, period: metric === "live" || metric === "followers" ? "today" : block.period === "hour" && block.type === "kpi" ? "today" : block.period });
                  }}>
                    {(block.type === "kpi" ? ["live", "views", "interactions", "followers"] : ["views", "interactions"]).map((m) => <option key={m} value={m}>{t(`designer.metrics.${m}`)}</option>)}
                  </select>
                </Field>
              )}
              {periodsFor(block).length > 0 && (
                <div className="field"><span>{t("designer.period")}</span>
                  <div className="seg">{periodsFor(block).map((p) => <button key={p} type="button" aria-pressed={block.period === p} onClick={() => changeBlock({ period: p })}>{t(`designer.periods.${p}`)}</button>)}</div>
                </div>
              )}
              {channelsFor(block) && (
                <div className="field"><span>{t("designer.channels")}</span>
                  <div className="chips">
                    <button type="button" className="chip" aria-pressed={!block.channels.length} onClick={() => changeBlock({ channels: [] })}>{t("designer.allChannels")}</button>
                    {sources.map((s) => (
                      <button key={s.id} type="button" className="chip" aria-pressed={block.channels.includes(s.id)}
                        onClick={() => changeBlock({ channels: block.channels.includes(s.id) ? block.channels.filter((x) => x !== s.id) : [...block.channels, s.id] })}>
                        {kindIcon(s.kind)} {s.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {VIZ[block.type] && (
                <div className="field"><span>{t("designer.showAs")}</span>
                  <div className="seg">{VIZ[block.type]!.map((v) => <button key={v} type="button" aria-pressed={block.viz === v} onClick={() => changeBlock({ viz: v })}>{vizLabel(v)}</button>)}</div>
                </div>
              )}
              {block.type !== "header" && (
                <div className="field"><span>{t("designer.colour")}</span>
                  <div className="wd-sw">
                    <button type="button" className="wd-auto" aria-pressed={block.color === "auto"} onClick={() => changeBlock({ color: "auto" })}>{t("designer.autoColour")}</button>
                    {SWATCHES.map((c) => <button key={c} type="button" aria-pressed={block.color.toLowerCase() === c.toLowerCase()} aria-label={c} title={c} style={{ background: c }} onClick={() => changeBlock({ color: c })} />)}
                    <input type="color" aria-label={t("designer.ownColour")} value={block.color === "auto" ? "#2fb8ff" : block.color} onChange={(e) => changeBlock({ color: e.target.value })} />
                  </div>
                </div>
              )}
              {block.type === "kpi" && <Switch checked={block.trend} onChange={(v) => changeBlock({ trend: v })} label={t("designer.trend")} />}
              {["kpi", "tiles", "race"].includes(block.type) && <Switch checked={block.countup} onChange={(v) => changeBlock({ countup: v })} label={t("designer.countup")} />}
              {block.type === "race" && <Switch checked={block.editors} onChange={(v) => changeBlock({ editors: v })} label={t("designer.editors")} />}
              {ROWS_FOR.includes(block.type) && (
                <Field label={t("designer.rows")} hint={t("designer.rowsHint")}><input type="number" min={1} max={10} value={block.rows} onChange={(e) => changeBlock({ rows: Math.max(1, Math.min(10, Number(e.target.value) || 1)) })} /></Field>
              )}
              <div className="field"><span>{t("designer.position")}</span>
                <div className="wd-pos">
                  {(["x", "y", "w", "h"] as const).map((k) => (
                    <label key={k}>{t(`designer.pos.${k}`)}<input type="number" min={k === "w" || k === "h" ? 1 : 0} max={k === "x" || k === "w" ? COLS : ROWS} value={block[k]} onChange={(e) => changeBlock({ [k]: Number(e.target.value) })} /></label>
                  ))}
                </div>
                <small>{t("designer.keysHint")}</small>
              </div>
            </div>
          ) : (
            <div className="stack">
              <h3>{t("designer.screenSettings")}</h3>
              <p className="muted small">{t("designer.nothingSelected")}</p>
              <Field label={t("designer.screenName")}><input maxLength={60} value={screen.name} onChange={(e) => changeScreen((s) => { s.name = e.target.value || "–"; })} /></Field>
              <Field label={t("designer.seconds")} hint={t("designer.secondsHint")}><input type="number" min={10} max={300} value={screen.seconds} onChange={(e) => changeScreen((s) => { s.seconds = Math.max(10, Math.min(300, Number(e.target.value) || 30)); })} /></Field>
              <div className="field"><span>{t("designer.background")}</span>
                <div className="seg">{(["neon", "aurora", "plain"] as const).map((bg) => <button key={bg} type="button" aria-pressed={screen.background === bg} onClick={() => changeScreen((s) => { s.background = bg; })}>{t(`designer.backgrounds.${bg}`)}</button>)}</div>
              </div>
              <Field label={t("designer.screenLink")} hint={t("designer.screenLinkHint")}><input readOnly value={linkFor} onFocus={(e) => e.target.select()} /></Field>
              <div className="row">
                <button type="button" className="btn secondary" disabled={screenIdx === 0} onClick={() => moveScreen(-1)} aria-label={t("designer.moveLeft")} title={t("designer.moveLeft")}><ArrowLeft /></button>
                <button type="button" className="btn secondary" disabled={screenIdx === design.screens.length - 1} onClick={() => moveScreen(1)} aria-label={t("designer.moveRight")} title={t("designer.moveRight")}><ArrowRight /></button>
                <button type="button" className="btn secondary" disabled={design.screens.length < 2} onClick={removeScreen}><Trash2 /> {t("designer.removeScreen")}</button>
              </div>
              <p className="muted small">{t("designer.coloursFrom")}</p>
            </div>
          )}
        </aside>
      </div>

      {showVersions && (
        <Modal title={t("designer.versions")} onClose={() => setShowVersions(false)}>
          <div className="stack">
            <p className="muted">{t("designer.versionsText")}</p>
            {!resp.versions.length && <p className="muted small">{t("designer.noVersions")}</p>}
            <ul className="wd-versions">
              {resp.versions.map((v) => (
                <li key={v.version}>
                  <span><b>{t("designer.versionN", { n: v.version })}</b>{v.version === resp.version && <span className="badge good">{t("designer.onTheTvs")}</span>}<br />
                    <small className="muted">{v.created_at ? new Date(v.created_at).toLocaleString(i18n.language) : ""}{v.created_by ? ` · ${v.created_by}` : ""}</small></span>
                  <button type="button" className="btn secondary" onClick={() => restore(v)}>{t("designer.restore")}</button>
                </li>
              ))}
            </ul>
            <div className="row end">
              {resp.custom && <button type="button" className="btn secondary" onClick={useStandard} disabled={busy}>{t("designer.useStandard")}</button>}
              <button type="button" className="btn" onClick={() => setShowVersions(false)}>{t("common.close")}</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
