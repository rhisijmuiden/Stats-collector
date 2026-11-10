import { useState } from "react";
import { useTranslation } from "react-i18next";
import { UserCheck } from "lucide-react";
import { api } from "../lib/api";
import { useApp } from "../lib/app";
import { Alert, Card, Modal, PageHead, useLoad } from "../components/ui";
import { errorText } from "../i18n";
import { fmt, fmtSeconds, type Item, ItemModal, ItemsTable, kindIcon, MetricsChart, type Detail, type Range, RangePicker } from "./Content";

type SocialSums = Record<"posts" | "views" | "reach" | "likes" | "comments" | "shares", number>;
interface Editor {
  id: number; name: string; linked_user: boolean; items: number; published: number; avg_read_seconds: number;
  metrics: Record<"views" | "visitors" | "read_seconds" | "reads" | "shares" | "comments" | "minutes", number>;
  social?: SocialSums & { by_kind: Record<string, SocialSums> };
}
interface Editors { scope: "all" | "own"; editors: Editor[] }
interface EditorDetail extends Pick<Detail, "granularity" | "buckets" | "series"> { editor: Editor }

function EditorModal({ editor, range, onClose }: { editor: Editor; range: Range; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const { theme } = useApp();
  const r = range === "24h" ? "7d" : range;
  const detail = useLoad(() => api.get<EditorDetail>(`/api/editors/${editor.id}?range=${r}`), [editor.id, r]);
  const top = useLoad(() => api.get<{ items: Item[] }>(`/api/content/top?range=${r}&person=${editor.id}&limit=10`), [editor.id, r]);
  const social = useLoad(() => api.get<{ items: Item[] }>(`/api/content/top?range=${r}&person=${editor.id}&via=social&limit=10`), [editor.id, r]);
  const byKind = Object.entries(editor.social?.by_kind ?? {});
  const [item, setItem] = useState<number | null>(null);
  if (item != null) return <ItemModal id={item} range={range} onClose={() => setItem(null)} />;
  return (
    <Modal title={editor.name} onClose={onClose}>
      <div className="stack">
        {detail.error && <Alert kind="error">{errorText(detail.error)}</Alert>}
        {detail.data && <MetricsChart granularity={detail.data.granularity} buckets={detail.data.buckets} series={detail.data.series} color={theme?.channels?.website ?? "#3E7BFA"} />}
        <h3 className="small-title">{t("editors.topArticles")}</h3>
        {top.data && <ItemsTable items={top.data.items} onOpen={setItem} showAuthors={false} />}
        <div><h3 className="small-title">{t("editors.social")}</h3><div className="muted small">{t("editors.socialHint")}</div></div>
        {byKind.length > 0 && (
          <div className="kpis">
            {byKind.map(([kind, v]) => (
              <div className="kpi" key={kind}>
                <span className="kpi-bar" style={{ background: theme?.channels?.[kind] }} />
                <div className="kpi-label">{kindIcon(kind)} {t(`editors.platform.${kind}`, { defaultValue: kind })}</div>
                <div className="kpi-value">{fmt(v.views, i18n.language)}</div>
                <div className="kpi-sub">{t("editors.socialSub", { count: v.posts, likes: fmt(v.likes, i18n.language) })}{v.reach ? ` · ${t("editors.socialReach", { reach: fmt(v.reach, i18n.language) })}` : ""}</div>
              </div>
            ))}
          </div>
        )}
        {social.data && (social.data.items.length ? <ItemsTable items={social.data.items} onOpen={setItem} showAuthors={false} /> : <p className="muted small">{t("editors.socialNone")}</p>)}
        <div className="row end"><button className="btn secondary" onClick={onClose}>{t("common.close")}</button></div>
      </div>
    </Modal>
  );
}

export default function EditorsPage() {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const [range, setRange] = useState<Range>("30d");
  const [open, setOpen] = useState<Editor | null>(null);
  const list = useLoad(() => api.get<Editors>(`/api/editors?range=${range}`), [range]);
  const rows = list.data?.editors ?? [];
  const max = Math.max(1, ...rows.map((e) => e.metrics.views));
  return (
    <div className="page">
      <PageHead help="content" title={t("editors.title")} subtitle={t(list.data?.scope === "own" ? "editors.subtitleOwn" : "editors.subtitle")} actions={<RangePicker value={range} onChange={setRange} />} />
      {list.data?.scope === "own" && <Alert kind="info">{t("editors.ownOnly")}</Alert>}
      <Card>
        {list.error && <Alert kind="error">{errorText(list.error)}</Alert>}
        {list.data && (rows.length ? (
          <div className="table-wrap"><table>
            <thead><tr>
              <th>{t("editors.name")}</th><th className="num">{t("editors.published")}</th><th>{t("content.views")}</th>
              <th className="num">{t("content.visitors")}</th><th className="num">{t("content.avgRead")}</th><th className="num">{t("content.reads")}</th>
              <th className="num">{t("content.shares")}</th><th className="num">{t("content.comments")}</th>
              <th className="num" title={t("editors.socialHint")}>{t("editors.socialViews")}</th>
            </tr></thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className="clickable" onClick={() => setOpen(e)}>
                  <td><button type="button" className="link-btn" onClick={(ev) => { ev.stopPropagation(); setOpen(e); }}>{e.name}</button>
                    {!e.linked_user && <div className="muted small">{t("editors.notLinked")}</div>}</td>
                  <td className="num">{e.published}</td>
                  <td className="meter-cell"><div><span className="meter"><span style={{ width: `${(e.metrics.views / max) * 100}%` }} /></span><b>{fmt(e.metrics.views, lang)}</b></div></td>
                  <td className="num">{fmt(e.metrics.visitors, lang)}</td>
                  <td className="num">{fmtSeconds(e.avg_read_seconds)}</td>
                  <td className="num">{fmt(e.metrics.reads, lang)}</td>
                  <td className="num">{fmt(e.metrics.shares, lang)}</td>
                  <td className="num">{fmt(e.metrics.comments, lang)}</td>
                  <td className="num">{e.social?.posts ? <span title={t("editors.socialPosts", { count: e.social.posts })}>{fmt(e.social.views, lang)}</span> : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        ) : <div className="empty"><UserCheck /><h2>{t("editors.noneTitle")}</h2><p>{t(list.data.scope === "own" ? "editors.noneOwn" : "editors.noneText")}</p></div>)}
      </Card>
      {open && <EditorModal editor={open} range={range} onClose={() => setOpen(null)} />}
    </div>
  );
}
