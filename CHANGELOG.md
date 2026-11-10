# Changelog

All notable changes to Stats Collector are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/). The app shows these notes per release under **Info → Releases**, in the tabs New, Changed, Fixed and Removed.

Each entry is written in English with a Dutch translation on the line below, prefixed `NL:`.

## [Unreleased]

### Added
- X accounts as sources through the X API v2 (OAuth 2.0): impressions, likes, reposts, replies, quotes, bookmarks, link and profile clicks per post and per day, and the follower count, with a monthly budget per source because X charges per post read.
  NL: X-accounts als bron via de X API v2 (OAuth 2.0): weergaven, likes, reposts, antwoorden, citaten, bladwijzers, link- en profielkliks per bericht en per dag, en het aantal volgers, met een maandbudget per bron omdat X per gelezen bericht rekent.
- Threads accounts as sources through the Threads API of the Meta app: views per day for the account, views, likes, replies, reposts, quotes and shares per post and per day, and the follower count; the token is renewed every week.
  NL: Threads-accounts als bron via de Threads API van de Meta-app: weergaven per dag voor het account, weergaven, likes, antwoorden, reposts, citaten en keren gedeeld per bericht en per dag, en het aantal volgers; het token wordt elke week vernieuwd.
- Live walls: the public address of the walls and the address of their own reverse proxy can be set under Live walls, instead of only with `SC_LIVEWALL_URL`.
  NL: Live walls: het openbare adres van de walls en het adres van hun eigen reverse proxy zijn in te stellen onder Live walls, in plaats van alleen met `SC_LIVEWALL_URL`.
- Bluesky and Mastodon accounts as sources: likes, reposts or boosts, replies and quotes per post and per day, and the follower count, through the platforms' open APIs (no app review needed; Mastodon optionally with an access token). They count towards the interactions and followers measures, and their posts are linked to the articles they point to.
  NL: Bluesky- en Mastodon-accounts als bron: likes, reposts of boosts, antwoorden en citaten per bericht en per dag, en het aantal volgers, via de open API's van de platforms (geen app-review nodig; Mastodon eventueel met een toegangstoken). Ze tellen mee voor de maten interacties en volgers, en hun berichten worden gekoppeld aan de artikelen waarnaar ze verwijzen.
- Roadmap: phase 3f adds X, LinkedIn, TikTok, Threads, Bluesky and Mastodon (`docs/DESIGN.md`).
  NL: Roadmap: fase 3f voegt X, LinkedIn, TikTok, Threads, Bluesky en Mastodon toe (`docs/DESIGN.md`).
- Live walls: read-only screens for the newsroom on port 8081 (`stats-collector-livewall`), with the last hour per radio stream, Owncast stream and website as animated 3D bars, a secret link per wall, new links, optional IP allow-list, updates every minute through Server-Sent Events.
  NL: Live walls: alleen-lezen schermen voor de redactie op poort 8081 (`stats-collector-livewall`), met het afgelopen uur per radiostream, Owncast-stream en website als bewegende 3D-staven, een geheime link per wall, nieuwe links, een optionele lijst met toegestane IP-adressen en elke minuut nieuwe cijfers via Server-Sent Events.
- My dashboards: build your own dashboards with totals, charts, top content, editors and goals; charts switch between stacked, overlay and separate, totals compare with the previous period; admins and editors-in-chief can share a dashboard with everyone.
  NL: Mijn dashboards: maak je eigen dashboards met totalen, grafieken, topcontent, redacteuren en doelen; grafieken wisselen tussen gestapeld, over elkaar en los, totalen worden vergeleken met de vorige periode; beheerders en hoofdredacteuren kunnen een dashboard met iedereen delen.
- Facebook and Instagram posts and YouTube videos are linked to the website articles they point to, automatically by address or by hand; an article shows its linked posts and their social views.
  NL: Facebook- en Instagram-berichten en YouTube-video's worden gekoppeld aan de websiteartikelen waarnaar ze verwijzen, automatisch op adres of met de hand; een artikel toont de gekoppelde berichten en hun sociale weergaven.
- Editors get the social numbers of posts that link to their articles: a Social views column and numbers per platform.
  NL: Redacteuren krijgen de sociale cijfers van berichten die naar hun artikelen linken: een kolom Sociale weergaven en cijfers per platform.
- System design, roadmap and clickable UI sketch (`docs/`).
  NL: Systeemontwerp, roadmap en klikbare UI-schets (`docs/`).
