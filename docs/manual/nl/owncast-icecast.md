# Owncast en Icecast

De koppelingen voor streams komen in fase 1. Beide worden elke 30 seconden opgevraagd voor live kijkers en luisteraars.

## Owncast (2 tot 5 servers)

Per server heb je nodig:

- de URL, bijv. `https://live.example.org`;
- het **beheerderswachtwoord** (Owncast-beheer → *Server setup → Admin password*). Stats Collector gebruikt de admin-API voor kijkersaantallen en sessies.

Optioneel: voeg in Owncast onder **Integrations → Webhooks** een webhook toe voor *Stream started* en *Stream stopped* naar de URL die Stats Collector toont, zodat elke uitzending meteen een apart item wordt.

## Icecast (2 tot 5 mounts)

Per server heb je nodig:

- de URL, bijv. `https://radio.example.org:8000`;
- de mountpoints, bijv. `/live.mp3`;
- de **admin-gebruiker en het wachtwoord** (`<admin-user>` en `<admin-password>` in `icecast.xml`). Zonder die gegevens leest Stats Collector nog steeds het aantal luisteraars uit `status-json.xsl`, maar niet hoe lang elke luisteraar blijft.

Zorg dat de Stats Collector-server deze URL's kan bereiken.
