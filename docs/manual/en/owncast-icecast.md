# Sources: Owncast and Icecast

Add your streaming servers under **Administration → Sources**. Each server is polled every 30 seconds for the number of viewers (Owncast) or listeners (Icecast). You can add 2 to 5 of each, or more.

> New to sources? [Setting up sources: overview](sources.md) shows per platform where to go, what you need and which value goes in which field.

![Sources](../images/en-sources.png)

## Add a source

1. Click **Add source** and pick **Icecast (radio)** or **Owncast (video)**.
2. Fill in a **Name** (shown on the dashboard) and the **Server address**.
3. Optionally fill in the admin password (see below).
4. Click **Test connection**. You see the server name and, for Icecast, the mount points and their listeners right now.
5. Click **Save**. The first numbers appear on the dashboard within a minute.

The status column shows **Working** after a successful poll, or the reason the last poll failed (wrong password, server not reachable, ...). **Poll now** (the round arrow) polls straight away. Switching off **Collect from this source** pauses it without losing its numbers. Deleting a source also deletes all its numbers.

## Icecast

- **Server address**: the address of Icecast itself, e.g. `https://radio.example.org:8000`, without `/status-json.xsl`.
- **Mount points**: e.g. `/live, /jazz`. Leave empty to collect every mount the server reports. A configured mount that is not broadcasting counts as zero.
- **Admin user and password** (optional): `<admin-user>` and `<admin-password>` from `icecast.xml`. With it Stats Collector also reads the average listening time and which players are used (VLC, browser, smart speaker...). IP addresses of listeners are never stored.

Stats Collector reads `status-json.xsl`, available in Icecast 2.4 and later.

Some hosting providers remove `status-json.xsl` and change `status.xsl` so it no longer shows the mount points. Stats Collector then reads the same numbers from `admin/stats`, the page Icecast keeps for its own admin interface. That page needs the **admin user and password**: ask your hosting provider for them if you do not have them. Without them the source shows *This server has no public status page*.

### Where do I find the Icecast details?

- **Server address**: take the stream link and leave off the mount. A stream at `https://audio.example.org/mp3` has server address `https://audio.example.org` and mount point `/mp3`. Some servers use a port, such as `:8000`.
- **Your own Icecast server**: the admin user and password are in `icecast.xml` (on Debian `/etc/icecast2/icecast.xml`), in the block `<authentication>` as `<admin-user>` and `<admin-password>`. Check them by opening `https://<server>/admin/stats` in a browser.
- **Hosted Icecast** (a streaming provider, Centova Cast, AzuraCast…): ask the provider for the Icecast **admin** login. The *source* password your playout software uses to send the stream is a different one and does not work here. In AzuraCast you find it under **Station → Mount points / Broadcasting → Icecast admin password**.

## Owncast

- **Server address**: the address of your Owncast server, e.g. `https://live.example.org`.
- **Admin password** (optional): the Owncast admin password. Without it the public status is used, which gives the same viewer numbers.

Every broadcast becomes a separate item with its title and start and end time, so you can compare broadcasts under **Top broadcasts and streams** on the dashboard.

**Where do I find the Owncast admin password?** Open `https://<your Owncast>/admin` (user name `admin`). The password is under **Configuration → Server setup → Admin password**. A new Owncast server starts with `abc123`: change it there first.

### Webhook (recommended)

After saving, the edit window shows a **Webhook for Owncast** URL. In Owncast go to **Integrations → Webhooks → Create webhook**, paste the URL and select **Stream started** and **Stream stopped**. Broadcasts then start and end on the minute instead of at the next poll. The URL contains a secret; if it leaks, click **Renew** next to it and update the webhook in Owncast.

## Network

The Stats Collector server must be able to reach these addresses. When a source sits on the internal network, use its internal address. A self-signed certificate works if you switch off **Verify the server certificate**.
