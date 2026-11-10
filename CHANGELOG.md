# Changelog

All notable changes to Stats Collector are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/). The app shows these notes per release under **Info → Releases**, in the tabs New, Changed, Fixed and Removed.

Each entry is written in English with a Dutch translation on the line below, prefixed `NL:`.

## [Unreleased]

### Added
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
- **Update now** and **Back up now** start right away again after the installer's first backup; before, the job waited for the hourly run.
  NL: **Nu bijwerken** en **Nu back-up maken** starten weer direct na de eerste back-up van het installatiescript; eerder wachtte de taak op de uurlijkse ronde.
- Downloaded update packages are removed after installing, and the pre-update database dump is readable only by the database user.
  NL: Gedownloade updatepakketten worden na installatie opgeruimd, en de databasedump van voor de update is alleen leesbaar voor de databasegebruiker.
