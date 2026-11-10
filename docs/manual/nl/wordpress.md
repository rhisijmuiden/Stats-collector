# WordPress

Vanaf fase 2 levert Stats Collector een eigen WordPress-plugin. Die telt paginaweergaven, unieke en terugkerende bezoekers, verwijzers, apparaten en leestijd per artikel zonder cookies (geen cookiebanner nodig) en stuurt ze elke minuut naar Stats Collector. De plugin stuurt ook auteur, categorie en tags mee, zodat cijfers per redacteur getoond kunnen worden.

## Wat je gaat doen (fase 2)

1. In Stats Collector: **Bronnen → WordPress → Site toevoegen**. Kopieer de API-sleutel en het geheim.
2. In WordPress: **Plugins → Nieuwe plugin → Plugin uploaden**, kies `stats-collector.zip` (te downloaden uit Stats Collector en van de GitHub-releases) en activeer hem.
3. **Instellingen → Stats Collector**: plak de URL van Stats Collector, de API-sleutel en het geheim. Klik op **Verbinding testen**.
4. Herhaal dit voor elke site (2 tot 5 sites verwacht).

## Nu al voorbereiden

- Zorg dat elke site WordPress 6.4 of nieuwer en PHP 8.1 of nieuwer draait.
- Controleer dat de WordPress-server `https://stats.example.org` kan bereiken (uitgaand HTTPS).
- Bepaal welke WordPress-gebruikers redacteur zijn; in fase 2 koppel je ze aan gebruikers in Stats Collector.

*Deze pagina wordt aangevuld met schermafbeeldingen als de plugin verschijnt.*
