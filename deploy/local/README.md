# Counter: install, update, restore

The step-by-step on-site list is in `docs/install-checklist.md`. This page covers how an installed counter is laid out, and what to do when something goes wrong.

| | Linux | Windows |
|---|---|---|
| Install | `sudo ./deploy/local/linux/install.sh --kiosk-user counter [--lan]` | `install.ps1 -KioskUser counter [-Lan]` (as administrator) |
| Running version | `/opt/faida/current` → `releases/<version>` | `C:\Faida\current` (junction) → `releases\<version>` |
| Settings (printers, cloud, email, secrets) | `/etc/faida/counter.env` | `C:\Faida\counter.env` |
| Pictures, backup status, logs | `/var/lib/faida` | `C:\Faida\data` |
| Backend service | `faida-counter.service` (systemd) | "Faida counter" scheduled task, at start-up |
| Full-screen screen | `~/.config/autostart/faida-kiosk.desktop` | "Faida kiosk" scheduled task, at sign-in |
| Nightly backup | `faida-backup.timer`, 04:30 → USB labelled FAIDABACKUP | "Faida backup" task, 04:30 → USB labelled FAIDABACKUP |
| Logs | `journalctl -u faida-counter` | `C:\Faida\data\logs\counter.log` |

The settings, the database and the pictures are never inside a release folder. An update or a rollback can't touch them.

## Updating (after closing hours only)

1. Build the release on the office machine: `deploy/make-release.sh`.
2. Copy it to the counter, for example over the remote-support tool.
3. Run the update:
   - Linux: `sudo /opt/faida/current/deploy/local/linux/update.sh faida-<version>.tar.gz`
   - Windows: `powershell -ExecutionPolicy Bypass -File C:\Faida\current\deploy\local\windows\update.ps1 -Archive faida-<version>.zip`

The update refuses to start while shifts or bills are open. Use `--force` / `-Force` only when you are sure nobody is selling. It then:

1. installs the new version beside the old one;
2. takes a backup;
3. stops Faida, switches to the new version, runs the database migrations, and starts it;
4. waits for the health check to answer with the new version.

If any step fails, it **rolls back by itself**. It undoes the migrations, or, if that fails, restores the backup it took a minute earlier. Then it starts the old version and checks it. The log is in the logs folder as `update-<date>.log`.

## Restoring a backup (new PC, failed disk, theft)

1. Install Faida on the new PC as usual (`docs/install-checklist.md`, steps 1–2). At "Business name", stop the installer with Ctrl+C. The database now exists but is empty.
2. Plug in the FAIDABACKUP drive. In the backend folder, with the settings file in use, run the restore. You need the **backup passphrase** from the sealed card.

   Linux:

   ```bash
   cd /opt/faida/current/backend
   sudo -u faida env FAIDA_ENV_FILE=/etc/faida/counter.env .venv/bin/python -m app.backup restore --file /mnt/faida-usb/faida/faida-local-<newest>.fbk
   ```

   Windows:

   ```powershell
   cd C:\Faida\current\backend; $env:FAIDA_ENV_FILE="C:\Faida\counter.env"
   .venv\Scripts\python -m app.backup restore --file E:\faida\faida-local-<newest>.fbk
   ```

3. The restore prints one line, `FAIDA_PIN_SECRET=...`. Put it in place of the line in the settings file, or staff PINs won't work.
4. Run the installer again so the services start, or restart the service.
5. Log in with the owner PIN, and check yesterday's closing.

Anything sold after the backup was taken, but not yet uploaded to the cloud, is lost. Ask the owner to re-enter the day from her paper records if needed.

## Common problems

| What you see | What to do |
|---|---|
| Screen shows "Can't reach the counter" | The backend stopped. Linux: `sudo systemctl restart faida-counter`, then check `journalctl -u faida-counter -n 50`. Windows: restart the PC, then check `counter.log` |
| Orange printer sign on tables | Printer off, out of paper, or the cable is loose. Fix it, then Owner area > Printers > Print again |
| Health alert "backup failed: drive not found" | The USB drive was unplugged or renamed. Plug it back in, check its name is FAIDABACKUP |
| Health alert "hasn't synced for 24 hours" | Check the internet at the bar. The counter keeps selling and catches up by itself |
| A new waiter's PIN is refused | It must be 4–6 digits, not 1234 or one digit repeated, and different from everyone else's |
