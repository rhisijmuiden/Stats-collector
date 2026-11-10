# Live wall

Een live wall is een alleen-lezen scherm voor een tv op de redactievloer. Hij toont het afgelopen uur per kanaal als bewegende 3D-staven: luisteraars per radiostream, kijkers per Owncast-stream en paginaweergaven per website, met het aantal van dit moment in grote cijfers. Er is geen login nodig: elke wall heeft een eigen lange, onraadbare link.

![Een live wall](../images/nl-live-wall.png)

## Een wall maken

**Beheer → Live walls** (alleen beheerders) toont de walls met hun link en een klein voorbeeld van wat het scherm laat zien.

![Live walls](../images/nl-livewalls.png)

1. Klik op **Nieuwe live wall**.
2. **Naam**: voor jezelf, bijv. *Redactie*. **Titel op het scherm**: staat bovenaan de wall; leeg betekent de naam.
3. **Kanalen**: de Icecast-, Owncast- en WordPress-bronnen die je wilt tonen. Niets gekozen betekent alles.
4. **Toegestane adressen** (optioneel): IP-adressen of netwerken, gescheiden door komma's, die de wall mogen openen, bijvoorbeeld het openbare IP-adres van de redactie. Leeg betekent iedereen met de link.
5. Sla op, klik op **Link kopiëren** en open de link op de tv in een browser op volledig scherm (kioskmodus).

De wall werkt zichzelf bij: de server zet elke minuut nieuwe cijfers klaar en stuurt ze naar het scherm. Valt de verbinding weg, dan maakt het scherm zelf opnieuw verbinding; komen er vijf minuten geen verse cijfers, dan meldt de onderste regel dat.

- **Nieuwe link** (ronde pijlen) maakt een nieuwe link. De oude link werkt meteen niet meer; gebruik dit als een link te breed is gedeeld.
- Zet je **Deze wall tonen** uit, of verwijder je de wall, dan werkt de link niet meer.
- De wall gebruikt de kleuren van **Beheer → Huisstijl** (de live-wallkleuren) en de kanaalkleuren.

## Wat staat er op de wall

| Kanaal | Getal | Staven (elk 5 minuten) | Hoe vers |
| --- | --- | --- | --- |
| Icecast | Luisteraars bij de laatste meting | Gemiddeld aantal luisteraars | Live (elke 30 seconden gemeten) |
| Owncast | Kijkers bij de laatste meting | Gemiddeld aantal kijkers | Live (elke 30 seconden gemeten) |
| Website | Paginaweergaven in de laatste 5 minuten | Paginaweergaven | Live (de plugin meldt elke minuut) |

De totalen bovenaan tellen alle luisteraars, alle kijkers en alle paginaweergaven op. YouTube, Facebook en Instagram geven alleen hele dagen door, daarom staan ze niet op de wall.

## Adres en reverse proxy

De wall draait als eigen kleine dienst, `stats-collector-livewall`, op poort 8081. Die kan niet bij de database of de beheerfuncties: hij leest alleen de cijfers die de worker klaarzet.

1. Maak een DNS-record voor een aparte hostnaam, bijv. `live.example.org`, en een proxyregel in Zoraxy naar `<ip-van-stats-server>:8081` met HTTPS, net als het hoofdadres (zie [Reverse proxy](reverse-proxy.md)).
2. Zet het adres in `/etc/stats-collector/config.env`:

   ```
   SC_LIVEWALL_URL=https://live.example.org
   ```

   en voer `systemctl restart stats-collector-web` uit. De links onder **Live walls** gebruiken dan dit adres. Zonder deze regel wijzen ze naar de hoofdhostnaam op poort 8081.

Met `--firewall` laat het installatiescript poort 8081 alleen toe vanaf de proxy. Verzoeken zijn beperkt tot 120 per minuut per IP-adres. Server-Sent Events vragen dat de proxy antwoorden niet buffert; Zoraxy geeft ze ongewijzigd door.
