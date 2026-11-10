import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Copy } from "lucide-react";
import { api, ApiError, type Role } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { Alert, Card, Field, PageHead, Switch, useLoad } from "../components/ui";

interface Sso {
  enabled: boolean; tenant_id: string; client_id: string; client_secret_set: boolean; allow_local_login: boolean;
  group_roles: Record<Role, string>; default_role: Role; redirect_uri: string;
}
const ROLES: Role[] = ["admin", "editor_in_chief", "editor", "staff"];

export default function SsoPage() {
  const { t } = useTranslation();
  const { toast } = useApp();
  const loaded = useLoad(() => api.get<Sso>("/api/settings/sso"));
  const [cfg, setCfg] = useState<Sso | null>(null);
  const [secret, setSecret] = useState("");
  useEffect(() => { if (loaded.data) setCfg(loaded.data); }, [loaded.data]);
  if (!cfg) return <div className="page"><PageHead title={t("sso.title")} /></div>;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const r = await api.put<Sso>("/api/settings/sso", { ...cfg, client_secret: secret || undefined });
      setCfg({ ...r, redirect_uri: cfg.redirect_uri }); setSecret("");
      toast("success", t("common.saved"));
    } catch (err) { toast("error", errorText(err instanceof ApiError ? err.detail : String(err))); }
  };

  return (
    <form className="page" onSubmit={save}>
      <PageHead title={t("sso.title")} subtitle={t("sso.subtitle")} actions={<button className="btn">{t("common.save")}</button>} />
      <Alert kind="info">{t("sso.phaseNote")}</Alert>
      <Card title={t("sso.app")} actions={<Switch checked={cfg.enabled} onChange={(v) => setCfg({ ...cfg, enabled: v })} label={t("sso.enabled")} />}>
        <div className="stack">
          <div className="grid two">
            <Field label={t("sso.tenantId")}><input value={cfg.tenant_id} onChange={(e) => setCfg({ ...cfg, tenant_id: e.target.value })} placeholder="00000000-0000-0000-0000-000000000000" /></Field>
            <Field label={t("sso.clientId")}><input value={cfg.client_id} onChange={(e) => setCfg({ ...cfg, client_id: e.target.value })} /></Field>
            <Field label={t("sso.clientSecret")} hint={cfg.client_secret_set ? t("common.secretKept") : undefined}>
              <input type="password" autoComplete="new-password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={cfg.client_secret_set ? "••••••••" : ""} />
            </Field>
            <Field label={t("sso.redirectUri")} hint={t("sso.redirectHint")}>
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input readOnly value={cfg.redirect_uri} />
                <button type="button" className="btn secondary" onClick={() => navigator.clipboard?.writeText(cfg.redirect_uri)} aria-label={t("common.copy")}><Copy /></button>
              </div>
            </Field>
          </div>
          <Switch checked={cfg.allow_local_login} onChange={(v) => setCfg({ ...cfg, allow_local_login: v })} label={t("sso.allowLocal")} />
          <p className="muted small">{t("sso.breakGlass")}</p>
        </div>
      </Card>
      <Card title={t("sso.groups")} subtitle={t("sso.groupsIntro")}>
        <div className="stack">
          {ROLES.map((r) => (
            <div key={r} className="grid two" style={{ alignItems: "center" }}>
              <div><b>{t(`roles.${r}`)}</b><div className="muted small">{t(`roles.${r}_text`)}</div></div>
              <input value={cfg.group_roles[r] ?? ""} placeholder={t("sso.groupIdPlaceholder")} onChange={(e) => setCfg({ ...cfg, group_roles: { ...cfg.group_roles, [r]: e.target.value } })} />
            </div>
          ))}
          <Field label={t("sso.defaultRole")}>
            <select value={cfg.default_role} onChange={(e) => setCfg({ ...cfg, default_role: e.target.value as Role })}>
              {ROLES.map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}
            </select>
          </Field>
        </div>
      </Card>
    </form>
  );
}
