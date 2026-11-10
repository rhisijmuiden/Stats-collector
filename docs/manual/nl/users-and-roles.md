# Eerste keer inloggen, gebruikers en rollen

## Inloggen

Log in met je e-mailadres en wachtwoord. Na tien foute pogingen vanaf hetzelfde adres binnen vijf minuten wordt inloggen een paar minuten geblokkeerd.

## Tweestapsverificatie

Elk lokaal account kan tweestapsverificatie aanzetten: **Mijn profiel** (klik op je initialen onderaan het menu) → **Tweestapsverificatie → Aanzetten**. Voeg de sleutel toe aan een authenticator-app zoals Microsoft Authenticator, Google Authenticator of 1Password en vul de code in die de app toont. Vanaf dan vraagt het inloggen om de 6-cijferige code.

Telefoon kwijt? Een beheerder op de server kan het wachtwoord resetten; daarmee gaat tweestapsverificatie ook uit:

```bash
stats-collector reset-password naam@example.org
```

## Gebruikers

Beheerders beheren accounts onder **Beheer → Gebruikers**: toevoegen, rol wijzigen, uitschakelen, wachtwoord resetten of verwijderen. Er is altijd minstens één actieve beheerder; de app weigert de laatste te verwijderen.

## Rollen

| Rol | Ziet | Mag |
| --- | --- | --- |
| Beheerder | Alles | Bronnen, gebruikers, huisstijl, e-mail, back-up, updates, live walls |
| Hoofdredacteur | Alles, ook cijfers per redacteur | Dashboards, rapporten en doelen; rapporten versturen |
| Redacteur | Alle items en kanalen, plus de eigen redacteurscijfers | Eigen dashboards, rapporten op aanvraag |
| Medewerker | Alle items, kanalen, volgers en doelen zonder namen van redacteuren | Alleen bekijken |

Namen van redacteuren en cijfers per redacteur worden op de server verwijderd voordat de gegevens de browser van Medewerkers en Redacteuren bereiken.

## Microsoft 365

Collega's kunnen inloggen met hun Microsoft 365-account en krijgen hun rol uit een app-rol of groep in Microsoft 365: zie [Microsoft 365](microsoft-365.md).
