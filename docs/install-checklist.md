# Faida install checklist (on site)

For the Avinaya technician installing a counter. It follows masterplan 7.1. Tick each box, and keep the signed copy with the client file.

Client: ____________________  Date: ____________  Technician: ____________________

## Before you go

- [ ] Release built on the office machine: `deploy/make-release.sh`. Copy `releases/faida-<version>.zip` (Windows) or `.tar.gz` (Linux) to a USB stick.
- [ ] Menu typed up as a JSON file, using `docs/sample-menu.json` as the pattern. It holds categories, items, sizes and prices, tables and sections, choices (mixers, sides), combos and happy hour. Recipes and stock items go in a second file if the owner wants stock from day one.
- [ ] On the cloud, the client's **business ID** isn't known yet. You will register the counter at step 7.
- [ ] Bring: a USB drive for backups (16 GB or more), a network cable, spare thermal paper.

## 1. Hardware (masterplan 5.3)

- [ ] The counter PC runs **Windows 10/11** or **Ubuntu 22.04/24.04**. If the client's machine is Android, set up a mini PC as the counter, and use `--lan` / `-Lan` at step 2.
- [ ] Touch screen is 1366×768 or larger, landscape.
- [ ] Counter printer is on USB with the cash drawer cable plugged into the printer. Kitchen printer is on the network with a fixed IP: ______________
- [ ] Printers are **thermal, ESC/POS** (Epson, Xprinter, Rongta and most others). Paper width: **80 mm** / **58 mm** (measure the roll). Bluetooth-only printers are not supported; use USB or network.
- [ ] The PC and the router are on the **UPS**.
- [ ] Disk encryption is on: **BitLocker** (Windows) or LUKS (Linux). Write the recovery key into the client file, not on the PC.

## 2. Install Faida

Windows: unzip the release, open PowerShell **as administrator** in that folder, then run:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\local\windows\install.ps1 -KioskUser counter
```

Linux: unpack the release, then run:

```bash
tar -xzf faida-<version>.tar.gz && cd faida-<version>
sudo ./deploy/local/linux/install.sh --kiosk-user counter
```

The installer asks for:

| Question | What to enter |
|---|---|
| PostgreSQL password (Windows) | The password you chose when PostgreSQL was installed |
| Counter printer | Windows: share the USB printer as `POS80`, then `device:\\localhost\POS80`. Linux: `device:/dev/usb/lp0` |
| Kitchen printer | `network:<its IP>`, for example `network:192.168.1.50` |
| Receipt paper width | `80` or `58`, the width of the paper roll in mm. If the two printers differ, fix one later in the settings file (`FAIDA_COUNTER_PAPER_MM`, `FAIDA_KITCHEN_PAPER_MM`) |
| Backup passphrase | A long phrase. **Write it on the client's sealed card and in Avinaya's password manager.** Without it no backup can ever be opened |
| Cloud URL and token | Leave empty for now; this is done at step 7 |
| Business name, owner's name, owner PIN | As on receipts. The owner types her own PIN |
| Menu file | The path to the JSON file |

- [ ] The installer finished with "Faida … is installed and running".
- [ ] Automatic sign-in is on for the counter account. Windows: `netplwiz`. Ubuntu: Settings > Users.
- [ ] Restart the PC. It comes back straight into the Faida PIN screen, full-screen, with no desktop showing.
- [ ] Windows: in Settings > System > Power, set the screen and sleep to **Never**. Turn off Windows Update restarts during opening hours (set Active hours).

## 3. Printers

- [ ] Order a **food** item and SEND. It prints in the **kitchen**.
- [ ] Order a **drink** and SEND. It prints at the **bar/counter**.
- [ ] Take a **cash** payment. The **drawer opens** and the receipt prints.
- [ ] On the receipt, no line runs off the paper, and the small "Powered by Faida POS" line at the bottom is readable. If lines wrap badly, the paper width setting is wrong.
- [ ] Unplug the kitchen printer and send a food item. The table shows the orange printer sign. Plug the printer back in and press Print again in Owner area > Printers.

## 4. Backups

- [ ] Rename the USB drive to **FAIDABACKUP**: Windows, right-click the drive > Rename; Linux, `sudo fatlabel /dev/sdX1 FAIDABACKUP` or use Disks.
- [ ] Run one backup now. Windows: `Start-ScheduledTask "Faida backup"`. Linux: `sudo systemctl start faida-backup`.
- [ ] A `faida-local-….fbk` file is on the drive, in the `faida` folder.
- [ ] The drive stays plugged in. The backup runs every night at 04:30, or when the PC next starts if it was off.

## 5. Business data (Owner area > Setup)

- [ ] **Menu & prices**: every item, size and price checked with the owner. Add pictures for the favourites: take photos of the bar's own drinks and plates, or load the sample pictures with `python -m app.cli load-images docs/sample-images` (they match items by name; credits are in that folder).
- [ ] **Choices & happy hour**: mixers, sides and "how cooked" are attached to the right items, and the happy hour times and days are correct.
- [ ] **Tables & sections**: the names match the floor (Indoor, Garden, VIP…).
- [ ] **Staff & PINs**: each person types their own PIN. Supervisors are set as supervisors.
- [ ] **Settings**: business-day end, tot size, M-Pesa till number, receipt thank-you line, the closing-report emails.
- [ ] **Credit customers** with their limits (Owner area > Credit).
- [ ] Email (optional): put the SMTP account in the settings file, then restart Faida. On Windows, restart the "Faida counter" task; on Linux, run `sudo systemctl restart faida-counter`. The settings file is `C:\Faida\counter.env` or `/etc/faida/counter.env`.

## 6. Opening stock

- [ ] Load stock items and recipes with `python -m app.cli load-stock stock.json`, or enter them in Owner area > Stock.
- [ ] Do a **stock take** with the owner: count every bottle and crate, and enter it.

## 7. Link to the cloud

- [ ] On the counter, get the business ID. Windows: `cd C:\Faida\current\backend; .venv\Scripts\python -m app.ops set-up`. Linux: `cd /opt/faida/current/backend && sudo -u faida env FAIDA_ENV_FILE=/etc/faida/counter.env .venv/bin/python -m app.ops set-up`.
- [ ] On the cloud, register the counter: `register-device --business-id <id>` (see `deploy/cloud/README.md`). Copy the token it prints.
- [ ] Put `FAIDA_CLOUD_URL=https://<domain>` and `FAIDA_CLOUD_TOKEN=<token>` into the counter's settings file, then restart Faida.
- [ ] Create the owner's phone login on the cloud: `create-owner --business-id <id> --email <hers>`. Add the key to her authenticator app.
- [ ] On her phone, open `https://<domain>`, log in, and add it to the home screen. Today's numbers show "Last updated" within a minute.
- [ ] Unplug the internet and sell one item. Plug it back in. Within a minute the phone shows the sale.

## 8. Training and handover

- [ ] Each waiter is trained with `docs/staff-guide.md` (15–30 minutes each) and has signed `docs/house-rules.md`.
- [ ] The owner is trained on the Owner area: closing, cash-up, stock, reports, Excel export, the audit log and the Setup pages.
- [ ] Soft launch: 2–3 days alongside her current method.
- [ ] Demo done, and `docs/handover-checklist.md` signed by the owner.

Technician signature: ____________________   Owner signature: ____________________
