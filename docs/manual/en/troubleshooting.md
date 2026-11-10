# Troubleshooting

## Logs

| What | Command |
| --- | --- |
| Web application | `journalctl -u stats-collector-web -f` |
| Updates, backups, restores | `journalctl -u stats-collector-ops -n 200`, or the log on the page while it runs |
| Logs of earlier tasks | `/var/lib/stats-collector/ops/job-<id>.log` |
| pgBackRest | `/var/log/pgbackrest/` |
| PostgreSQL | `journalctl -u postgresql@17-main` |

## Command line

```bash
stats-collector version             # installed version and channel
stats-collector setup-link          # one-time link for the first administrator
stats-collector reset-password EMAIL
stats-collector migrate             # apply database migrations
stats-collector ops run-pending     # run queued tasks now (root)
stats-collector backup full|incr    # make a backup now (root)
stats-collector restore --target ID --label LABEL   # restore from a remote location (root)
```

## Common problems

**The page does not load through the proxy.** Check `curl http://127.0.0.1:8080/api/health` on the server. If that works, check the proxy rule and that port 8080 is reachable from the proxy (firewall).

**I am logged out immediately after signing in.** The public URL starts with `https://` but the proxy sends plain HTTP to the browser, or the other way round. Make `SC_PUBLIC_URL` match the address in the browser.

**A task stays "Queued".** The ops runner is not running: `systemctl status stats-collector-ops.path`. Start it with `systemctl enable --now stats-collector-ops.path`. Queued tasks are also picked up by the hourly run (five past the hour); to start them right away, run `sudo stats-collector ops run-pending`.

**"GitHub cannot be reached".** The server needs outgoing HTTPS to `api.github.com` and `github.com` to check for and download updates.

**Backup test fails with "permission denied" on SFTP.** Check the username and key, and that the folder can be created by that user. For key login paste the complete private key including the `BEGIN` and `END` lines.

**The update failed.** The previous version and the database were restored automatically. The task log on the Info page shows the reason. Report it with that log.
