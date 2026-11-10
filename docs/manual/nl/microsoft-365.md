# Microsoft 365 (Entra ID)

Vanaf fase 1 loggen collega's in met hun Microsoft 365-account en krijgen ze hun rol uit een Microsoft 365-groep. De app-registratie en de instellingen onder **Beheer → Rollen & inloggen** kun je nu al aanmaken.

## 1. App-registratie

1. Open het [Entra-beheercentrum](https://entra.microsoft.com) → **Identiteit → Toepassingen → App-registraties → Nieuwe registratie**.
2. Naam: *Stats Collector*. Ondersteunde accounttypen: **Alleen accounts in deze organisatiemap (één tenant)**.
3. Omleidings-URI: platform **Web**, waarde: kopieer die uit **Rollen & inloggen → Omleidings-URI** in Stats Collector (zoiets als `https://stats.example.org/api/auth/entra/callback`).
4. Klik op **Registreren**. Kopieer de **Applicatie-ID (client)** en **Directory-ID (tenant)** naar Stats Collector.
5. **Certificaten en geheimen → Nieuw clientgeheim**, 24 maanden geldig. Kopieer de *Waarde* (niet de ID) naar **Clientgeheim**. Zet een herinnering in je agenda om het op tijd te vernieuwen.
6. **Tokenconfiguratie → Groepsclaim toevoegen → Beveiligingsgroepen**, voor het *ID*-token, formaat *Groeps-ID*.
7. **API-machtigingen**: `openid`, `profile`, `email` en `User.Read` (gedelegeerd) zijn genoeg. Klik op **Beheerderstoestemming verlenen**.

## 2. Groepen voor rollen

Maak vier beveiligingsgroepen in Microsoft 365 (de namen zijn een voorbeeld):

| Rol | Groep |
| --- | --- |
| Beheerder | `SC-Admins` |
| Hoofdredacteur | `SC-EditorsInChief` |
| Redacteur | `SC-Editors` |
| Medewerker | alle anderen in de organisatie (geen groep nodig) |

Kopieer de **Object-ID** van elke groep naar **Rollen & inloggen → Rollen uit Microsoft 365-groepen**. Het lidmaatschap wordt bij elke keer inloggen gelezen: iemand toevoegen of verwijderen in Microsoft 365 verandert de rol bij de volgende keer inloggen.

## 3. Lokale accounts

Laat **Lokale accounts mogen ook inloggen** aan totdat inloggen met Microsoft 365 werkt. Beheerders kunnen altijd met een lokaal account inloggen, dus een kapotte Entra-configuratie sluit je nooit buiten.
