"""Photo + name service updates.

Nick takes a photo at the registered agent's office and sends it with the name of the
person served ("JANE DOE, INTAKE SPECIALIST"). The photo's own date/time is the time
of service. The bot finds the open jobs at that office and, after he confirms, adds
the comment the way he writes it in WebPST himself:

    text      "Jane Doe, Intake Specialist"   (exactly as typed)
    time      the moment of service
    flags     IsAttempt, IsStatusReport, IsReviewed

Pure helpers live here so they can be tested without Telegram or PST.
"""

import io
from datetime import datetime
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")

# EXIF tags
_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 36867
_OFFSET_TIME_ORIGINAL = 36881
_DATETIME = 306

DEFAULT_LOCATION = "ct corporation"


class NoRecipientError(ValueError):
    pass


def photo_taken_at(image_bytes):
    """When the photo was taken (Pacific time), from its EXIF data, or None.

    Telegram removes EXIF from photos sent the normal (compressed) way, so this only
    works for photos sent "as a file". iPhone HEIC files are supported.
    """
    try:
        from PIL import Image
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        with Image.open(io.BytesIO(image_bytes)) as image:
            exif = image.getexif()
            details = exif.get_ifd(_EXIF_IFD)
            raw = details.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
            offset = details.get(_OFFSET_TIME_ORIGINAL)
    except Exception:
        return None
    if not raw:
        return None
    try:
        taken = datetime.strptime(str(raw).strip().rstrip("\x00"), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if offset:
        try:
            aware = datetime.strptime(f"{taken:%Y-%m-%d %H:%M:%S}{str(offset).strip()}", "%Y-%m-%d %H:%M:%S%z")
            return aware.astimezone(PACIFIC)
        except ValueError:
            pass
    # No offset recorded: the phone's clock was local (Pacific) time.
    return taken.replace(tzinfo=PACIFIC)


def to_pacific(moment):
    """A Telegram message time (UTC) as Pacific time."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    return moment.astimezone(PACIFIC)


def parse_recipient(caption):
    """The comment text: the name and title exactly as typed, e.g. "JANE DOE, INTAKE SPECIALIST".

    An optional leading "served" or "served to" is dropped, and so is a trailing period.
    """
    text = " ".join((caption or "").split())
    lowered = text.lower()
    for prefix in ("served to ", "served "):
        if lowered.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.strip(" .")
    if not text or not any(ch.isalpha() for ch in text):
        raise NoRecipientError("Who did you serve? Send the name and title, e.g. JANE DOE, INTAKE SPECIALIST")
    return text


def pst_datetime(moment):
    """PST's date-time text, e.g. "11/6/2026 12:56 pm"."""
    hour = moment.hour % 12 or 12
    return f"{moment.month}/{moment.day}/{moment.year} {hour}:{moment.minute:02d} {'am' if moment.hour < 12 else 'pm'}"


def friendly_time(moment):
    """e.g. "Tue 11/10 12:56 PM"."""
    hour = moment.hour % 12 or 12
    return f"{moment:%a} {moment.month}/{moment.day} {hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def parse_pst_datetime(text):
    """PST's "11/7/2026  1:33 pm" (note the double space) as Pacific time, or None."""
    text = " ".join((text or "").split())
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M%p", "%m/%d/%Y"):
        try:
            return datetime.strptime(text.upper(), fmt).replace(tzinfo=PACIFIC)
        except ValueError:
            continue
    return None


def already_served(comments):
    """True if a job already has a service comment (an attempt comment) logged."""
    return any(c.get("IsAttempt") for c in comments or [])


def eligible_jobs(jobs, comments_by_job, served_at):
    """The open jobs this service can apply to.

    Leaves out jobs that already have a service/attempt comment (served earlier but
    not closed yet) and jobs PST received after the photo was taken.
    Returns (eligible, skipped) where skipped is a list of (job, reason).
    """
    eligible, skipped = [], []
    for job in jobs:
        number = job.get("JobNumber")
        if already_served(comments_by_job.get(number)):
            skipped.append((job, "already has a service comment"))
            continue
        received = parse_pst_datetime(job.get("ReceivedDateTime"))
        if received and served_at and received > served_at:
            skipped.append((job, "received after the photo was taken"))
            continue
        eligible.append(job)
    return eligible, skipped


def job_label(job):
    """Short label for a job button: number and party served."""
    name = job.get("ServeeLastFirstMiddle") or (job.get("PartyToBeServed") or {}).get("LastName") or ""
    full = job.get("ServeeFullNameAndAddress") or ""
    if not name and full:
        name = full.split(",")[0]
    return f"#{job.get('JobNumber')} {name}".strip()
