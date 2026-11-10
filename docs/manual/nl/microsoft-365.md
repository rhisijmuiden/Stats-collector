# Microsoft 365 (Entra ID)

Collega's loggen in met hun Microsoft 365-account (knop **Inloggen met Microsoft 365** op de inlogpagina) en krijgen hun rol uit een Microsoft 365-groep. Je stelt dit in onder **Beheer → Rollen & inloggen**.

![Rollen & inloggen](../images/nl-sso.png)

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

Kopieer de **Object-ID** van elke groep naar **Rollen & inloggen → Rollen uit Microsoft 365-groepen**. Meerdere ID's per rol scheid je met komma's, en de waarde van een *app-rol* (App-registratie → App-rollen) werkt ook. Het lidmaatschap wordt bij elke keer inloggen gelezen: iemand toevoegen of verwijderen in Microsoft 365 verandert de rol bij de volgende keer inloggen. Zit iemand in meerdere groepen, dan geldt de hoogste rol (Beheerder, dan Hoofdredacteur, Redacteur, Medewerker); wie in geen van de groepen zit, krijgt de rol bij **Rol voor alle anderen in de organisatie**.

Is iemand lid van meer dan ongeveer 200 groepen, dan laat Microsoft de groepen weg uit het inlogtoken. Stats Collector leest ze dan uit Microsoft Graph; voeg daarvoor de gedelegeerde machtiging `GroupMember.Read.All` toe met beheerderstoestemming.

## 3. Aanzetten en testen

1. Vul de tenant-ID, client-ID en het clientgeheim in, koppel de groepen en zet **Inloggen met Microsoft 365 aanzetten** aan. Klik op **Opslaan**.
2. Open de inlogpagina in een privévenster en klik op **Inloggen met Microsoft 365**.
3. Na het inloggen kom je op het dashboard; je rol staat onderaan het menu. Onder **Gebruikers** staat het account met inlogmethode *Microsoft 365*.

Lukt het niet? De inlogpagina toont de reden, bijvoorbeeld een verkeerd clientgeheim of een verkeerde omleidings-URI. De meest gemaakte fout is een omleidings-URI die niet precies klopt: die moet het `https://`-adres zijn dat gebruikers openen, dus controleer `SC_PUBLIC_URL` (zie [Reverse proxy](reverse-proxy.md)).

## 4. Lokale accounts

Een bestaand lokaal account met hetzelfde e-mailadres wordt bij de eerste keer inloggen met Microsoft gekoppeld. Het houdt zijn wachtwoord en de rol die in Stats Collector is ingesteld, zodat je eerste beheerder altijd een werkend noodaccount blijft. Accounts die via Microsoft worden aangemaakt, krijgen hun rol bij elke keer inloggen uit Microsoft 365.

Laat **Lokale accounts mogen ook inloggen** aan totdat inloggen met Microsoft 365 werkt. Beheerders kunnen altijd met een lokaal account inloggen, dus een kapotte Entra-configuratie sluit je nooit buiten.
