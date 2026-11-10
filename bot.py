import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from locations import load_locations
from message_parser import ParseError, parse_message
import photo_service
from pst_client import PstApiError, PstClient

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

ALLOWED_USER_ID = int(os.environ["TELEGRAM_ALLOWED_USER_ID"])
SERVER_SERIAL_NUMBER = int(os.environ["PST_SERVER_SERIAL_NUMBER"])

pst = PstClient(
    api_username=os.environ["PST_API_USERNAME"],
    api_password=os.environ["PST_API_PASSWORD"],
    dbs_code=os.environ["PST_DBS_CODE"],
)

# chat_id -> {"jobs": [...], "parsed": {...}}
pending_confirmations = {}

# chat_id -> photo service waiting for a name or a confirm:
# {"jobs": [...], "selected": set(job numbers), "skipped": [(job, reason)],
#  "served_at": datetime, "time_from_photo": bool, "recipient": str or None, "address": str}
photo_pending = {}


def _is_authorized(update: Update) -> bool:
    return bool(update.effective_user) and update.effective_user.id == ALLOWED_USER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "Ready.\n\n"
        "After serving at C T Corporation: send the photo you took there, with the name "
        "and title as the caption, e.g. JANE DOE, INTAKE SPECIALIST.\n"
        "Send the photo as a File (paperclip > File) so its own date and time are used; "
        "a normal photo loses them and the bot uses the time you sent it instead.\n\n"
        "The old text format still works too:\n"
        "served 10 at CT Corporation, Glendale at 12:00 PM to John Doe, Intake Specialist"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await update.message.reply_text("Not authorized.")
        logger.warning("Unauthorized message from user id %s", update.effective_user.id if update.effective_user else "unknown")
        return

    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    photo = photo_pending.get(chat_id)
    if photo is not None:
        if text.lower() in ("no", "n", "cancel"):
            photo_pending.pop(chat_id, None)
            await update.message.reply_text("Cancelled. Nothing was updated.")
            return
        if photo["recipient"] is None:
            try:
                photo["recipient"] = photo_service.parse_recipient(text)
            except photo_service.NoRecipientError as exc:
                await update.message.reply_text(str(exc))
                return
            await _show_photo_summary(chat_id, update.message.reply_text)
            return
        if text.lower() in ("yes", "y", "confirm"):
            await _apply_photo_service(chat_id, update.message.reply_text)
            return

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


