# WordPress

From phase 2 Stats Collector ships its own WordPress plugin. It counts page views, unique and returning visitors, referrers, devices and reading time per article without cookies (no cookie banner needed) and sends them every minute to Stats Collector. It also sends the author, category and tags, so numbers can be shown per editor.

## What you will do (phase 2)

1. In Stats Collector: **Sources → WordPress → Add site**. Copy the API key and secret.
2. In WordPress: **Plugins → Add new → Upload plugin**, choose `stats-collector.zip` (downloadable from Stats Collector and from GitHub releases), and activate it.
3. **Settings → Stats Collector**: paste the URL of Stats Collector, the API key and the secret. Click **Test connection**.
4. Repeat for every site (2 to 5 sites are expected).

## Prepare now

- Make sure each site runs WordPress 6.4 or newer and PHP 8.1 or newer.
- Check that the WordPress server can reach `https://stats.example.org` (outgoing HTTPS).
- Decide which WordPress users are editors; they are linked to Stats Collector users in phase 2.

*This page is completed with screenshots when the plugin is released.*
