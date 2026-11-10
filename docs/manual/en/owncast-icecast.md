# Owncast and Icecast

The stream connectors arrive in phase 1. Both are polled every 30 seconds for live viewers and listeners.

## Owncast (2 to 5 servers)

You need per server:

- the URL, e.g. `https://live.example.org`;
- the **admin password** (Owncast admin → *Server setup → Admin password*). Stats Collector uses the admin API for viewer numbers and sessions.

Optional: in Owncast **Integrations → Webhooks** add a webhook for *Stream started* and *Stream stopped* to the URL Stats Collector will show, so every broadcast becomes a separate item immediately.

## Icecast (2 to 5 mounts)

You need per server:

- the URL, e.g. `https://radio.example.org:8000`;
- the mount points, e.g. `/live.mp3`;
- the **admin user and password** (`<admin-user>` and `<admin-password>` in `icecast.xml`). Without it Stats Collector can still read listener counts from `status-json.xsl`, but not how long each listener stays.

Make sure the Stats Collector server can reach these URLs.