# ---------------------------------------------------------------- photo + name

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A photo taken at the registered agent, captioned with who was served."""
    if not _is_authorized(update):
        await update.message.reply_text("Not authorized.")
        return
    chat_id = update.effective_chat.id
    message = update.message

    try:
        if message.document:
            file = await message.document.get_file()
        else:
            file = await message.photo[-1].get_file()
        image_bytes = bytes(await file.download_as_bytearray())
    except Exception:
        logger.exception("Could not download the photo")
        await message.reply_text("I couldn't download that photo. Try sending it again. Nothing was updated.")
        return

    sent_at = photo_service.to_pacific(message.date)
    taken_at = photo_service.photo_taken_at(image_bytes)
    served_at = taken_at or sent_at

    recipient = None
    if message.caption:
        try:
            recipient = photo_service.parse_recipient(message.caption)
        except photo_service.NoRecipientError:
            recipient = None

    address = load_locations().get(photo_service.DEFAULT_LOCATION)
    if not address:
        await message.reply_text("C T Corporation isn't set up in locations.json. Nothing was updated.")
        return

    try:
        jobs = photo_service.merge_jobs(*[
            pst.search_jobs(
                ServerSerialNumber=SERVER_SERIAL_NUMBER,
                ServeeAddress1=variant,
                SearchPurpose="UnfinishedJobs",
            )
            for variant in photo_service.address_variants(address)
        ])
        comments = {job["JobNumber"]: pst.get_comments(job["JobNumber"]) for job in jobs}
    except PstApiError as exc:
        await message.reply_text(f"PST API error: {exc}\nNothing was updated.")
        return
    except Exception:
        logger.exception("Unexpected error calling PST API")
        await message.reply_text("Unexpected error reaching PST. Nothing was updated.")
        return

    eligible, skipped = photo_service.eligible_jobs(jobs, comments, served_at)
    if not eligible:
        lines = [f"No open jobs at {address} are waiting for service. Nothing was updated."]
        lines += [f"  {photo_service.job_label(job)}: {reason}" for job, reason in skipped]
        await message.reply_text("\n".join(lines))
        return

    photo_pending[chat_id] = {
        "jobs": eligible,
        "selected": {job["JobNumber"] for job in eligible},
        "skipped": skipped,
        "served_at": served_at,
        "time_from_photo": taken_at is not None,
        "sent_at": sent_at,
        "recipient": recipient,
        "address": address,
    }
    if recipient is None:
        await message.reply_text("Got the photo. Who did you serve? Send the name and title, e.g. JANE DOE, INTAKE SPECIALIST")
        return
    await _show_photo_summary(chat_id, message.reply_text)


def _photo_summary(pending):
    served_at = pending["served_at"]
    if pending["time_from_photo"]:
        when = f"{photo_service.friendly_time(served_at)} (from the photo)"
        gap = abs((pending["sent_at"] - served_at).total_seconds())
        if gap > 6 * 3600:
            when += "\n\u26a0\ufe0f The photo was taken a while ago. Make sure it's the right one."
    else:
        when = (f"{photo_service.friendly_time(served_at)} (when you sent it; the photo had no date. "
                "Send it as a File next time to use the photo's own time)")
    count = len(pending["selected"])
    lines = [
        f"Served: {pending['recipient']}",
        f"Time: {when}",
        "",
        f"Which jobs should get this? Your open {pending['address']} jobs are all selected. "
        f"Tap a job to unselect it (tap again to put it back), then tap Submit. "
        f"{count} selected now.",
    ]
    if pending["skipped"]:
        lines.append("")
        lines.append("Not included:")
        lines += [f"  {photo_service.job_label(job)}: {reason}" for job, reason in pending["skipped"]]
    return "\n".join(lines)


def _photo_keyboard(pending):
    rows = []
    for job in pending["jobs"]:
        mark = "\u2705" if job["JobNumber"] in pending["selected"] else "\u2b1c"
        rows.append([InlineKeyboardButton(f"{mark} {photo_service.job_label(job)}"[:60], callback_data=f"t:{job['JobNumber']}")])
    count = len(pending["selected"])
    rows.append([
        InlineKeyboardButton(f"Submit ({count})", callback_data="ok"),
        InlineKeyboardButton("Cancel", callback_data="x"),
    ])
    return InlineKeyboardMarkup(rows)


async def _show_photo_summary(chat_id, reply):
    pending = photo_pending[chat_id]
    await reply(_photo_summary(pending), reply_markup=_photo_keyboard(pending))


async def handle_photo_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not _is_authorized(update):
        await query.answer("Not authorized.")
        return
    chat_id = update.effective_chat.id
    pending = photo_pending.get(chat_id)
    if pending is None or pending["recipient"] is None:
        await query.answer("This one is finished or expired. Send the photo again.")
        await query.edit_message_reply_markup(None)
        return
    data = query.data or ""
    if data == "x":
        photo_pending.pop(chat_id, None)
        await query.answer("Cancelled")
        await query.edit_message_text("Cancelled. Nothing was updated.")
        return
    if data == "ok":
        await query.answer("Updating PST...")
        await query.edit_message_reply_markup(None)
        await _apply_photo_service(chat_id, query.message.reply_text)
        return
    if data.startswith("t:"):
        number = int(data[2:])
        if number in pending["selected"]:
            pending["selected"].discard(number)
        else:
            pending["selected"].add(number)
        await query.answer()
        await query.edit_message_text(_photo_summary(pending), reply_markup=_photo_keyboard(pending))


async def _apply_photo_service(chat_id, reply):
    pending = photo_pending.pop(chat_id, None)
    if not pending or not pending["selected"]:
        await reply("No jobs selected. Nothing was updated.")
        return
    when = photo_service.pst_datetime(pending["served_at"])
    updated, failed = [], []
    for job in pending["jobs"]:
        number = job["JobNumber"]
        if number not in pending["selected"]:
            continue
        try:
            pst.add_comment(number, pending["recipient"], when, is_attempt=True, is_status_report=True)
            updated.append(number)
        except PstApiError as exc:
            failed.append((number, str(exc)))
        except Exception:
            logger.exception("Unexpected error updating job %s", number)
            failed.append((number, "unexpected error"))
    lines = []
    if updated:
        lines.append(f"Added \"{pending['recipient']}\" at {when} to: " + ", ".join(f"#{n}" for n in updated))
        lines.append("Close the job(s) and make the proof in WebPST when you're back at your computer.")
    if failed:
        lines.append("FAILED (not updated): " + ", ".join(f"#{n} ({err})" for n, err in failed))
    await reply("\n".join(lines) if lines else "Nothing was updated.")


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE | filters.Document.FileExtension("heic"), handle_photo))
    app.add_handler(CallbackQueryHandler(handle_photo_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot starting, polling for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
