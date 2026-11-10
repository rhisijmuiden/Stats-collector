import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setCsrf, type User } from "./api";
import { applyTheme, resolveMode, type Theme } from "./theme";
import { setLanguage } from "../i18n";

interface Toast {
  id: number;
  kind: "success" | "error";
  text: string;
}

interface AppState {
  user: User | null;
  loading: boolean;
  theme: Theme | null;
  needsSetup: boolean;
  setSession: (user: User, csrf: string) => void;
  setUser: (user: User) => void;
  logout: () => Promise<void>;
  reloadTheme: (t?: Theme) => Promise<void>;
  toasts: Toast[];
  toast: (kind: Toast["kind"], text: string) => void;
}

const Ctx = createContext<AppState | null>(null);

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside provider");
  return v;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [theme, setTheme] = useState<Theme | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 8000 : 4000);
  }, []);

  const reloadTheme = useCallback(async (t?: Theme) => {
    setTheme(t ?? (await api.get<Theme>("/api/branding")));
  }, []);

  const setUser = useCallback((u: User) => {
    setUserState(u);
    setLanguage(u.language);
  }, []);

  const setSession = useCallback(
    (u: User, csrf: string) => {
      setCsrf(csrf);
      setUser(u);
      setNeedsSetup(false);
    },
    [setUser],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/api/auth/logout");
    } finally {
      setUserState(null);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [status] = await Promise.all([
          api.get<{ needs_setup: boolean; default_language: "en" | "nl" }>("/api/auth/status"),
          reloadTheme().catch(() => undefined),
        ]);
        setNeedsSetup(status.needs_setup);
        try {
          const me = await api.get<{ user: User; csrf_token: string }>("/api/auth/me");
          setSession(me.user, me.csrf_token);
        } catch {
          /* not logged in */
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [reloadTheme, setSession]);

  // Apply brand colours for the user's light/dark preference, and follow the OS when set to "system".
  useEffect(() => {
    if (!theme) return;
    const pref = user?.theme ?? "system";
    const apply = () => applyTheme(theme, resolveMode(pref));
    apply();
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener("change", apply);
    return () => mq?.removeEventListener("change", apply);
  }, [theme, user?.theme]);

  const value = useMemo(
    () => ({ user, loading, theme, needsSetup, setSession, setUser, logout, reloadTheme, toasts, toast }),
    [user, loading, theme, needsSetup, setSession, setUser, logout, reloadTheme, toasts, toast],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
