# Reverse proxy and HTTPS (Zoraxy)

Stats Collector listens on plain HTTP port 8080. A reverse proxy in front of it handles HTTPS with a Let's Encrypt certificate. The [live wall](live-wall.md) uses port 8081 and its own host name.

## Zoraxy, step by step

1. **DNS**: create an A record (and AAAA if you use IPv6) for `stats.example.org` pointing to the Zoraxy server. Later add `live.example.org` for the live wall.
2. Open the Zoraxy web interface and go to **HTTP Proxy → Create Proxy Rules**.
3. Fill in:
   - **Proxy type**: Sub-domain
   - **Matching keyword / domain**: `stats.example.org`
   - **Target IP address or domain name with port**: `<ip-of-stats-server>:8080`
   - **Proxy target require TLS connection**: off (the app speaks HTTP behind the proxy)
   - **Create Credentials**: off
4. Click **Create Endpoint**.
5. Go to **TLS / SSL certificates → ACME**. Enter your email address, choose Let's Encrypt, add `stats.example.org` and request the certificate. Enable automatic renewal.
6. In the proxy rule, enable **Force HTTPS redirect** (HTTP → HTTPS).
7. On the Stats Collector server, make sure the Zoraxy IP is in `SC_TRUSTED_PROXIES` in `/etc/stats-collector/config.env` and that `SC_PUBLIC_URL` starts with `https://`. After changing it run `systemctl restart stats-collector-web`.

Check it: open `https://stats.example.org`. Under **Info & updates** the page loads without warnings, and after signing in the session cookie is marked *Secure*.

### Why the trusted proxy IP matters

The app only believes the `X-Forwarded-For` and `X-Forwarded-Proto` headers when they come from an IP in `SC_TRUSTED_PROXIES`. Anyone else could otherwise pretend to be another IP address, for example to dodge the login rate limit.

### Cloudflare in front of the proxy: the real visitor IP

When the public address goes through Cloudflare, `X-Forwarded-For` holds a Cloudflare address instead of the visitor's. Cloudflare sends the real address in the `CF-Connecting-IP` header. Tell Stats Collector to use it by adding this line to `/etc/stats-collector/config.env` (or run the installer with `--client-ip-header CF-Connecting-IP`):

```
SC_CLIENT_IP_HEADER=CF-Connecting-IP
```

and run `systemctl restart stats-collector-web`. The header is only read on requests from a trusted proxy, so it cannot be faked from outside. The audit log and the login rate limit then see the real visitor addresses.

### Firewall

When Zoraxy runs on another machine, only Zoraxy needs to reach port 8080. Run the installer again with `--firewall` to have nftables enforce this.

## Other proxies

### Nginx

```nginx
server {
    server_name stats.example.org;
    listen 443 ssl http2;
    # ssl_certificate lines from certbot
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
