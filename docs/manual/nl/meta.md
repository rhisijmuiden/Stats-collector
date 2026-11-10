# Meta: Facebook en Instagram

De koppeling met Facebook en Instagram komt in fase 3. De App Review van Meta duurt dagen tot weken, dus begin nu. Je hebt nodig:

- een **Meta Business-portfolio** (Business Manager) dat **geverifieerd** is (voor dit project al gedaan);
- de **Facebook-pagina** die je wilt meten, met jou als beheerder in het Business-portfolio;
- het **professionele Instagram-account** (Zakelijk of Creator) dat aan die pagina gekoppeld is.

## 1. App aanmaken

1. Ga naar [developers.facebook.com/apps](https://developers.facebook.com/apps) → **App maken**.
2. Toepassing: **Overig** → apptype **Zakelijk**.
3. Naam: *Stats Collector*, contactadres, en kies je geverifieerde **Business-portfolio**.
4. Vul bij **App-instellingen → Basis** de URL van het privacybeleid, de URL van de voorwaarden, het app-icoon (1024×1024) en de categorie *Bedrijven en pagina's* in. Sla op.

## 2. Producten toevoegen

- **Facebook Login for Business** (eenmalig door een beheerder gebruikt om toegang tot de pagina te geven).
- **Instagram Graph API** (via *Product toevoegen → Instagram*), kies *API-instelling met Facebook-aanmelding*.

## 3. Machtigingen aanvragen

| Machtiging | Waarom |
| --- | --- |
| `pages_show_list` | De pagina's tonen die de beheerder beheert |
| `pages_read_engagement` | Berichten, reacties, opmerkingen, deelacties, volgers |
| `read_insights` | Statistieken van pagina en berichten (bereik, weergaven, klikken) |
| `business_management` | Pagina's in het Business-portfolio |
| `instagram_basic` | Instagram-account en media |
| `instagram_manage_insights` | Instagram-bereik, weergaven, opslaan, profielbezoeken |

## 4. App Review

1. **App Review → Machtigingen en functies**: klik voor elke machtiging hierboven op **Geavanceerde toegang aanvragen**.
2. Beschrijf per machtiging het gebruik, in het Engels: *"Stats Collector is an internal analytics dashboard for our newsroom. An administrator connects our own Page and Instagram account once; we read insights for our own content and show them to staff in dashboards and monthly reports. No data is shared with third parties."*
3. Upload een korte schermopname. Meta wil de inlogstap zien en waar de gegevens verschijnen. Zolang de koppeling nog niet bestaat, neem je het dashboard van Stats Collector op en leg je uit welke cijfers er komen; Meta kan om een nieuwe opname vragen zodra de koppeling er is (fase 3).
4. Vul de **vragen over gegevensverwerking** in en dien de aanvraag in.
5. Zet de app na goedkeuring in de modus **Live**.

Meta wijzigt regelmatig de namen van statistieken; Stats Collector houdt die instelbaar, zodat een nieuwe naam de koppeling niet breekt.

*Schermafbeeldingen van deze stappen komen erbij als de koppeling gebouwd wordt.*
