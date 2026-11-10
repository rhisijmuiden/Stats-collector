# Stats Collector

Self-hosted statistics and reporting platform for media teams. It collects reach, engagement and audience numbers from WordPress, Facebook, Instagram, YouTube, Owncast and Icecast, combines them in one dashboard, and emails branded reports on demand or on a schedule.

> Status: phase 0 (foundation). Install it on Debian 13 with `install.sh`; see the [manual](docs/manual/en/README.md) ([Nederlands](docs/manual/nl/README.md)).

- Manual: [English](docs/manual/en/README.md) · [Nederlands](docs/manual/nl/README.md)
- System design and roadmap: [docs/DESIGN.md](docs/DESIGN.md)
- Changes: [CHANGELOG.md](CHANGELOG.md) · [CHANGELOG.nl.md](CHANGELOG.nl.md)
- Clickable UI sketch: [docs/mockup/index.html](docs/mockup/index.html) (open in a browser; example data only)
- Default brand: [branding/](branding/)

## Highlights

- Runs on Debian 13 (Trixie) with a one-command installer; app on port 8080, live wall on port 8081, both behind a reverse proxy with Let's Encrypt.
- Stacked, overlaid or separate charts per channel, editor performance, followers and adjustable goals.
- Reports as interactive HTML and PDF, sent through Microsoft 365 (Graph) or your own SMTP server.
- Entra ID single sign-on and local accounts.
- Full and incremental backups to FTP, FTPS or SCP, with restore from the UI.
- Updates from the UI with a production (`main`) and test (`develop`) channel.
- English by default, fully translated to Dutch.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/rhisijmuiden/stats-collector/develop/install.sh -o install.sh
sudo bash install.sh
```

## Development

```bash
cd backend && uv venv && uv pip install -e '.[dev]' && pytest -q
cd frontend && npm ci && npm run dev   # proxies /api to 127.0.0.1:8080
```

## License

GPL-3.0, see [LICENSE](LICENSE).
