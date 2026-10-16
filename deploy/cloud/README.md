# The Faida cloud

There is one shared server for all Faida clients (masterplan 7.2). It runs the backend in cloud mode, PostgreSQL and the owner's phone view. Every record carries its business ID, so each owner sees only her own business.

## First set-up (once)

1. Rent a small Ubuntu 24.04 server: 1–2 GB RAM, about USD 8–15 a month.
2. Point the domain's DNS **A record** at it, for example `faida.co.ke`.
3. Copy a release to the server, unpack it, and run:

   ```bash
   sudo ./deploy/cloud/setup.sh faida.co.ke admin@avinaya.co.ke
   ```

   It installs PostgreSQL, nginx and a TLS certificate, opens the firewall for SSH and HTTPS only, and starts three services:

   - `faida-cloud`: the app, on 127.0.0.1:8100 behind nginx;
   - `faida-cloud-backup.timer`: encrypted backup to `/var/backups/faida` every day at 02:15;
   - `faida-health.timer`: an hourly check for counters that stopped syncing for 24 hours, or whose backup failed. It posts to `FAIDA_ALERT_WEBHOOK`.

4. Copy the backups off the server: `sudo apt install rclone && sudo -u faida rclone config`. Make a remote called `offsite` (for example Backblaze B2 or Google Drive). The backup service then copies new files there every day.

## Adding a client

Run these on the server:

```bash
cd /opt/faida/current/backend
alias faida='sudo -u faida env FAIDA_ENV_FILE=/etc/faida/cloud.env .venv/bin/python'

# 1. The counter's business ID: on the counter, `python -m app.ops set-up`
faida -m app.cli register-device --business-id <id> --name "Counter"
#    -> FAIDA_CLOUD_TOKEN=...  (into the counter's settings file, with FAIDA_CLOUD_URL=https://faida.co.ke)

# 2. The owner's phone login (asks for a password; prints the authenticator key)
faida -m app.cli create-owner --business-id <id> --email owner@example.com
```

## Updating

Run this at night, when bars are closed:

```bash
sudo /opt/faida/current/deploy/cloud/update.sh faida-<version>.tar.gz
```

It works like the counter update: backup, switch, migrate, health check, and roll back by itself on failure. The cloud accepts uploads from the current and the previous minor version. Counters can therefore be updated after the cloud, one at a time.

## Checking on it

- App log: `journalctl -u faida-cloud -f`
- Health of every counter: `curl -H "X-Admin-Token: <FAIDA_ADMIN_TOKEN>" https://faida.co.ke/api/admin/health`. The token is in `/etc/faida/cloud.env`.
- Run the alert check now: `sudo systemctl start faida-health && journalctl -u faida-health -n 20`
- Restore a cloud backup: `faida -m app.backup restore --file /var/backups/faida/faida-cloud-<date>.fbk`. This replaces the database, so stop `faida-cloud` first.
