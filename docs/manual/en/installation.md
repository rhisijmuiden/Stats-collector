# Installation on Debian 13

Stats Collector runs on a dedicated Debian 13 (Trixie) server or virtual machine. The installer sets up everything: database, background services, backups and the application itself.

## Requirements

| | Minimum | Recommended |
| --- | --- | --- |
| CPU | 2 cores | 4 cores |
| Memory | 4 GB | 8 GB |
| Disk | 20 GB | 50 GB or more (backups and one year of raw data) |
| Operating system | Debian 13, freshly installed | |
| Network | Outgoing HTTPS to GitHub, Debian and the platform APIs | |

The server needs a host name that users can reach through your reverse proxy, for example `stats.example.org`.

## Install

Log in as root (or use `sudo -i`) and run:

```bash
curl -fsSL https://raw.githubusercontent.com/rhisijmuiden/stats-collector/develop/install.sh -o install.sh
bash install.sh
```

The installer asks four questions. Press Enter to accept the default.

| Question | Meaning |
| --- | --- |
| Update channel | `test` follows new features first (default during development), `production` only stable releases. You can switch later in **Info & updates**. |
| Public URL | The address users type, e.g. `https://stats.example.org`. |
| Reverse proxy IP addresses | The IP of your Zoraxy (or other proxy). Only these addresses may tell the app the visitor's real IP. |
| Web port / listen address | Default `8080` on all interfaces. Use `127.0.0.1` when the proxy runs on the same server. |

To install without questions:

```bash
bash install.sh --channel test --public-url https://stats.example.org --proxy-ips 192.0.2.10 -y
```

Add `--firewall` to let nftables block port 8080 for everyone except the proxy.

## What the installer does

1. Checks that this is Debian 13, that you are root and that the network works.
2. Installs Python, PostgreSQL, Redis, pgBackRest and rclone from the Debian repositories.
3. Creates the system user `statscollector`, the folders `/opt/stats-collector`, `/var/lib/stats-collector` and `/etc/stats-collector`.
4. Generates secrets in `/etc/stats-collector/config.env`, creates the database, and enables WAL archiving for incremental backups.
5. Downloads the newest release of your channel from GitHub, checks its SHA-256 checksum and installs it with its own Python environment.
6. Runs the database migrations and starts the services.
7. Prints a one-time link to create the first administrator.

Running the installer again is safe. It keeps your configuration and repairs anything that is missing.

## First administrator

Open the link printed at the end, for example `https://stats.example.org/setup?token=…`, and create your account. The link works once and expires after 24 hours. Make a new one with:

```bash
stats-collector setup-link
```

## Services

| Service | What it does |
| --- | --- |
| `stats-collector-web` | The web application and API on port 8080 |
| `stats-collector-ops.path` / `.service` | Runs updates, backups and restores that administrators start in the interface |
| `stats-collector-backup.timer` | Checks every hour whether a scheduled backup is due |

Next step: [Reverse proxy and HTTPS](reverse-proxy.md).
