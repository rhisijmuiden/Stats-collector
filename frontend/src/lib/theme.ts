export interface Palette {
  background: string;
  surface: string;
  sidebar: string;
  sidebarText: string;
  text: string;
  muted: string;
  border: string;
  accent: string;
  accentSoft: string;
  good: string;
  warning: string;
  critical: string;
}

export interface Theme {
  app_name: string;
  colors: { light: Palette; dark: Palette };
  channels: Record<string, string>;
  fonts: { heading: { family: string; fallback: string }; body: { family: string; fallback: string } };
  radius: { card: number; control: number };
  assets?: { logo_light: string | null; logo_dark: string | null; favicon: string | null };
}

export type Mode = "light" | "dark";
export type ModePref = "system" | Mode;

const VARS: Record<keyof Palette, string> = {
  background: "--bg",
  surface: "--surface",
  sidebar: "--sidebar",
  sidebarText: "--sidebar-text",
  text: "--text",
  muted: "--muted",
  border: "--border",
  accent: "--accent",
  accentSoft: "--accent-soft",
  good: "--good",
  warning: "--warning",
  critical: "--critical",
};

/** Black or white text, whichever has more contrast on the given colour. */
export function contrastText(hex: string): string {
  const n = parseInt(hex.replace("#", ""), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.4 ? "#0b1220" : "#ffffff";
}

export function resolveMode(pref: ModePref): Mode {
  if (pref !== "system") return pref;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const fontStack = (f: { family: string; fallback: string }, variable: boolean) =>
  `"${f.family}${variable ? " Variable" : ""}", "${f.family}", ${f.fallback}`;

export function applyTheme(theme: Theme, mode: Mode) {
  const root = document.documentElement;
  root.dataset.mode = mode;
  const p = theme.colors[mode];
  for (const [key, cssVar] of Object.entries(VARS)) {
    const value = p[key as keyof Palette];
    if (value) root.style.setProperty(cssVar, value);
  }
  root.style.setProperty("--surface-2", `color-mix(in srgb, ${p.surface} 70%, ${p.background})`);
  root.style.setProperty("--accent-contrast", contrastText(p.accent));
  root.style.setProperty("--radius-card", `${theme.radius?.card ?? 12}px`);
  root.style.setProperty("--radius-control", `${theme.radius?.control ?? 8}px`);
  if (theme.fonts) {
    root.style.setProperty("--font-heading", fontStack(theme.fonts.heading, true));
    root.style.setProperty("--font-body", fontStack(theme.fonts.body, true));
  }
  for (const [ch, color] of Object.entries(theme.channels ?? {})) root.style.setProperty(`--c-${ch}`, color);
  document.title = theme.app_name || "Stats Collector";
  const icon = document.querySelector<HTMLLinkElement>("link[rel=icon]");
  if (icon) icon.href = theme.assets?.favicon || "/favicon.svg";
}
