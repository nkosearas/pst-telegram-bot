# PST Telegram Bot

Text a Telegram bot from your phone after serving papers, and it updates the matching
job(s) in WebPST (via the PST Customer API) with a comment — after you confirm.

This is a live-environment integration (real PST data, real billing per job touched),
so v1 is deliberately conservative:
- It only matches jobs to your own Server Serial Number, by firm name + city, that are
  still open ("UnfinishedJobs").
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
