import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from locations import load_locations
from message_parser import ParseError, parse_message
from pst_client import PstApiError, PstClient

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ALLOWED_USER_ID = int(os.environ["TELEGRAM_ALLOWED_USER_ID"])
SERVER_SERIAL_NUMBER = int(os.environ["PST_SERVER_SERIAL_NUMBER"])

pst = PstClient(
    api_username=os.environ["PST_API_USERNAME"],
    api_password=os.environ["PST_API_PASSWORD"],
    dbs_code=os.environ["PST_DBS_CODE"],
)

# chat_id -> {"jobs": [...], "parsed": {...}}
pending_confirmations = {}


def _is_authorized(update: Update) -> bool:
    return bool(update.effective_user) and update.effective_user.id == ALLOWED_USER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "Ready. Send messages like:\n"
        "served 10 at CT Corporation, Glendale at 12:00 PM to John Doe, Intake Specialist"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await update.message.reply_text("Not authorized.")
        logger.warning("Unauthorized message from user id %s", update.effective_user.id if update.effective_user else "unknown")
        return

    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    if text.lower() in ("yes", "y", "confirm"):
        await _confirm_and_update(chat_id, update)
        return

    if text.lower() in ("no", "n", "cancel"):
        pending_confirmations.pop(chat_id, None)
        await update.message.reply_text("Cancelled. Nothing was updated.")
        return

    try:
        parsed = parse_message(text)
    except ParseError as exc:
        await update.message.reply_text(str(exc))
        return

    locations = load_locations()
    address = locations.get(parsed["firm"].strip().lower())
    if not address or address.startswith("REPLACE_WITH"):
        await update.message.reply_text(
            f"\"{parsed['firm']}\" isn't set up in locations.json yet.\n\n"
            "Open a real job in WebPST for this location, copy the exact Party to be "
            "Served street address, and add it to locations.json as:\n"
            f'  "{parsed["firm"].strip().lower()}": "<that address>"\n\n'
            "Nothing was updated."
        )
        return

    try:
        jobs = pst.search_jobs(
            ServerSerialNumber=SERVER_SERIAL_NUMBER,
            ServeeAddress1=address,
            ServeeCity=parsed["city"],
            SearchPurpose="UnfinishedJobs",
        )
    except PstApiError as exc:
        await update.message.reply_text(f"PST API error: {exc}")
        return
    except Exception:
        logger.exception("Unexpected error calling PST API")
        await update.message.reply_text("Unexpected error reaching PST. Nothing was updated.")
        return

    if len(jobs) != parsed["count"]:
        job_list = "\n".join(f"  #{j['JobNumber']}" for j in jobs) or "  (none)"
        await update.message.reply_text(
            f"You said {parsed['count']} job(s), but I found {len(jobs)} open, unfinished job(s) "
            f"with a Party to be Served address matching \"{address}\", {parsed['city']}:\n{job_list}\n\n"
            "Nothing was updated. Double check and resend, or handle this one in WebPST directly."
        )
        return

    pending_confirmations[chat_id] = {"jobs": jobs, "parsed": parsed}
    job_list = "\n".join(f"  #{j['JobNumber']} — {j.get('ServeeLastFirstMiddle', '')}" for j in jobs)
    await update.message.reply_text(
        f"Found {len(jobs)} job(s) at {parsed['firm']}, {parsed['city']}:\n{job_list}\n\n"
        f"Will add this comment to each job:\n"
        f"\"Served to {parsed['recipient']}, {parsed['title']} at {parsed['time']}.\"\n\n"
        "Reply YES to confirm or NO to cancel."
    )


async def _confirm_and_update(chat_id, update):
    pending = pending_confirmations.pop(chat_id, None)
    if not pending:
        await update.message.reply_text("Nothing waiting to confirm.")
        return

    parsed = pending["parsed"]
    comment_text = f"Served to {parsed['recipient']}, {parsed['title']} at {parsed['time']}."
    comment_datetime = datetime.now().strftime("%m/%d/%Y %I:%M%p")

    updated, failed = [], []
    for job in pending["jobs"]:
        job_number = job["JobNumber"]
        try:
            pst.add_comment(job_number, comment_text, comment_datetime)
            updated.append(job_number)
        except PstApiError as exc:
            failed.append((job_number, str(exc)))
        except Exception as exc:
            logger.exception("Unexpected error updating job %s", job_number)
            failed.append((job_number, "unexpected error"))

    lines = []
    if updated:
        lines.append("Updated: " + ", ".join(f"#{n}" for n in updated))
    if failed:
        lines.append("Failed: " + ", ".join(f"#{n} ({err})" for n, err in failed))
    await update.message.reply_text("\n".join(lines) if lines else "Nothing was updated.")


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot starting, polling for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
