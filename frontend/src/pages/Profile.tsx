import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError, type User } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { Alert, Card, Field, PageHead } from "../components/ui";
import { LanguageToggle } from "../components/Layout";

export default function Profile() {
  const { t } = useTranslation();
  const { user, setUser, toast } = useApp();
  const [name, setName] = useState(user?.display_name ?? "");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [totp, setTotp] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  if (!user) return null;
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const saveProfile = async (patch: Partial<User>) => {
    try { setUser(await api.patch<User>("/api/auth/me", patch)); toast("success", t("common.saved")); } catch (e) { fail(e); }
  };
  const changePw = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post("/api/auth/password", pw); setPw({ current_password: "", new_password: "" }); toast("success", t("profile.passwordChanged")); } catch (err) { fail(err); }
  };

  return (
    <div className="page">
      <PageHead help="users-and-roles" title={t("profile.title")} subtitle={user.email} />
      <div className="grid two">
        <Card title={t("profile.personal")}>
          <div className="stack">
            <Field label={t("users.name")}>
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input value={name} onChange={(e) => setName(e.target.value)} />
                <button className="btn secondary" onClick={() => saveProfile({ display_name: name })}>{t("common.save")}</button>
              </div>
            </Field>
            <div className="field"><span>{t("profile.language")}</span><LanguageToggle /></div>
            <div className="field"><span>{t("profile.theme")}</span>
              <div className="seg">
                {(["system", "light", "dark"] as const).map((m) => <button key={m} aria-pressed={user.theme === m} onClick={() => saveProfile({ theme: m })}>{t(`profile.themes.${m}`)}</button>)}
              </div>
            </div>
            <dl className="kv"><dt>{t("users.role")}</dt><dd>{t(`roles.${user.role}`)}</dd></dl>
          </div>
        </Card>
        {user.auth_provider === "local" && (
          <Card title={t("profile.password")}>
            <form className="stack" onSubmit={changePw}>
              <Field label={t("profile.currentPassword")}><input type="password" autoComplete="current-password" required value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
              <Field label={t("users.newPassword")} hint={t("auth.passwordRule")}><input type="password" autoComplete="new-password" minLength={12} required value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
              <div className="row end"><button className="btn">{t("profile.changePassword")}</button></div>
            </form>
          </Card>
        )}
      </div>
      {user.auth_provider === "local" && (
        <Card title={t("profile.twoFactor")} subtitle={t("profile.twoFactorIntro")}>
          {user.totp_enabled ? (
            <div className="stack">
              <Alert kind="success">{t("profile.twoFactorOn")}</Alert>
              <form className="row" onSubmit={async (e) => { e.preventDefault(); try { setUser(await api.post<User>("/api/auth/totp/disable", { current_password: pw.current_password, new_password: "" })); } catch (err) { fail(err); } }}>
                <input type="password" placeholder={t("profile.currentPassword")} value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} style={{ maxWidth: 260 }} />
                <button className="btn secondary">{t("profile.disable2fa")}</button>
              </form>
            </div>
          ) : totp ? (
            <div className="stack">
              <p>{t("profile.scanOrType")}</p>
              <code style={{ fontSize: 15, letterSpacing: 1 }}>{totp.secret.match(/.{1,4}/g)?.join(" ")}</code>
              <a href={totp.otpauth_uri}>{t("profile.openAuthenticator")}</a>
              <div className="row" style={{ flexWrap: "nowrap", maxWidth: 360 }}>
                <input inputMode="numeric" placeholder="123456" value={code} onChange={(e) => setCode(e.target.value)} />
                <button className="btn" onClick={async () => { try { setUser(await api.post<User>("/api/auth/totp/enable", { secret: totp.secret, code })); setTotp(null); } catch (err) { fail(err); } }}>{t("profile.confirm")}</button>
              </div>
            </div>
          ) : (
            <button className="btn secondary" onClick={async () => setTotp(await api.get("/api/auth/totp/setup"))}>{t("profile.enable2fa")}</button>
          )}
        </Card>
      )}
    </div>
  );
}
