# Reverse proxy en HTTPS (Zoraxy)

Stats Collector luistert op gewone HTTP-poort 8080. Een reverse proxy ervoor regelt HTTPS met een Let's Encrypt-certificaat. De live wall (vanaf fase 3) gebruikt poort 8081 en een eigen hostnaam.

## Zoraxy, stap voor stap

1. **DNS**: maak een A-record (en AAAA bij IPv6) voor `stats.example.org` dat naar de Zoraxy-server wijst. Voeg later `live.example.org` toe voor de live wall.
2. Open de webinterface van Zoraxy en ga naar **HTTP Proxy → Create Proxy Rules**.
3. Vul in:
   - **Proxy type**: Sub-domain
   - **Matching keyword / domain**: `stats.example.org`
   - **Target IP address or domain name with port**: `<ip-van-stats-server>:8080`
   - **Proxy target require TLS connection**: uit (de app spreekt HTTP achter de proxy)
   - **Create Credentials**: uit
4. Klik op **Create Endpoint**.
5. Ga naar **TLS / SSL certificates → ACME**. Vul je e-mailadres in, kies Let's Encrypt, voeg `stats.example.org` toe en vraag het certificaat aan. Zet automatisch vernieuwen aan.
6. Zet in de proxyregel **Force HTTPS redirect** aan (HTTP → HTTPS).
7. Controleer op de Stats Collector-server dat het IP van Zoraxy in `SC_TRUSTED_PROXIES` staat in `/etc/stats-collector/config.env` en dat `SC_PUBLIC_URL` met `https://` begint. Voer na een wijziging `systemctl restart stats-collector-web` uit.

Controle: open `https://stats.example.org`. Onder **Info & updates** laadt de pagina zonder waarschuwingen, en na het inloggen is de sessiecookie gemarkeerd als *Secure*.

### Waarom het vertrouwde proxy-IP belangrijk is

De app gelooft de headers `X-Forwarded-For` en `X-Forwarded-Proto` alleen als ze van een IP-adres uit `SC_TRUSTED_PROXIES` komen. Anders zou iedereen zich als een ander IP-adres kunnen voordoen, bijvoorbeeld om de beperking op inlogpogingen te omzeilen.

### Firewall

Als Zoraxy op een andere machine draait, hoeft alleen Zoraxy poort 8080 te bereiken. Draai het installatiescript opnieuw met `--firewall` om dat met nftables af te dwingen.

## Andere proxy's

### Nginx

```nginx
server {
    server_name stats.example.org;
    listen 443 ssl http2;
    # ssl_certificate-regels van certbot
    client_max_body_size 10m;
    location / {
        proxy_pass http://10.0.0.20:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Caddy

```caddy
stats.example.org {
    reverse_proxy 10.0.0.20:8080
}
```

### Traefik (labels)

```yaml
- traefik.http.routers.stats.rule=Host(`stats.example.org`)
- traefik.http.routers.stats.tls.certresolver=letsencrypt
- traefik.http.services.stats.loadbalancer.server.port=8080
```
