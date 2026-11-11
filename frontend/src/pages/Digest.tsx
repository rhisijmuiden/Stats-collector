import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Eye, MailCheck, Send } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { Alert, Card, Field, Modal, PageHead, Switch, useLoad } from "../components/ui";

interface Settings { enabled: boolean; weekday: number; time: string; ranking: boolean; excluded_person_ids: number[]; last_week: string }
interface Editor { id: number; name: string; email: string | null; language: string; enabled: boolean }
interface State { settings: Settings; editors: Editor[]; email_ready: boolean }
interface Preview { to: string | null; language: string; subject: string; html: string }

function weekdayNames(lang: string) {
  const monday = new Date(2024, 0, 1);
  return Array.from({ length: 7 }, (_, i) => new Date(monday.getTime() + i * 86400000).toLocaleDateString(lang, { weekday: "long" }));
}

export default function DigestPage() {
  const { t, i18n } = useTranslation();
  const { toast } = useApp();
  const state = useLoad(() => api.get<State>("/api/digest"));
  const [form, setForm] = useState<Settings | null>(null);
  const [preview, setPreview] = useState<(Preview & { id: number; name: string }) | null>(null);
  useEffect(() => { if (state.data) setForm(state.data.settings); }, [state.data]);
  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));
  const days = weekdayNames(i18n.language);

  const save = async (next: Settings) => {
    try {
      const s = await api.put<State>("/api/digest", next);
      state.setData(s);
      toast("success", t("common.saved"));
    } catch (e) { fail(e); }
  };
  const toggle = (id: number, on: boolean) => {
    const ex = new Set(form!.excluded_person_ids);
    if (on) ex.delete(id); else ex.add(id);
    void save({ ...form!, excluded_person_ids: [...ex] });
  };
  const show = async (e: Editor) => {
    try { setPreview({ ...(await api.get<Preview>(`/api/digest/preview/${e.id}`)), id: e.id, name: e.name }); } catch (err) { fail(err); }
  };
  const test = async (id: number) => {
    try { const r = await api.post<{ to: string }>(`/api/digest/test/${id}`); toast("success", t("digest.testSent", { to: r.to })); } catch (err) { fail(err); }
  };

  return (
    <div className="page">
      <PageHead help="weekly-summary" title={t("digest.title")} subtitle={t("digest.subtitle")} />
      {state.error && <Alert kind="error">{errorText(state.error)}</Alert>}
      {state.data && !state.data.email_ready && <Alert kind="warning">{t("digest.noEmail")}</Alert>}
      {form && (
        <Card title={t("digest.when")}>
          <form className="stack" onSubmit={(e) => { e.preventDefault(); void save(form); }}>
            <Switch checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} label={t("digest.enabled")} />
            <div className="grid two">
              <Field label={t("digest.weekday")}>
                <select value={form.weekday} onChange={(e) => setForm({ ...form, weekday: Number(e.target.value) })}>
                  {days.map((d, i) => <option key={i} value={i}>{d}</option>)}
                </select>
              </Field>
              <Field label={t("digest.time")} hint={t("digest.timeHint")}><input type="time" required value={form.time} onChange={(e) => setForm({ ...form, time: e.target.value })} /></Field>
            </div>
            <Switch checked={form.ranking} onChange={(v) => setForm({ ...form, ranking: v })} label={t("digest.ranking")} />
            <p className="muted small">{t("digest.what")}{form.last_week ? ` ${t("digest.lastSent", { week: form.last_week })}` : ""}</p>
            <div className="row end"><button className="btn">{t("common.save")}</button></div>
          </form>
        </Card>
      )}
      {state.data && form && (
        <Card title={t("digest.editors")} subtitle={t("digest.editorsHint")}>
          {state.data.editors.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>{t("digest.editor")}</th><th>{t("digest.address")}</th><th>{t("digest.language")}</th><th>{t("digest.receives")}</th><th /></tr></thead>
              <tbody>{state.data.editors.map((e) => (
                <tr key={e.id}>
                  <td><b>{e.name}</b></td>
                  <td>{e.email ?? <span className="muted">{t("digest.noAddress")}</span>}</td>
                  <td>{e.language === "nl" ? "Nederlands" : "English"}</td>
                  <td><Switch checked={e.enabled} onChange={(v) => toggle(e.id, v)} label={e.enabled ? t("digest.yes") : t("digest.no")} /></td>
                  <td className="num nowrap">
                    <button className="btn ghost" onClick={() => show(e)}><Eye /> {t("digest.preview")}</button>
                  </td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <div className="empty"><MailCheck /><h2>{t("digest.noneTitle")}</h2><p>{t("digest.noneText")}</p></div>}
        </Card>
      )}
      {preview && (
        <Modal title={t("digest.previewOf", { name: preview.name })} onClose={() => setPreview(null)}>
          <div className="stack">
            <div className="muted small"><b>{t("digest.subject")}:</b> {preview.subject}<br /><b>{t("digest.to")}:</b> {preview.to ?? t("digest.noAddress")}</div>
            <iframe className="mail-preview" title={preview.subject} sandbox="" srcDoc={preview.html} />
            <div className="row end">
              <button className="btn secondary" disabled={!state.data?.email_ready} onClick={() => test(preview.id)}><Send /> {t("digest.sendTest")}</button>
              <button className="btn secondary" onClick={() => setPreview(null)}>{t("common.close")}</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
