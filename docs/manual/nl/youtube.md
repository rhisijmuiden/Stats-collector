# YouTube

De koppeling met YouTube komt in fase 2. Hij gebruikt de **YouTube Data API v3** (video's, abonnees) en de **YouTube Analytics API** (weergaven, kijktijd, gemiddelde kijkduur, gewonnen en verloren abonnees). Google vraagt verificatie voor de Analytics-scope, dus bereid het project nu al voor.

## 1. Google Cloud-project

1. Open [console.cloud.google.com](https://console.cloud.google.com) met het Google-account dat eigenaar (of beheerder) van het YouTube-kanaal is → **Nieuw project** *Stats Collector*.
2. **API's en services → Bibliotheek**: zet **YouTube Data API v3** en **YouTube Analytics API** aan.

## 2. OAuth-toestemmingsscherm

1. **API's en services → OAuth-toestemmingsscherm**. Gebruikerstype: **Extern** (staat het kanaal in je eigen Google Workspace, dan heeft *Intern* geen verificatie nodig).
2. Appnaam *Stats Collector*, supportadres, logo, homepage (`https://stats.example.org`), URL van het privacybeleid, geautoriseerd domein `example.org`.
3. Scopes: `https://www.googleapis.com/auth/youtube.readonly` en `https://www.googleapis.com/auth/yt-analytics.readonly`.
4. Voeg jezelf toe als testgebruiker, zodat je al kunt koppelen voor de verificatie rond is.
5. **App publiceren** en klik op **Voorbereiden voor verificatie**. Google vraagt om een video van de toestemmingsstap en een toelichting; gebruik dezelfde tekst als bij Meta.

## 3. Inloggegevens

**API's en services → Inloggegevens → Inloggegevens maken → OAuth-client-ID**, type **Webapplicatie**, omleidings-URI `https://stats.example.org/api/connectors/youtube/callback`. Bewaar de client-ID en het geheim voor fase 2.

## Limieten

- De Data API heeft een dagquotum van 10.000 eenheden; Stats Collector blijft daar ruim onder.
- Analytics-cijfers lopen één tot twee dagen achter; recente weergaven op de live wall worden geschat uit de verandering van het aantal weergaven.
