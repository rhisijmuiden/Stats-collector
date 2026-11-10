import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { api, ApiError, type Role, type User } from "../lib/api";
import { useApp } from "../lib/app";
import { errorText } from "../i18n";
import { formatDate } from "../lib/format";
import { Card, Field, Modal, PageHead, Switch, useLoad } from "../components/ui";

const ROLES: Role[] = ["admin", "editor_in_chief", "editor", "staff"];

interface Draft {
  id?: number;
  email: string;
  display_name: string;
  role: Role;
  language: "en" | "nl";
  password: string;
  is_active: boolean;
}

export default function Users() {
  const { t, i18n } = useTranslation();
  const { user: me, toast } = useApp();
  const users = useLoad(() => api.get<User[]>("/api/users"));
  const [draft, setDraft] = useState<Draft | null>(null);

  const fail = (e: unknown) => toast("error", errorText(e instanceof ApiError ? e.detail : String(e)));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!draft) return;
    try {
      const body = { ...draft, password: draft.password || undefined };
      if (draft.id) await api.patch(`/api/users/${draft.id}`, body);
      else await api.post("/api/users", body);
      toast("success", t("common.saved"));
      setDraft(null);
      users.reload();
    } catch (err) {
      fail(err);
    }
  };

  const remove = async (u: User) => {
    if (!window.confirm(t("users.confirmDelete", { name: u.display_name }))) return;
    try {
      await api.del(`/api/users/${u.id}`);
      users.reload();
    } catch (err) {
      fail(err);
    }
  };

  return (
    <div className="page">
      <PageHead
        title={t("users.title")}
        subtitle={t("users.subtitle")}
        actions={
          <button className="btn" onClick={() => setDraft({ email: "", display_name: "", role: "staff", language: i18n.language as "en" | "nl", password: "", is_active: true })}>
            <Plus /> {t("users.add")}
          </button>
        }
      />
      <Card>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("users.name")}</th><th>{t("auth.email")}</th><th>{t("users.role")}</th>
                <th>{t("users.signIn")}</th><th>{t("users.lastLogin")}</th><th />
              </tr>
            </thead>
            <tbody>
              {users.data?.map((u) => (
                <tr key={u.id}>
                  <td><b>{u.display_name}</b> {!u.is_active && <span className="badge critical">{t("users.disabled")}</span>}</td>
                  <td>{u.email}</td>
                  <td><span className="badge accent">{t(`roles.${u.role}`)}</span></td>
                  <td>{u.auth_provider === "entra" ? "Microsoft 365" : t("users.local")}{u.totp_enabled && " · 2FA"}</td>
                  <td>{formatDate(u.last_login_at, i18n.language)}</td>
                  <td>
                    <div className="row end" style={{ flexWrap: "nowrap" }}>
                      <button className="btn ghost" aria-label={t("common.edit")} onClick={() => setDraft({ ...u, password: "" })}><Pencil /></button>
                      {u.id !== me?.id && <button className="btn ghost" aria-label={t("common.delete")} onClick={() => remove(u)}><Trash2 /></button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title={t("users.rolesTitle")}>
        <div className="grid two">
          {ROLES.map((r) => (
            <div key={r}>
              <h3>{t(`roles.${r}`)}</h3>
              <p className="muted small" style={{ margin: "4px 0 0" }}>{t(`roles.${r}_text`)}</p>
            </div>
          ))}
        </div>
      </Card>
      {draft && (
        <Modal title={draft.id ? t("users.edit") : t("users.add")} onClose={() => setDraft(null)}>
          <form className="stack" onSubmit={save}>
            <Field label={t("users.name")}><input required value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} /></Field>
            <Field label={t("auth.email")}><input type="email" required disabled={!!draft.id} value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} /></Field>
            <div className="grid two">
              <Field label={t("users.role")}>
                <select value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value as Role })}>
                  {ROLES.map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}
                </select>
              </Field>
              <Field label={t("profile.language")}>
                <select value={draft.language} onChange={(e) => setDraft({ ...draft, language: e.target.value as "en" | "nl" })}>
                  <option value="en">English</option><option value="nl">Nederlands</option>
                </select>
              </Field>
            </div>
            <Field label={draft.id ? t("users.newPassword") : t("auth.password")} hint={t("auth.passwordRule")}>
              <input type="password" autoComplete="new-password" minLength={12} value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
            </Field>
            <Switch checked={draft.is_active} onChange={(v) => setDraft({ ...draft, is_active: v })} label={t("users.active")} />
            <div className="row end">
              <button type="button" className="btn secondary" onClick={() => setDraft(null)}>{t("common.cancel")}</button>
              <button className="btn">{t("common.save")}</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
