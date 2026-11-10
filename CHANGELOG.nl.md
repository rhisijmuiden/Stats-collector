# Wijzigingen

Alle belangrijke wijzigingen, nieuwste eerst, in het formaat van [Keep a Changelog](https://keepachangelog.com/nl/).
Testbuilds gebruiken de sectie `Unreleased`; bij een productierelease krijgt die het versienummer.

## [Unreleased]

### Toegevoegd
- Installatiescript voor Debian 13 (`install.sh`): PostgreSQL, Redis, pgBackRest, rclone, systeemdiensten, een installatielink voor de eerste beheerder en een optionele nftables-firewall.
- Basis van de applicatie op poort 8080, klaar voor een reverse proxy (inclusief handleiding voor Zoraxy); doorgestuurde headers worden alleen vertrouwd van ingestelde proxy-IP's.
- Lokale accounts met Argon2id-wachtwoorden, optionele tweestapsverificatie (TOTP) en de rollen Beheerder, Hoofdredacteur, Redacteur en Medewerker.
- Instellingen voor inloggen met Microsoft 365 (Entra ID) en het koppelen van groepen aan rollen, voorbereid voor fase 1.
- Moderne interface met alle menu's in een balk aan de linkerkant, licht en donker thema, Engels en Nederlands.
- Huisstijlscherm: logo's, kleuren, lettertypen en kanaalkleuren met live voorbeeld, exporteren en importeren.
- Info & updates: versiegegevens, controleren op updates, wisselen tussen het productie- en testkanaal, elke release vanuit de interface installeren met automatisch terugdraaien, releasenotes in tabbladen (Nieuw, Gewijzigd, Verwijderd, Opgelost).
- E-mail: je eigen SMTP-server met STARTTLS of SMTPS (TLS 1.2+), wachtwoord of OAuth 2.0 (XOAUTH2) en een testknop.
- Back-up & herstel: volledige en incrementele back-ups van database en bestanden, versleutelde kopieën naar FTP-, FTPS- en SCP/SFTP-locaties, planning en bewaartermijn, herstellen vanaf een externe locatie.
- Helpknop met de volledige handleiding in het Engels en Nederlands, ook gepubliceerd op GitHub.
