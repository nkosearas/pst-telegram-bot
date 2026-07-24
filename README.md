# PST Telegram Bot

Text a Telegram bot from your phone after serving papers, and it updates the matching
job(s) in WebPST (via the PST Customer API) with a comment — after you confirm.

This is a live-environment integration (real PST data, real billing per job touched),
so v1 is deliberately conservative:
- It matches jobs to your own Server Serial Number that are still open
  ("UnfinishedJobs"), using the **Party to be Served street address** (not the firm
  name) — see "Locations" below for why.
- If the number of matched jobs doesn't equal the count you texted, it updates nothing
  and shows you what it found instead, so you can double check.
- It always asks for a YES/NO confirmation before writing anything to PST.
- It only adds a Comment to each job (visible to your office in WebPST) — it does not
  change the job's formal "done"/served status. Once you trust the matching, that can
  be added as a next step.

## Message format

```
served <count> at <firm>, <city> at <time> to <recipient name>, <recipient title>
```

Example:

```
served 10 at CT Corporation, Glendale at 12:00 PM to John Doe, Intake Specialist
```

Reply `yes` to confirm the update, or `no` to cancel.

## Locations

Places like CT Corporation are registered agents — the *defendant name on each job
differs*, but you always physically serve papers at the same office address. So
matching by firm name doesn't work; the bot instead looks up the location name you
type (e.g. "CT Corporation") in `locations.json` to get the real street address, then
searches PST jobs by that address (`ServeeAddress1`) instead.

`locations.json` looks like:

```json
{
  "ct corporation": "818 West Seventh Street"
}
```

To add a location:
1. Open a real, existing job in WebPST for that address.
2. Copy the exact **Party to be Served** street address as PST has it stored.
3. Add an entry to `locations.json`: the lowercase name you'll type in messages, mapped
   to that address.

If you text a location name that isn't in `locations.json` yet, the bot will tell you
instead of guessing.

## Setup

1. **Install Python 3.10+** if you don't have it.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. **Create a Telegram bot:**
   - Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`, follow
     the prompts. It gives you a bot token — save it.
4. **Get your Telegram numeric user ID:**
   - Message [@userinfobot](https://t.me/userinfobot) — it replies with your ID.
   - This restricts the bot so only you can use it.
5. **Find your PST Server Serial Number:**
   - In WebPST, look up your own Server/Entity record — the serial number is shown
     there. (If you can't find it, DBS support can confirm it.)
6. Copy `.env.example` to `.env` and fill in all values:
   - `TELEGRAM_BOT_TOKEN` — from BotFather
   - `TELEGRAM_ALLOWED_USER_ID` — from userinfobot
   - `PST_API_USERNAME` / `PST_API_PASSWORD` / `PST_DBS_CODE` — from DBS
   - `PST_SERVER_SERIAL_NUMBER` — your own server record's serial number
7. Run it:
   ```
   python bot.py
   ```
   Leave this running (in a terminal window, or set up as a scheduled task) while
   you're out serving papers — the bot only works while this process is running on
   this machine.
8. Open your bot in Telegram and send `/start`, then try a real message.

## Deploying on a Raspberry Pi (recommended for real use)

Running this on your PC only works while your PC happens to be on. A Raspberry Pi
left running at home/office is a better fit — it stays reachable, and `systemd` can
keep the bot alive automatically (restarting it on crash or reboot).

1. SSH into the Pi, then clone the repo:
   ```
   git clone https://github.com/nkosearas/pst-telegram-bot.git
   cd pst-telegram-bot
   ```
2. Create a virtual environment and install dependencies (Raspberry Pi OS blocks
   installing packages system-wide by default, so a venv is required):
   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Create `.env` on the Pi (copy `.env.example`, fill in real values). This file is
   git-ignored and never leaves the Pi.
4. Install the systemd service:
   ```
   sudo cp deploy/pst-telegram-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now pst-telegram-bot
   ```
   The service file assumes the repo lives at `/home/pi/pst-telegram-bot` and runs as
   user `pi` — edit `deploy/pst-telegram-bot.service` first if your username or path
   differs, then re-copy it and run `sudo systemctl daemon-reload`.
5. Check it's running / view logs:
   ```
   sudo systemctl status pst-telegram-bot
   journalctl -u pst-telegram-bot -f
   ```
6. After pulling code updates (`git pull`), restart the service:
   ```
   sudo systemctl restart pst-telegram-bot
   ```

## Cost note

Per DBS's pricing, each job is billed once per month it's touched by the API
(currently $20/mo covers your first 200 jobs, then $0.10/job after that) — repeated
comments/updates to the same job in the same month don't add extra cost.

## Known limitations / ideas for later

- Only handles "served" messages — no support yet for attempts, non-serves, or
  address corrections.
- Firm/city matching is a simple text search against PST fields — unusual spacing or
  abbreviations in `firm`/`city` could cause a mismatch (the bot will tell you if the
  count doesn't line up rather than guessing).
- No formal "mark as served" status update yet — just a comment.
- Runs on your PC only; if this machine is off, texts won't be processed until it's
  back on and `bot.py` is running again.
