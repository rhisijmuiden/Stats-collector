import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, RotateCcw, Upload } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import type { Palette, Theme } from "../lib/theme";
import { Card, Field, PageHead, useLoad } from "../components/ui";

interface BrandingData { app_name: string; overrides: Partial<Theme>; default: Theme; effective: Theme }
const KEYS: (keyof Palette)[] = ["accent", "accentSoft", "background", "surface", "sidebar", "sidebarText", "text", "muted", "border", "good", "warning", "critical"];

export default function Branding() {
  const { t } = useTranslation();
  const { toast, reloadTheme } = useApp();
  const loaded = useLoad(() => api.get<BrandingData>("/api/settings/branding"));
  const [theme, setTheme] = useState<Theme | null>(null);
  const [mode, setMode] = useState<"light" | "dark">("light");
  useEffect(() => { if (loaded.data) setTheme(structuredClone(loaded.data.effective)); }, [loaded.data]);
  if (!theme || !loaded.data) return <div className="page"><PageHead help="branding" title={t("branding.title")} /></div>;
  const p = theme.colors[mode];
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const setColor = (k: keyof Palette, v: string) =>
    setTheme({ ...theme, colors: { ...theme.colors, [mode]: { ...theme.colors[mode], [k]: v.toUpperCase() } } });

  const save = async () => {
    try {
      const r = await api.put<Theme>("/api/settings/branding", {
        app_name: theme.app_name,
        overrides: { colors: theme.colors, channels: theme.channels, fonts: theme.fonts, radius: theme.radius },
      });
      await reloadTheme(r);
      toast("success", t("common.saved"));
    } catch (e) { fail(e); }
  };

  const reset = () => setTheme({ ...structuredClone(loaded.data!.default), app_name: theme.app_name, assets: theme.assets });

  const upload = async (kind: "logo_light" | "logo_dark" | "favicon", file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.post<Theme>(`/api/settings/branding/${kind}`, fd);
      setTheme({ ...theme, assets: r.assets });
      await reloadTheme(r);
    } catch (e) { fail(e); }
  };

  const exportBrand = () => {
    const { assets: _assets, ...rest } = theme;
    void _assets;
    const blob = new Blob([JSON.stringify({ ...rest, name: theme.app_name, version: 1 }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "theme.json";
    a.click();
  };

  const importBrand = async (file: File) => {
    try {
      const data = JSON.parse(await file.text());
      setTheme({ ...theme, colors: data.colors ?? theme.colors, channels: data.channels ?? theme.channels, fonts: data.fonts ?? theme.fonts, radius: data.radius ?? theme.radius });
      toast("success", t("branding.imported"));
    } catch { toast("error", t("branding.importFailed")); }
  };

  return (
    <div className="page">
      <PageHead help="branding" title={t("branding.title")} subtitle={t("branding.subtitle")} actions={
        <>
          <button className="btn ghost" onClick={reset}><RotateCcw /> {t("branding.reset")}</button>
          <button className="btn" onClick={save}>{t("common.save")}</button>
        </>
      } />
      <div className="grid two">
        <Card title={t("branding.identity")}>
          <div className="stack">
            <Field label={t("branding.appName")}><input value={theme.app_name} onChange={(e) => setTheme({ ...theme, app_name: e.target.value })} /></Field>
            {(["logo_light", "logo_dark", "favicon"] as const).map((kind) => (
              <div key={kind} className="row" style={{ justifyContent: "space-between" }}>
                <div className="row">
                  <div style={{ width: 64, height: 40, borderRadius: 8, display: "grid", placeItems: "center", background: kind === "logo_dark" ? "#0F1B2D" : "var(--surface-2)", border: "1px solid var(--border)" }}>
                    {theme.assets?.[kind] ? <img src={`${theme.assets[kind]}?v=${Date.now()}`} alt="" style={{ maxHeight: 28, maxWidth: 56 }} /> : <span className="muted small">–</span>}
                  </div>
                  <div><b>{t(`branding.${kind}`)}</b><div className="muted small">{t("branding.fileTypes")}</div></div>
                </div>
                <div className="row">
                  <label className="btn secondary"><Upload /> {t("branding.upload")}
                    <input type="file" hidden accept=".svg,.png,.webp,.ico" onChange={(e) => e.target.files?.[0] && upload(kind, e.target.files[0])} />
                  </label>
                  {theme.assets?.[kind] && <button className="btn ghost" onClick={async () => { const r = await api.del<Theme>(`/api/settings/branding/${kind}`); setTheme({ ...theme, assets: r.assets }); reloadTheme(r); }}>{t("common.delete")}</button>}
                </div>
              </div>
            ))}
            <div className="row">
              <button className="btn secondary" onClick={exportBrand}><Download /> {t("branding.export")}</button>
              <label className="btn secondary"><Upload /> {t("branding.import")}
                <input type="file" hidden accept="application/json" onChange={(e) => e.target.files?.[0] && importBrand(e.target.files[0])} />
              </label>
            </div>
            <p className="muted small">{t("branding.repoHint")}</p>
          </div>
        </Card>
        <Card title={t("branding.preview")} actions={
          <div className="seg">{(["light", "dark"] as const).map((m) => <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}>{t(`profile.themes.${m}`)}</button>)}</div>
        }>
          <div className="preview" style={{ background: p.background, fontFamily: "var(--font-body)" }}>
            <div className="pv-side" style={{ background: p.sidebar }}>
              <i style={{ background: p.accent, opacity: 1, height: 18, width: 18, borderRadius: 5 }} />
              {[1, 2, 3, 4].map((n) => <i key={n} style={{ background: p.sidebarText }} />)}
            </div>
            <div className="pv-main">
              <b style={{ color: p.text, fontFamily: "var(--font-heading)", fontSize: 16 }}>{theme.app_name}</b>
              <div style={{ background: p.surface, border: `1px solid ${p.border}`, borderRadius: theme.radius.card, padding: 12, display: "grid", gap: 8 }}>
                <span style={{ color: p.muted, fontSize: 12 }}>{t("branding.sample")}</span>
                <div style={{ display: "flex", gap: 6, alignItems: "flex-end", height: 48 }}>
                  {Object.values(theme.channels).map((c, i) => <span key={i} style={{ flex: 1, background: c, height: `${30 + ((i * 37) % 70)}%`, borderRadius: 4 }} />)}
                </div>
                <span style={{ background: p.accent, color: "#fff", borderRadius: theme.radius.control, padding: "5px 10px", fontSize: 12, width: "fit-content", fontWeight: 600 }}>{t("common.save")}</span>
              </div>
            </div>
          </div>
        </Card>
      </div>
      <Card title={t("branding.colors", { mode: t(`profile.themes.${mode}`) })}>
        <div className="grid three">
          {KEYS.map((k) => (
            <Field key={k} label={t(`branding.palette.${k}`)}>
              <div className="swatch-row">
                <input type="color" value={p[k]} onChange={(e) => setColor(k, e.target.value)} />
                <input value={p[k]} onChange={(e) => setColor(k, e.target.value)} />
              </div>
            </Field>
          ))}
        </div>
      </Card>
      <div className="grid two">
        <Card title={t("branding.channelColors")}>
          <div className="grid two">
            {Object.entries(theme.channels).map(([ch, color]) => (
              <Field key={ch} label={t(`channels.${ch}`)}>
                <div className="swatch-row">
                  <input type="color" value={color} onChange={(e) => setTheme({ ...theme, channels: { ...theme.channels, [ch]: e.target.value.toUpperCase() } })} />
                  <input value={color} onChange={(e) => setTheme({ ...theme, channels: { ...theme.channels, [ch]: e.target.value } })} />
                </div>
              </Field>
            ))}
          </div>
        </Card>
        <Card title={t("branding.typography")}>
          <div className="stack">
            <Field label={t("branding.headingFont")}>
              <select value={theme.fonts.heading.family} onChange={(e) => setTheme({ ...theme, fonts: { ...theme.fonts, heading: { ...theme.fonts.heading, family: e.target.value } } })}>
                {["Space Grotesk", "Inter", "system-ui"].map((f) => <option key={f}>{f}</option>)}
              </select>
            </Field>
            <Field label={t("branding.bodyFont")}>
              <select value={theme.fonts.body.family} onChange={(e) => setTheme({ ...theme, fonts: { ...theme.fonts, body: { ...theme.fonts.body, family: e.target.value } } })}>
                {["Inter", "Space Grotesk", "system-ui"].map((f) => <option key={f}>{f}</option>)}
              </select>
            </Field>
            <div className="grid two">
              <Field label={t("branding.radiusCard")}><input type="number" min={0} max={24} value={theme.radius.card} onChange={(e) => setTheme({ ...theme, radius: { ...theme.radius, card: Number(e.target.value) } })} /></Field>
              <Field label={t("branding.radiusControl")}><input type="number" min={0} max={16} value={theme.radius.control} onChange={(e) => setTheme({ ...theme, radius: { ...theme.radius, control: Number(e.target.value) } })} /></Field>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
