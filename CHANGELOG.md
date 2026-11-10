# Changelog

All notable changes are listed here, newest first, in [Keep a Changelog](https://keepachangelog.com) format.
Test builds use the `Unreleased` section; a production release renames it to the version number.
The Dutch translation is in [CHANGELOG.nl.md](CHANGELOG.nl.md). The app shows both under **Info → Releases**.

## [Unreleased]

### Added
- Debian 13 installer (`install.sh`): PostgreSQL, Redis, pgBackRest, rclone, system services, setup link for the first administrator, optional nftables firewall.
- Application skeleton on port 8080, ready for a reverse proxy (Zoraxy guide included); forwarded headers are trusted only from configured proxy IPs.
- Local accounts with Argon2id passwords, optional two-factor authentication (TOTP), roles Admin, Editor-in-chief, Editor and Staff.
- Settings for Microsoft 365 (Entra ID) sign-in and group-to-role mapping, prepared for phase 1.
- Modern interface with all menus in a left sidebar, light and dark mode, English and Dutch.
- Branding screen: logos, colours, fonts and channel colours with live preview, export and import.
- Info & updates: version details, update check, switch between the production and test channel, install any release from the interface with automatic rollback, release notes in tabs (New, Changed, Removed, Fixed).
- Email: your own SMTP server with STARTTLS or SMTPS (TLS 1.2+), password or OAuth 2.0 (XOAUTH2), test button.
- Backup & restore: full and incremental backups of database and files, encrypted copies to FTP, FTPS and SCP/SFTP locations, schedule and retention, restore from a remote location.
- Help button with the full manual in English and Dutch, also published on GitHub.