- Default brand with light and dark theme tokens and logos (`branding/default/`).
  NL: Standaard huisstijl met kleuren voor licht en donker thema en logo's (`branding/default/`).
- Design for the release overview with change notes per release.
  NL: Ontwerp voor het releaseoverzicht met wijzigingen per release.
- Design for the Help button and the full manual on GitHub Pages.
  NL: Ontwerp voor de Help-knop en de volledige handleiding op GitHub Pages.
- Debian 13 installer (`install.sh`): PostgreSQL, Redis, pgBackRest, rclone, system services, setup link for the first administrator, optional nftables firewall.
  NL: Installatiescript voor Debian 13 (`install.sh`): PostgreSQL, Redis, pgBackRest, rclone, systeemdiensten, een installatielink voor de eerste beheerder en een optionele nftables-firewall.
- Application skeleton on port 8080, ready for a reverse proxy (Zoraxy guide included); forwarded headers are trusted only from configured proxy IPs.
  NL: Basis van de applicatie op poort 8080, klaar voor een reverse proxy (inclusief handleiding voor Zoraxy); doorgestuurde headers worden alleen vertrouwd van ingestelde proxy-IP's.
- Local accounts with Argon2id passwords, optional two-factor authentication (TOTP), roles Admin, Editor-in-chief, Editor and Staff.
  NL: Lokale accounts met Argon2id-wachtwoorden, optionele tweestapsverificatie (TOTP) en de rollen Beheerder, Hoofdredacteur, Redacteur en Medewerker.
- Settings for Microsoft 365 (Entra ID) sign-in and group-to-role mapping, prepared for phase 1.
  NL: Instellingen voor inloggen met Microsoft 365 (Entra ID) en het koppelen van groepen aan rollen, voorbereid voor fase 1.
- Modern interface with all menus in a left sidebar, light and dark mode, English and Dutch.
  NL: Moderne interface met alle menu's in een balk aan de linkerkant, licht en donker thema, Engels en Nederlands.
- Branding screen: logos, colours, fonts and channel colours with live preview, export and import.
  NL: Huisstijlscherm: logo's, kleuren, lettertypen en kanaalkleuren met live voorbeeld, exporteren en importeren.
- Info & updates: version details, update check, switch between the production and test channel, install any release from the interface with automatic rollback, release notes in tabs (New, Changed, Removed, Fixed).
  NL: Info & updates: versiegegevens, controleren op updates, wisselen tussen het productie- en testkanaal, elke release vanuit de interface installeren met automatisch terugdraaien, releasenotes in tabbladen (Nieuw, Gewijzigd, Verwijderd, Opgelost).
- Email: your own SMTP server with STARTTLS or SMTPS (TLS 1.2+), password or OAuth 2.0 (XOAUTH2), test button.
  NL: E-mail: je eigen SMTP-server met STARTTLS of SMTPS (TLS 1.2+), wachtwoord of OAuth 2.0 (XOAUTH2) en een testknop.
- Backup & restore: full and incremental backups of database and files, encrypted copies to FTP, FTPS and SCP/SFTP locations, schedule and retention, restore from a remote location.
  NL: Back-up & herstel: volledige en incrementele back-ups van database en bestanden, versleutelde kopieën naar FTP-, FTPS- en SCP/SFTP-locaties, planning en bewaartermijn, herstellen vanaf een externe locatie.
- Help button with the full manual in English and Dutch, also published on GitHub.
  NL: Helpknop met de volledige handleiding in het Engels en Nederlands, ook gepubliceerd op GitHub.
- Sources: add Icecast servers (listeners per mount point, average listening time and players with the admin password) and Owncast servers (viewers, every broadcast as a separate item, webhook for stream start and stop), with a connection test.
  NL: Bronnen: voeg Icecast-servers toe (luisteraars per mountpoint, gemiddelde luistertijd en spelers met het beheerwachtwoord) en Owncast-servers (kijkers, elke uitzending als apart item, webhook voor start en einde van de stream), met een verbindingstest.
- Dashboard with live listeners and viewers, peak today, minutes, a chart per 5 minutes, hour or day that can be stacked, overlaid or shown per source, totals per source and the top broadcasts.
  NL: Dashboard met live luisteraars en kijkers, piek van vandaag, minuten, een grafiek per 5 minuten, uur of dag die gestapeld, over elkaar of per bron getoond kan worden, totalen per bron en de best bekeken uitzendingen.
