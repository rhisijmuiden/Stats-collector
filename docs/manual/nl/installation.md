# Installatie op Debian 13

Stats Collector draait op een eigen Debian 13 (Trixie)-server of virtuele machine. Het installatiescript regelt alles: database, achtergronddiensten, back-ups en de applicatie zelf.

## Systeemeisen

| | Minimaal | Aanbevolen |
| --- | --- | --- |
| CPU | 2 cores | 4 cores |
| Geheugen | 4 GB | 8 GB |
| Schijf | 20 GB | 50 GB of meer (back-ups en een jaar ruwe data) |
| Besturingssysteem | Debian 13, schone installatie | |
| Netwerk | Uitgaand HTTPS naar GitHub, Debian en de API's van de platforms | |

De server heeft een hostnaam nodig die gebruikers via je reverse proxy bereiken, bijvoorbeeld `stats.example.org`.

## Installeren

Log in als root (of gebruik `sudo -i`) en voer uit:

```bash
curl -fsSL https://raw.githubusercontent.com/rhisijmuiden/stats-collector/develop/install.sh -o install.sh
bash install.sh
```

Het script stelt vier vragen. Druk op Enter om de standaardwaarde te nemen.

| Vraag | Betekenis |
| --- | --- |
| Update channel | `test` krijgt nieuwe functies als eerste (standaard tijdens de ontwikkelfase), `production` alleen stabiele releases. Je kunt later wisselen in **Info & updates**. |
| Public URL | Het adres dat gebruikers intypen, bijv. `https://stats.example.org`. |
| Reverse proxy IP addresses | Het IP-adres van je Zoraxy (of andere proxy). Alleen deze adressen mogen de app het echte IP-adres van de bezoeker doorgeven. |
| Web port / listen address | Standaard `8080` op alle netwerkkaarten. Kies `127.0.0.1` als de proxy op dezelfde server draait. |

Zonder vragen installeren:

```bash
bash install.sh --channel test --public-url https://stats.example.org --proxy-ips 192.0.2.10 -y
```

Voeg `--client-ip-header CF-Connecting-IP` toe als het openbare adres via Cloudflare loopt (zie [Reverse proxy](reverse-proxy.md)).

Met `--firewall` blokkeert nftables poort 8080 voor iedereen behalve de proxy.

## Wat het script doet

1. Controleert dat dit Debian 13 is, dat je root bent en dat het netwerk werkt.
2. Installeert Python, PostgreSQL, Redis, pgBackRest en rclone uit de Debian-repositories.
3. Maakt de systeemgebruiker `statscollector` en de mappen `/opt/stats-collector`, `/var/lib/stats-collector` en `/etc/stats-collector` aan.
4. Genereert geheimen in `/etc/stats-collector/config.env`, maakt de database aan en zet WAL-archivering aan voor incrementele back-ups.
5. Downloadt de nieuwste release van je kanaal van GitHub, controleert de SHA-256-checksum en installeert hem met een eigen Python-omgeving.
6. Voert de databasemigraties uit en start de diensten.
7. Toont een eenmalige link om de eerste beheerder aan te maken.

Het script opnieuw draaien kan altijd. Je configuratie blijft behouden en wat ontbreekt wordt hersteld.

## Eerste beheerder

Open de link die aan het eind getoond wordt, bijvoorbeeld `https://stats.example.org/setup?token=…`, en maak je account aan. De link werkt één keer en verloopt na 24 uur. Een nieuwe maak je met:

```bash
stats-collector setup-link
```

## Diensten

| Dienst | Wat het doet |
| --- | --- |
| `stats-collector-web` | De webapplicatie en API op poort 8080 |
| `stats-collector-worker` | Haalt de bronnen op (Icecast, Owncast) en telt elke 5 minuten de cijfers op |
| `stats-collector-ops.path` / `.service` | Voert updates, back-ups en herstel uit die beheerders in de interface starten |
| `stats-collector-backup.timer` | Controleert elk uur of er een geplande back-up moet draaien |

Volgende stap: [Reverse proxy en HTTPS](reverse-proxy.md).
