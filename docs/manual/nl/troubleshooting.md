# Problemen oplossen

## Logboeken

| Wat | Opdracht |
| --- | --- |
| Webapplicatie | `journalctl -u stats-collector-web -f` |
| Updates, back-ups, herstel | `journalctl -u stats-collector-ops -n 200`, of het logboek op de pagina terwijl het loopt |
| Logboeken van eerdere taken | `/var/lib/stats-collector/ops/job-<id>.log` |
| pgBackRest | `/var/log/pgbackrest/` |
| PostgreSQL | `journalctl -u postgresql@17-main` |

## Command line

```bash
stats-collector version             # geïnstalleerde versie en kanaal
stats-collector setup-link          # eenmalige link voor de eerste beheerder
stats-collector reset-password E-MAIL
stats-collector migrate             # databasemigraties uitvoeren
stats-collector ops run-pending     # taken in de wachtrij nu uitvoeren (root)
stats-collector backup full|incr    # nu een back-up maken (root)
stats-collector restore --target ID --label LABEL   # terugzetten vanaf een externe locatie (root)
```

## Veelvoorkomende problemen

**De pagina laadt niet via de proxy.** Controleer `curl http://127.0.0.1:8080/api/health` op de server. Werkt dat, controleer dan de proxyregel en of poort 8080 vanaf de proxy bereikbaar is (firewall).

**Ik word direct na het inloggen weer uitgelogd.** De publieke URL begint met `https://` maar de proxy levert gewone HTTP aan de browser, of andersom. Laat `SC_PUBLIC_URL` overeenkomen met het adres in de browser.

**Een taak blijft op "In de wachtrij" staan.** De ops-dienst draait niet: `systemctl status stats-collector-ops.path`. Start hem met `systemctl enable --now stats-collector-ops.path`.

**"GitHub is niet bereikbaar".** De server heeft uitgaand HTTPS nodig naar `api.github.com` en `github.com` om updates te zoeken en te downloaden.

**Back-uptest via SFTP geeft "permission denied".** Controleer gebruikersnaam en sleutel, en of die gebruiker de map mag aanmaken. Plak bij inloggen met een sleutel de volledige privésleutel inclusief de regels met `BEGIN` en `END`.

**De update is mislukt.** De vorige versie en de database zijn automatisch teruggezet. Het taaklogboek op de Info-pagina toont de reden. Meld het probleem met dat logboek erbij.
