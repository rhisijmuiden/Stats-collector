# Stats Collector: system design and roadmap

Status: design, agreed scope as of 2026-11-10. No application code yet.
The living (Dutch) version of this document, with architecture and roadmap diagrams, is kept as a Claude Doc; this file is the English copy in the repo. A clickable UI sketch is in [`docs/mockup/index.html`](mockup/index.html).

## Summary

Stats Collector is a self-hosted web application for Debian 13 (Trixie). It collects reach, engagement and audience numbers from WordPress, Facebook, Instagram, YouTube, X, LinkedIn, TikTok, Threads, Bluesky, Mastodon, Owncast and Icecast, normalises them, and combines them in one BI dashboard with stacked, overlaid or separate charts. Reports are composed in the app and sent on demand or on a schedule through Microsoft 365.

Key decisions:

- One app on port **8080** (web + API), designed to run behind a reverse proxy with Let's Encrypt (Zoraxy in production). `X-Forwarded-*` headers are trusted only from configured proxy IPs.
- A separate, read-only **live wall** service on port **8081** for a TV screen, without login.
- **Canonical metrics**: every platform's numbers are mapped to shared categories (Reach, Views/visits, Interactions, Watch/listen time, Followers), so channels can be stacked into one total.
- **Single tenant now, multi-tenant ready**: every table carries `tenant_id` from day one.
- **English by default, fully translated to Dutch.**

## Architecture

```
 WordPress   Facebook   Instagram   YouTube   Owncast   Icecast    (+ X, LinkedIn, TikTok, Threads, Bluesky, Mastodon: pull)
  (push)      (pull)     (pull)     (pull)    (pull)    (pull)
     \__________|__________|__________|_________|_________/
                              |
 +----------------------- Debian 13 server ------------------------+
 |  worker (Celery)      scheduler (Celery Beat)     updater        |
 |  connectors, rollups, report/PDF generation       (systemd unit) |
 |                                                                  |
 |  web + API :8080      PostgreSQL 17      Redis      live wall :8081 |
 |  FastAPI + React UI   metrics, items     queue,     reads snapshot  |
 |                       users, RLS         cache      from Redis only |
 +------------------------------------------------------------------+
        |                    |                         |
  Reverse proxy (Zoraxy)   Microsoft 365 + SMTP     Backup targets
  HTTPS, Let's Encrypt     Entra SSO, Graph mail    FTP, FTPS, SCP/SFTP
```

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.13, FastAPI, SQLAlchemy, Alembic | Ships with Debian 13; strong libraries for every source API |
| Background jobs | Celery + Redis, Celery Beat for schedules | Retries and backoff on API errors and rate limits |
| Database | PostgreSQL 17, monthly partitions, row-level security | Fast time series, ready for multi-tenant |
| Frontend | React, TypeScript, Vite, Tailwind, shadcn/ui | Modern, light/dark, themeable from the brand |
| Charts | Apache ECharts | Stacking, overlay, toggleable legend, zoom |
| PDF | Playwright + headless Chromium | The PDF is the same page as the interactive report |
| Live wall | Separate small service, Three.js / CSS 3D bars, Server-Sent Events | Isolated from database and admin |
| i18n | react-i18next (UI), Babel (emails, PDF) | English base, Dutch translation |

## Connectors

Every source is a backend connector with the same shape: settings, a "test connection" button, a fetch schedule and a mapping to canonical metrics.