- Background worker with scheduler (stats-collector-worker) that polls the sources every 30 seconds and adds the numbers up per hour, day and month; raw samples are kept for one year.
  NL: Achtergrondworker met planner (stats-collector-worker) die de bronnen elke 30 seconden ophaalt en de cijfers optelt per uur, dag en maand; ruwe metingen worden een jaar bewaard.
- Sign in with Microsoft 365 (Entra ID, OpenID Connect with PKCE); the role comes from Microsoft 365 groups or app roles at every sign-in.
  NL: Inloggen met Microsoft 365 (Entra ID, OpenID Connect met PKCE); de rol komt bij elke keer inloggen uit Microsoft 365-groepen of app-rollen.
- Setting for the header with the visitor's real IP address behind Cloudflare (`SC_CLIENT_IP_HEADER`, e.g. `CF-Connecting-IP`).
  NL: Instelling voor de header met het echte IP-adres van de bezoeker achter Cloudflare (`SC_CLIENT_IP_HEADER`, bijv. `CF-Connecting-IP`).
- `stats-collector demo-data` adds demo sources with a week of numbers to try out the dashboard.
  NL: `stats-collector demo-data` voegt demobronnen met een week aan cijfers toe om het dashboard uit te proberen.
- WordPress plugin (Settings → Stats Collector): counts page views, unique visitors, reading time, read articles, share clicks, referrers and devices per article without cookies, and sends them every minute, signed with the site's secret. Download it under Sources.
  NL: WordPress-plugin (Instellingen → Stats Collector): telt zonder cookies paginaweergaven, unieke bezoekers, leestijd, gelezen artikelen, deelkliks, verwijzers en apparaten per artikel, en stuurt ze elke minuut ondertekend met het geheim van de site. Te downloaden onder Bronnen.
- Sources: WordPress sites with a site key and secret for the plugin.
  NL: Bronnen: WordPress-sites met een sitesleutel en geheim voor de plugin.
- Content page: top articles, broadcasts and streams per period, with filters for source, category and editor, and per item a chart, where readers came from and their devices.
  NL: Contentpagina: top artikelen, uitzendingen en streams per periode, met filters op bron, categorie en redacteur, en per item een grafiek, waar lezers vandaan kwamen en hun apparaten.
- Editors page: website numbers per editor. Admins and the editor-in-chief see everyone, an editor only their own numbers, staff no editor names at all (removed on the server).
  NL: Redacteurenpagina: websitecijfers per redacteur. Beheerders en de hoofdredactie zien iedereen, een redacteur alleen de eigen cijfers, medewerkers helemaal geen namen van redacteuren (op de server verwijderd).
- Authors are linked to their Stats Collector account by email address.
  NL: Auteurs worden via hun e-mailadres aan hun Stats Collector-account gekoppeld.
- Info shows the address the app sees for you, to check the reverse proxy and Cloudflare setup.
  NL: Info toont het adres dat de app van jou ziet, om de reverse proxy en Cloudflare te controleren.
- `stats-collector demo-data` also adds a demo website with a month of articles and editors.
  NL: `stats-collector demo-data` voegt ook een demowebsite met een maand aan artikelen en redacteuren toe.
- YouTube channels: connect with Google (OAuth), the whole channel history is imported, then views, watch time, likes, comments, shares and subscribers per day for the channel and every video, updated every three hours.
  NL: YouTube-kanalen: koppelen met Google (OAuth), de hele geschiedenis van het kanaal wordt opgehaald, daarna weergaven, kijktijd, likes, reacties, keren gedeeld en abonnees per dag voor het kanaal en elke video, elke drie uur bijgewerkt.
- Subscribers per day for the past, worked back from today's count with the daily gains and losses.
  NL: Abonnees per dag voor het verleden, teruggerekend vanaf het huidige aantal met de dagelijkse aanmeldingen en afmeldingen.
- Dashboard card "Website and video" with views per website and YouTube channel, stacked per hour or day.
  NL: Dashboardkaart "Website en video" met weergaven per website en YouTube-kanaal, gestapeld per uur of dag.
- Content page shows YouTube videos with views, watch time and average view duration.
  NL: De contentpagina toont YouTube-video's met weergaven, kijktijd en gemiddelde kijkduur.
