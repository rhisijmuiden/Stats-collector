import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink } from "lucide-react";
import { api } from "../lib/api";
import { Card, PageHead, useLoad } from "../components/ui";

interface Index { lang: string; pages: { slug: string; title: string }[]; github: string }
interface Page { slug: string; title: string; markdown: string; github: string }

/** Rewrites manual-relative links: images to /help-assets, other .md files to in-app help routes. */
function rewrite(href: string | undefined, kind: "img" | "a"): string | undefined {
  if (!href || /^(https?:|mailto:|#)/.test(href)) return href;
  if (kind === "img") return "/help-assets/" + href.replace(/^(\.\.\/)*(images\/)?/, "");
  const m = href.match(/^(?:\.\/)?([A-Za-z0-9-]+)\.md(#.*)?$/);
  return m ? `/help/${m[1]}${m[2] ?? ""}` : href;
}

export default function Help() {
  const { t, i18n } = useTranslation();
  const { slug = "README" } = useParams();
  const index = useLoad(() => api.get<Index>(`/api/help?lang=${i18n.language}`), [i18n.language]);
  const page = useLoad(() => api.get<Page>(`/api/help/${slug}?lang=${i18n.language}`), [slug, i18n.language]);
  return (
    <div className="page">
      <PageHead title={t("help.title")} subtitle={t("help.subtitle")} actions={
        index.data && <a className="btn secondary" href={page.data?.github ?? index.data.github} target="_blank" rel="noreferrer"><ExternalLink /> {t("help.onGithub")}</a>
      } />
      <div className="help-layout">
        <nav className="help-nav card" aria-label={t("help.contents")}>
          {index.data?.pages.map((p) => (
            <Link key={p.slug} to={`/help/${p.slug}`} className={p.slug === slug ? "active" : ""}>{p.title}</Link>
          ))}
        </nav>
        <Card>
          {page.error ? <p className="muted">{t("help.notFound")}</p> : (
            <article className="markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                img: ({ src, alt }) => <img src={rewrite(src, "img")} alt={alt ?? ""} loading="lazy" />,
                a: ({ href, children }) => {
                  const to = rewrite(href, "a");
                  return to?.startsWith("/help/") ? <Link to={to}>{children}</Link> : <a href={to} target="_blank" rel="noreferrer">{children}</a>;
                },
              }}>{page.data?.markdown ?? ""}</ReactMarkdown>
            </article>
          )}
        </Card>
      </div>
    </div>
  );
}
