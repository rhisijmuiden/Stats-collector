import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Send } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { Alert, Card, Field, PageHead, Switch, useLoad } from "../components/ui";

interface EmailCfg {
  enabled: boolean; host: string; port: number; security: "starttls" | "ssl" | "none";
  auth: "password" | "xoauth2" | "none"; username: string; password_set: boolean;
  oauth_token_url: string; oauth_client_id: string; oauth_client_secret_set: boolean; oauth_scope: string;
  from_address: string; from_name: string; reply_to: string; verify_tls: boolean; timeout: number;
}

const PRESETS: Record<string, Partial<EmailCfg>> = {
  m365: { host: "smtp.office365.com", port: 587, security: "starttls" },
  google: { host: "smtp.gmail.com", port: 587, security: "starttls" },
  ssl: { port: 465, security: "ssl" },
};

export default function Email() {
  const { t } = useTranslation();
  const { user, toast } = useApp();
  const loaded = useLoad(() => api.get<EmailCfg>("/api/settings/email"));
  const [cfg, setCfg] = useState<EmailCfg | null>(null);
  const [password, setPassword] = useState("");
  const [secret, setSecret] = useState("");
  const [to, setTo] = useState(user?.email ?? "");
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (loaded.data) setCfg(loaded.data); }, [loaded.data]);
  if (!cfg) return <div className="page"><PageHead help="email" title={t("email.title")} /></div>;
  const set = <K extends keyof EmailCfg>(k: K, v: EmailCfg[K]) => setCfg({ ...cfg, [k]: v });

  const save = async (e?: FormEvent) => {
    e?.preventDefault();
    try {
      const r = await api.put<EmailCfg>("/api/settings/email", {
        ...cfg, password: password || undefined, oauth_client_secret: secret || undefined,
      });
      setCfg(r); setPassword(""); setSecret("");
      toast("success", t("common.saved"));
      return true;
    } catch (err) {
      toast("error", errorText(err instanceof ApiError ? err.detail : String(err)));
      return false;
    }
  };

  const test = async () => {
    setBusy(true); setTestResult(null);
    if (await save()) {
      try {
        await api.post("/api/settings/email/test", { to });
        setTestResult({ ok: true, text: t("email.testOk", { to }) });
      } catch (err) {
        setTestResult({ ok: false, text: errorText(err instanceof ApiError ? err.detail : String(err)) });
      }
    }
    setBusy(false);
  };

  return (
    <form className="page" onSubmit={save}>
      <PageHead help="email" title={t("email.title")} subtitle={t("email.subtitle")} actions={<button className="btn">{t("common.save")}</button>} />
      <Card title={t("email.server")} actions={<Switch checked={cfg.enabled} onChange={(v) => set("enabled", v)} label={t("email.enabled")} />}>
        <div className="stack">
          <div className="row small">
            <span className="muted">{t("email.presets")}:</span>
            <button type="button" className="btn secondary" onClick={() => setCfg({ ...cfg, ...PRESETS.m365 })}>Microsoft 365</button>
            <button type="button" className="btn secondary" onClick={() => setCfg({ ...cfg, ...PRESETS.google })}>Google Workspace</button>
            <button type="button" className="btn secondary" onClick={() => setCfg({ ...cfg, ...PRESETS.ssl })}>SMTPS (465)</button>
          </div>
          <div className="grid three">
            <Field label={t("email.host")}><input value={cfg.host} onChange={(e) => set("host", e.target.value)} placeholder="smtp.example.org" /></Field>
            <Field label={t("email.port")}><input type="number" value={cfg.port} onChange={(e) => set("port", Number(e.target.value))} /></Field>
            <Field label={t("email.security")}>
              <select value={cfg.security} onChange={(e) => set("security", e.target.value as EmailCfg["security"])}>
                <option value="starttls">STARTTLS</option>
                <option value="ssl">SSL/TLS (SMTPS)</option>
                <option value="none">{t("email.noEncryption")}</option>
              </select>
            </Field>
          </div>
          {cfg.security === "none" && <Alert kind="warning">{t("email.noEncryptionWarning")}</Alert>}
          <Switch checked={cfg.verify_tls} onChange={(v) => set("verify_tls", v)} label={t("email.verifyTls")} />
        </div>
      </Card>
      <Card title={t("email.authentication")}>
        <div className="stack">
          <div className="seg">
            {(["password", "xoauth2", "none"] as const).map((a) => (
              <button key={a} type="button" aria-pressed={cfg.auth === a} onClick={() => set("auth", a)}>{t(`email.auth.${a}`)}</button>
            ))}
          </div>
          {cfg.auth !== "none" && (
            <div className="grid two">
              <Field label={t("email.username")}><input value={cfg.username} autoComplete="off" onChange={(e) => set("username", e.target.value)} /></Field>
              {cfg.auth === "password" && (
                <Field label={t("email.password")} hint={cfg.password_set ? t("common.secretKept") : undefined}>
                  <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={cfg.password_set ? "••••••••" : ""} />
                </Field>
              )}
            </div>
          )}
          {cfg.auth === "xoauth2" && (
            <div className="grid two">
              <Field label={t("email.tokenUrl")} hint={t("email.tokenUrlHint")}><input value={cfg.oauth_token_url} onChange={(e) => set("oauth_token_url", e.target.value)} placeholder="https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token" /></Field>
              <Field label={t("email.scope")}><input value={cfg.oauth_scope} onChange={(e) => set("oauth_scope", e.target.value)} /></Field>
              <Field label={t("email.clientId")}><input value={cfg.oauth_client_id} onChange={(e) => set("oauth_client_id", e.target.value)} /></Field>
              <Field label={t("email.clientSecret")} hint={cfg.oauth_client_secret_set ? t("common.secretKept") : undefined}>
                <input type="password" autoComplete="new-password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={cfg.oauth_client_secret_set ? "••••••••" : ""} />
              </Field>
            </div>
          )}
        </div>
      </Card>
      <Card title={t("email.sender")}>
        <div className="grid three">
          <Field label={t("email.fromAddress")}><input type="email" value={cfg.from_address} onChange={(e) => set("from_address", e.target.value)} /></Field>
          <Field label={t("email.fromName")}><input value={cfg.from_name} onChange={(e) => set("from_name", e.target.value)} /></Field>
          <Field label={t("email.replyTo")}><input type="email" value={cfg.reply_to} onChange={(e) => set("reply_to", e.target.value)} /></Field>
        </div>
      </Card>
      <Card title={t("email.test")} subtitle={t("email.testIntro")}>
        <div className="stack">
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <input type="email" value={to} onChange={(e) => setTo(e.target.value)} aria-label={t("email.testTo")} />
            <button type="button" className="btn secondary" onClick={test} disabled={busy || !to}><Send /> {t("email.sendTest")}</button>
          </div>
          {testResult && <Alert kind={testResult.ok ? "success" : "error"}>{testResult.text}</Alert>}
        </div>
      </Card>
    </form>
  );
}