- Facebook Pages and Instagram professional accounts: connect with Facebook (one Meta app for both, choose the Page or account when you manage several), two years of history, then views, reach, reactions, comments, shares, clicks, saves and followers per day for the account and every post, updated every hour.
  NL: Facebook-pagina's en professionele Instagram-accounts: koppelen met Facebook (één Meta-app voor beide, kies de pagina of het account als je er meerdere beheert), twee jaar historie, daarna weergaven, bereik, reacties, opmerkingen, keren gedeeld, klikken, opgeslagen en volgers per dag voor het account en elk bericht, elk uur bijgewerkt.
- Meta metric names that keep working when Meta renames them: known old and new names are tried automatically, and an administrator can set the Graph API version and their own names under Advanced.
  NL: Namen van Meta-metrics die blijven werken als Meta ze hernoemt: bekende oude en nieuwe namen worden automatisch geprobeerd, en een beheerder kan bij Geavanceerd de Graph API-versie en eigen namen instellen.
- Content page shows Facebook and Instagram posts with reach, likes or reactions per type, saves and clicks; the dashboard card shows them with total reach and followers.
  NL: De contentpagina toont Facebook- en Instagram-berichten met bereik, likes of reacties per soort, opgeslagen en klikken; de dashboardkaart toont ze met totaal bereik en volgers.
- Followers page: YouTube subscribers and Facebook and Instagram followers per day, per channel and stacked, over 30 days, 90 days or 12 months.
  NL: Pagina Volgers: YouTube-abonnees en Facebook- en Instagram-volgers per dag, per kanaal en gestapeld, over 30 dagen, 90 dagen of 12 maanden.
- Goals on followers, views, reach, interactions or listening/watching minutes, for all or chosen channels, with progress, pace, forecast and a chart with the target as a dashed line; every change of the target is kept in its history.
  NL: Doelen voor volgers, weergaven, bereik, interacties of luister-/kijkminuten, voor alle of gekozen kanalen, met voortgang, tempo, prognose en een grafiek met het doel als streepjeslijn; elke wijziging van het doel blijft bewaard in de historie.
- Optional email when a goal is reached or falls behind (at most weekly), and a Goals card on the dashboard.
  NL: Optionele mail als een doel gehaald is of achterloopt (hooguit wekelijks), en een kaart Doelen op het dashboard.

### Changed
- Updates now also install the system services shipped with the new version and restart the worker.
  NL: Updates installeren nu ook de systeemdiensten van de nieuwe versie en herstarten de worker.
- Reverse proxy headers are handled by the app itself; trusted proxies may be IP ranges (CIDR).
  NL: Headers van de reverse proxy worden door de app zelf verwerkt; vertrouwde proxy's mogen IP-reeksen (CIDR) zijn.
- Releases are built by pushing a version tag (`vX.Y.Z-rc.N` for a test build, `vX.Y.Z` for production).
  NL: Releases worden gebouwd door een versietag te pushen (`vX.Y.Z-rc.N` voor een testversie, `vX.Y.Z` voor productie).
- A merge into `develop` marked `[test-release]` builds the next test build automatically.
  NL: Een merge naar `develop` met `[test-release]` bouwt automatisch de volgende testversie.
- A release created by hand on GitHub (Releases → Draft a new release) is filled in automatically with notes and the package.
  NL: Een release die je zelf op GitHub aanmaakt (Releases → Draft a new release) wordt automatisch aangevuld met de releasenotes en het pakket.

### Fixed
- The online manual is published again with every release: its screenshot run now also starts the live wall service.
  NL: De online handleiding wordt weer bij elke release gepubliceerd: de screenshotronde start nu ook de livewall-dienst.
- Icecast servers without `status-json.xsl` (some hosting providers remove it): the numbers are now read from `admin/stats` with the admin user and password.
  NL: Icecast-servers zonder `status-json.xsl` (sommige hostingpartijen halen die weg): de cijfers worden nu uit `admin/stats` gelezen met de beheerder-gebruikersnaam en het wachtwoord.
- **Update now** and **Back up now** start right away again after the installer's first backup; before, the job waited for the hourly run.
  NL: **Nu bijwerken** en **Nu back-up maken** starten weer direct na de eerste back-up van het installatiescript; eerder wachtte de taak op de uurlijkse ronde.
- Downloaded update packages are removed after installing, and the pre-update database dump is readable only by the database user.
  NL: Gedownloade updatepakketten worden na installatie opgeruimd, en de databasedump van voor de update is alleen leesbaar voor de databasegebruiker.