| Source | Method | Collected | Per item | Notes |
| --- | --- | --- | --- | --- |
| WordPress (2 to 5 sites) | Own plugin pushes batches over HTTPS (API key + HMAC), every minute | Page views, unique visitors, returning visitors, referrers, device, read time, comments, share clicks, author, category, tags | Per post/page | Cookieless: daily rotating salted visitor hash, no cookie banner needed |
| Facebook | Graph API, Page + Post Insights, long-lived Page token | Followers, page likes, views/reach, reactions by type, comments, shares, clicks, video views | Per post | Meta Business is verified; App Review is requested in phase 0. Metric names are configurable because Meta changes them per API version |
| Instagram | Graph API via the same Meta app (business account) | Followers, profile visits, reach, likes, comments, shares, saves, views (incl. reels, stories) | Per post | Ships with Facebook in phase 3 |
| YouTube | Data API v3 + Analytics API (channel owner OAuth) | Subscribers gained/lost, views, watch time, avg view duration, likes, comments, shares | Per video | Daily quota; Analytics lags 1 to 2 days |
| Owncast (2 to 5) | Admin API polled every 30 s + webhooks for stream start/stop | Live viewers, peak, viewer minutes, session duration | Per broadcast | Each broadcast becomes an item |
| Icecast (2 to 5 mounts) | `status-json.xsl` every 30 s + `admin/listclients`; `admin/stats` when the host removed `status-json.xsl` | Listeners per mount, peak, listener minutes, avg listening time, user agents | Per mount | Admin password needed for per-client duration (and for `admin/stats`) |
| Threads | Threads API via the same Meta app (`threads_basic`, `threads_manage_insights`) | Followers, views, likes, replies, reposts, quotes, clicks | Per post | Phase 3f. Insights from 13 April 2024 onwards |
| Bluesky | Public AppView API (`app.bsky.feed.getAuthorFeed`, `getProfile`), no login | Followers, likes, reposts, replies, quotes | Per post | Phase 3f. Free; no views or reach |
| Mastodon | Server REST API with a read-only access token | Followers, favourites, boosts, replies | Per post | Phase 3f. Free, per server; no views or reach |
| X | X API v2 with user OAuth 2.0 (owner's account): `users/me`, `users/:id/tweets` with `public_metrics` and `non_public_metrics` | Followers, impressions, likes, reposts, replies, quotes, bookmarks, link clicks | Per post | Phase 3f. Pay-per-use credits since Feb 2026 (about $0.005 per post read); posts are refreshed for 7 days, a monthly budget cap stops collection before it runs out |
| LinkedIn (company page) | Community Management API (organization follower, page and share statistics) | Followers, page views, impressions, clicks, reactions, comments, shares, video views | Per post | Phase 3f. Vetted product: a new developer app, Development tier, then Standard tier with a screencast; weeks of review |
| TikTok | Display API with the owner's login (`user.info.stats`, `video.list`) | Followers, likes, views, likes, comments, shares per video | Per video | Phase 3f. App review needed; no daily history, so daily numbers are computed from the change in totals |

## Data model

| Table | Content |
| --- | --- |
| `tenants` | Customers; exactly one row (`default`) for now |
| `sources` | A configured connector instance |
| `content_items` | Post, video, article, broadcast or mount: title, URL, published at, category, tags |
| `people`, `item_people` | Editors/creators and which items are theirs (author, co-author, presenter) |
| `item_links` | Links items across platforms (a Facebook post or YouTube video pointing to an article) |
| `metric_definitions` | Per platform metric: unit, aggregation (sum, avg, max, gauge), canonical category |
| `metric_points` | Values: tenant, source, item (optional), metric, time bucket, value; partitioned per month |
| `stream_samples` | Raw Owncast/Icecast samples per 30 s; summarised after **1 year** |
| `goals`, `goal_revisions` | Targets on any metric, with full history of adjustments |

Hourly, daily and monthly rollups are kept up to date by a background job. Raw samples are kept for 1 year; hourly and daily totals are kept forever.

### Editor performance

Each editor is a person in the app, linked to their WordPress user and optionally an Entra ID account. Social posts are linked to an article (and so to its editor) automatically by URL, through a per-article tracking link generated by the plugin, or manually. Dashboards and reports can filter and group by editor: website views plus reach and engagement of the linked social posts, stacked per platform.

### Followers and goals

Follower counts are recorded daily per platform, giving a growth chart per platform and stacked over all channels. A goal can be set on any metric (for example 5,000 Facebook followers, or 1 million reach this quarter across all channels), with an optional end date. Goals can be adjusted at any time; earlier targets stay in the history so reports show what the target was at the time. Charts show the goal as a dashed line with a progress bar and a trend forecast. Optional email when a goal is reached or falls behind.

## Dashboards

- Saved dashboards with multiple widgets: KPI tiles, line/area/bar charts, top-items tables, editor rankings.
- Every chart can switch between **stacked total**, **overlay** and **separate** (small multiples).
- The legend below a chart toggles series on and off.
- Filters: period, source, platform, editor, category/tag, comparison with the previous period.

## Reports

- A report is a template of blocks (KPI row, chart, top content, editor ranking, per-channel section, streams, goals, free text) filled in for a period.
- Output: interactive HTML (signed link with expiry) and a branded PDF rendered from the same page.
- On demand ("Generate now", "Send now") and scheduled: daily, weekly or monthly at a chosen time and time zone (default Europe/Amsterdam).
- Recipients: internal users and external email addresses per report.
- Delivery through Microsoft Graph `sendMail` from a configurable mailbox (app registration with `Mail.Send`, restricted to that mailbox by an Application Access Policy). The mailbox is chosen at install time. SMTP is the fallback route.
- Every sent report is archived with recipients and time.

## Live wall (port 8081)

A separate, read-only web app showing the last hour of activity per channel as animated 3D bars, for a TV on the newsroom floor.

- No login. Each wall has a unique, unguessable URL (`/w/<token>`), its own channels, title and brand. Tokens can be revoked or rotated; optional IP allow-list.
- The wall never calls source APIs. The worker computes one snapshot every 60 seconds and stores it in Redis; the wall service only reads that snapshot and pushes it to screens with Server-Sent Events (fallback: poll every 60 s). Rate limiting per IP on top.
- The wall service has no access to the database or admin functions.
- Freshness is shown per channel: website, Owncast and Icecast are live; YouTube is approximate (5 to 15 min delay, computed from view-count deltas); Facebook and Instagram are approximate (up to about an hour).
- Served behind the reverse proxy on its own host name, e.g. `live.example.org` → port 8081.

## Authentication and authorisation

- **Entra ID (Microsoft 365) SSO** via OpenID Connect (authorization code + PKCE).
- **Local accounts** with Argon2id passwords and optional TOTP; at least one local break-glass admin.

### Roles from Microsoft 365

Roles are managed in Microsoft 365, not in the app: each role maps to an Entra group (or an app role on the Entra app registration). Group membership is read at every sign-in, so adding or removing someone in Microsoft 365 changes their role. Everyone in the organisation can sign in and gets at least the Staff role.

| Role | Entra group (example) | Sees | Can |
| --- | --- | --- | --- |
| Admin | `SC-Admins` | Everything | Sources, users, branding, email, backup, updates, live walls |
| Editor-in-chief | `SC-EditorsInChief` | Everything, including per-editor numbers and rankings | Build dashboards, reports and goals; send reports |
| Editor | `SC-Editors` | All items and channels, plus their own editor numbers | Own dashboards, on-demand reports |
| Staff | All employees | All items, channels, followers and goals, without editor names | View only |

**Anonymised view for Staff and Editors**: editor names and per-editor aggregates are removed server-side from every API response before it reaches the browser, not just hidden in the UI. The editor overview, rankings and the editor filter are not available. An editor sees only their own numbers, never a colleague's. Reports containing editor blocks can only be sent to Editor-in-chief and Admin users.

Group mapping and what each role sees are configurable in **Admin → Roles**; the table above is the default.

## Branding

- The default brand lives in [`branding/default/`](../branding/default/).
- **Admin → Branding**: logo (light/dark), favicon, accent colours, fonts, chart colours per channel, with live preview.
- Applied to the app, PDF and interactive reports, emails and the live wall. Export/import as a file.

## Multi-tenant (later)

`tenant_id` on every table and PostgreSQL row-level security from day one. Later: tenant by host name, per-tenant brand, Entra connection, mailbox and connectors, and a super-admin screen.

## Standard features

| Feature | Implementation |
| --- | --- |
| Mail server | **Admin → Email**: custom SMTP with STARTTLS or SMTPS (TLS 1.2+), password or OAuth2 (XOAUTH2), sender name, test button. Microsoft Graph as a second route; choose the route per function |
| Backup | Full and incremental: database via pgBackRest (full/incr), files via tar with incremental index. Encrypted (AES-256) and compressed |
| Remote locations | FTP, FTPS (explicit and implicit) and SCP/SFTP via rclone; multiple targets; retention (e.g. 7 daily, 4 weekly, 6 monthly) |
| Restore | Pick a backup from a remote location in the UI, verify and restore (full or up to an incremental point); also `stats-collector restore` on the CLI |
| Info button | Version, git commit, channel, build date, Python/PostgreSQL versions, background job status |
| Updates | "Check for updates" reads GitHub releases of the selected channel. "Update now" takes a backup, fetches the new version, runs migrations and restarts; automatic rollback on failure. Runs in a separate systemd unit so the web process never needs root |
| Production / test | Production follows `main` (releases), test follows `develop`. Switch in **Info → Update channel** |
| Menu | All admin screens in a fixed left sidebar |
| Languages | English default, full Dutch translation; language per user, PDFs and emails per recipient language |

### Help and manual

A full manual with screenshots, hosted on GitHub Pages and opened from a **Help** button at the bottom of the left menu.

- **Content**: installation on Debian 13 and Zoraxy; step-by-step setup per source: creating the Meta app and App Review (Facebook, Instagram), Google Cloud project and OAuth for YouTube, installing and linking the WordPress plugin, Owncast and Icecast access; then dashboards, reports, goals, live wall, roles in Microsoft 365, email, backup/restore and updates.
- **Tooling**: Markdown in `docs/manual/`, built with MkDocs Material, English and Dutch, with search. Published to GitHub Pages on every release, versioned per release so the help always matches the running version.
- **In the app**: the Help button opens the manual in the user's language. Every screen has a `?` icon that links to its own page. A copy of the manual is bundled in the app for servers without internet access.
- **Always current**: screenshots are regenerated with Playwright and example data on every release. Every change to a screen or feature must update the manual; a CI check blocks pull requests that change UI or features without touching `docs/manual/`.

## Installer (Debian 13 Trixie)

`install.sh` turns a bare Debian 13 into a working server and is idempotent.

1. Checks Debian 13, root and network; asks for channel (production/test), port (default 8080, live wall 8081) and reverse proxy IPs.
2. Installs from Debian repositories: Python 3.13, PostgreSQL 17, Redis, pgBackRest, rclone, Chromium dependencies, git.
3. Creates system user `statscollector`, `/opt/stats-collector` and a Python virtualenv; checks out the selected channel.
4. Creates database and role, runs migrations, generates secrets in `/etc/stats-collector/config.env` (readable by the app only).
5. Installs systemd units: `web` (8080), `livewall` (8081), `worker`, `scheduler`, `updater`.
6. Optional nftables firewall that opens 8080/8081 only to the proxy.
7. Prints the URL and a one-time link to create the first admin.

**Reverse proxy (Zoraxy)**: two proxy rules, `stats.example.org` → `:8080` and `live.example.org` → `:8081`, ACME/Let's Encrypt enabled, Zoraxy's IP configured as trusted proxy in the app. A step-by-step Zoraxy guide ships in the repo; examples for Nginx, Caddy and Traefik as well.

## Roadmap

| Phase | Scope | Done when |
| --- | --- | --- |
| 0 · Foundation | Repo, CI, Debian 13 installer, app skeleton on 8080 behind proxy, local accounts, left menu, EN/NL, branding, Info button. Request Meta App Review and Google OAuth verification | Runs on a bare Debian 13 |
| 1 · Data and streams | Data model, worker, scheduler, Icecast and Owncast connectors, first dashboard, Entra ID SSO | Live viewer and listener numbers |
| 2 · Website and video | WordPress plugin, YouTube connector, articles and editors, top lists per item | Numbers per article |
| 3 · Facebook + builder | Facebook + Instagram connectors, dashboard builder (stack/overlay/legend), linking posts to articles, followers and goals, live wall on 8081 | One total reach |
| 3f · More social media | Threads, Bluesky, Mastodon, then X (pay-per-use), then LinkedIn and TikTok once their app review is approved; all in the canonical measures, goals, post-to-article links and dashboards | Every channel the newsroom posts on |
| 4 · Reports | Report builder, interactive HTML and PDF, schedules and recipients, mail via Graph and SMTP | Monthly report in the inbox |
| 5 · Go-live | Backup/restore FTP/FTPS/SCP, updates from the UI, production and test channel, security review | In production |
| Later · Multi-tenant | Fully separated customers with their own brand, SSO and mailbox | |

A first live wall with website, Owncast and Icecast can ship after phase 2.

## Decisions log (2026-11-10)

| Question | Decision |
| --- | --- |
| App and repo name | Stats Collector, `stats-collector` |
| Meta Business verification | Verified; App Review starts in phase 0 |
| Instagram | Included in phase 3 via the same Meta app |
| X, LinkedIn and other social media | Added as phase 3f (requested 2026-11-10): Threads, Bluesky, Mastodon first (free, no review), then X (pay-per-use, about $30-40 a month estimated), then LinkedIn and TikTok after app review |
| Icecast without `status-json.xsl` | The IJmond360 host removed it; the connector falls back to `admin/stats` with the admin login |
| Number of sources | 2 to 5 each of WordPress sites, Owncast servers, Icecast mounts |
| Report mailbox | Not decided; configurable at install |
| Data retention | Raw samples 1 year, hourly/daily totals forever |
| Reverse proxy | Zoraxy |
| Roles and visibility | Roles from Microsoft 365 groups: Admin, Editor-in-chief, Editor, Staff. Staff see everything except per-editor numbers |
