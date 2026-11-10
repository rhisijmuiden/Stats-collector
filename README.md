# Stats Collector

Self-hosted statistics and reporting platform for media teams. It collects reach, engagement and audience numbers from WordPress, Facebook, Instagram, YouTube, Owncast and Icecast, combines them in one dashboard, and emails branded reports on demand or on a schedule.

> Status: design phase. No application code yet.

- System design and roadmap: [docs/DESIGN.md](docs/DESIGN.md)
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

## License

GPL-3.0, see [LICENSE](LICENSE).
