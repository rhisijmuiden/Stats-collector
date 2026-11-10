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
