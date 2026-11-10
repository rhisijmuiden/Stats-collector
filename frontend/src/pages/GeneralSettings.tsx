import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { Card, Field, PageHead, useLoad } from "../components/ui";

interface General { organization: string; default_language: "en" | "nl"; timezone: string }

export default function GeneralSettings() {
  const { t } = useTranslation();
  const { toast } = useApp();
  const loaded = useLoad(() => api.get<General>("/api/settings/general"));
  const [cfg, setCfg] = useState<General | null>(null);
  useEffect(() => { if (loaded.data) setCfg(loaded.data); }, [loaded.data]);
  if (!cfg) return <div className="page"><PageHead title={t("general.title")} /></div>;
  const zones = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone") ?? [cfg.timezone];

  const save = async (e: FormEvent) => {
    e.preventDefault();
    try { setCfg(await api.put<General>("/api/settings/general", cfg)); toast("success", t("common.saved")); }
    catch (err) { toast("error", errorText(err instanceof ApiError ? err.detail : String(err))); }
  };

  return (
    <form className="page" onSubmit={save}>
      <PageHead title={t("general.title")} subtitle={t("general.subtitle")} actions={<button className="btn">{t("common.save")}</button>} />
      <Card>
        <div className="grid three">
          <Field label={t("general.organization")}><input value={cfg.organization} onChange={(e) => setCfg({ ...cfg, organization: e.target.value })} /></Field>
          <Field label={t("general.defaultLanguage")} hint={t("general.defaultLanguageHint")}>
            <select value={cfg.default_language} onChange={(e) => setCfg({ ...cfg, default_language: e.target.value as "en" | "nl" })}>
              <option value="en">English</option><option value="nl">Nederlands</option>
            </select>
          </Field>
          <Field label={t("general.timezone")}>
            <select value={cfg.timezone} onChange={(e) => setCfg({ ...cfg, timezone: e.target.value })}>
              {zones.map((z) => <option key={z}>{z}</option>)}
            </select>
          </Field>
        </div>
      </Card>
      <Card title={t("general.proxy")}>
        <p className="muted" style={{ marginTop: 0 }}>{t("general.proxyText")}</p>
        <pre className="log">{`# /etc/stats-collector/config.env
SC_PUBLIC_URL=https://stats.example.org
SC_TRUSTED_PROXIES=192.0.2.10`}</pre>
      </Card>
    </form>
  );
}
