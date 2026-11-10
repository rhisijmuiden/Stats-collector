import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useSearchParams } from "react-router-dom";
import { api, ApiError, type User } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { Alert, Field, Toasts } from "../components/ui";
import { Brand, LanguageToggle } from "../components/Layout";

export function Login() {
  const { t } = useTranslation();
  const { user, setSession, needsSetup } = useApp();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ user: User; csrf_token: string }>("/api/auth/login", {
        email, password, totp: needTotp ? totp : undefined,
      });
      setSession(r.user, r.csrf_token);
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail : String(err);
      if (detail === "totp_required") setNeedTotp(true);
      else setError(errorText(detail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <form className="card stack" onSubmit={submit}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <Brand />
          <LanguageToggle compact />
        </div>
        <div>
          <h1>{t("auth.signIn")}</h1>
          <p className="muted">{t("auth.signInIntro")}</p>
        </div>
        {needsSetup && <Alert kind="warning">{t("auth.needsSetup")}</Alert>}
        {error && <Alert kind="error">{error}</Alert>}
        <Field label={t("auth.email")}>
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label={t("auth.password")}>
          <input type="password" autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {needTotp && (
          <Field label={t("auth.totpCode")} hint={t("auth.totpHint")}>
            <input inputMode="numeric" autoComplete="one-time-code" autoFocus value={totp}
              onChange={(e) => setTotp(e.target.value)} />
          </Field>
        )}
        <button className="btn" disabled={busy}>{t("auth.signIn")}</button>
        <button type="button" className="btn secondary" disabled title={t("auth.ssoSoon")}>
          {t("auth.signInMicrosoft")}
        </button>
      </form>
      <Toasts />
    </div>
  );
}

export function Setup() {
  const { t, i18n } = useTranslation();
  const { setSession, user } = useApp();
  const [params] = useSearchParams();
  const [form, setForm] = useState({ display_name: "", email: "", password: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const token = params.get("token") ?? "";
  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (form.password !== form.confirm) return setError(t("errors.passwords_differ"));
    try {
      const r = await api.post<{ user: User; csrf_token: string }>("/api/auth/setup", {
        token, email: form.email, display_name: form.display_name, password: form.password, language: i18n.language,
      });
      setSession(r.user, r.csrf_token);
    } catch (err) {
      setError(errorText(err instanceof ApiError ? err.detail : String(err)));
    }
  };
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="auth">
      <form className="card stack" onSubmit={submit}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <Brand />
          <LanguageToggle compact />
        </div>
        <div>
          <h1>{t("setup.title")}</h1>
          <p className="muted">{t("setup.intro")}</p>
        </div>
        {!token && <Alert kind="error">{t("setup.noToken")}</Alert>}
        {error && <Alert kind="error">{error}</Alert>}
        <Field label={t("users.name")}><input required value={form.display_name} onChange={set("display_name")} /></Field>
        <Field label={t("auth.email")}><input type="email" required value={form.email} onChange={set("email")} /></Field>
        <Field label={t("auth.password")} hint={t("auth.passwordRule")}>
          <input type="password" autoComplete="new-password" required minLength={12} value={form.password} onChange={set("password")} />
        </Field>
        <Field label={t("auth.confirmPassword")}>
          <input type="password" autoComplete="new-password" required value={form.confirm} onChange={set("confirm")} />
        </Field>
        <button className="btn" disabled={!token}>{t("setup.create")}</button>
      </form>
    </div>
  );
}
