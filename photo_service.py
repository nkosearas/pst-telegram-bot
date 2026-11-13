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


def address_variants(address):
    """The CT address as typed both ways in PST: "C T Corporation System" and "CT Corporation System"."""
    variants = [address]
    squeezed = address.replace("C T ", "CT ", 1)
    if squeezed != address:
        variants.append(squeezed)
    spaced = address.replace("CT ", "C T ", 1)
    if spaced != address and spaced not in variants:
        variants.append(spaced)
    return variants


def merge_jobs(*job_lists):
    """One list, each job once, in job-number order."""
    seen = {}
    for jobs in job_lists:
        for job in jobs:
            seen.setdefault(job.get("JobNumber"), job)
    return [seen[k] for k in sorted(seen, key=lambda n: n or 0)]


# ---------------------------------------------------------------- served person entry
#
# Copied from the entry Nick made by hand in WebPST (+ ADD ANOTHER) on a C T Corporation
# job: a Natural Person, "Intake Specialist", at C T's Glendale office, marked as the
# actual service, Served, with the service date/time and type CORPORATE - REGISTERED
# AGENT. The Party to be Served (the company) is set to Ignore.

INTAKE_RELATIONSHIP = "Intake Specialist"
TYPE_SERVICE_CORPORATE_REGISTERED_AGENT = 9   # "CORPORATE - REGISTERED AGENT" in Nick's PST
CT_OFFICE = {
    "AddressType": "Work",
    "Address1": "C T Corporation System",
    "Address2": "330 N Brand Blvd",
    "City": "Glendale",
    "State": "CA",
    "Zip": "91203",
    "County": "Los Angeles",
}


def split_name(recipient):
    """("Pat", "Q Example") from "PAT Q EXAMPLE, INTAKE SPECIALIST".

    The name is everything before the first comma; the first word is the first name and
    the rest is the last name. ALL CAPS (or all lower case) names become Title Case, the
    way Nick types them in WebPST; mixed-case names are kept exactly as typed.
    """
    name = " ".join((recipient or "").split(",")[0].split())
    if name and (name.isupper() or name.islower()):
        name = " ".join(_title_word(word) for word in name.split())
    words = name.split(" ", 1) if name else []
    if not words:
        return "", ""
    return words[0], (words[1] if len(words) > 1 else "")


def _title_word(word):
    # "o'brien" -> "O'Brien", "mary-jo" -> "Mary-Jo"
    out, upper_next = [], True
    for ch in word.lower():
        out.append(ch.upper() if upper_next else ch)
        upper_next = ch in "-'"
    return "".join(out)


def served_person(first_name, last_name, served_datetime):
    """The new servee entry for the person served (CreateServeeDetailModel)."""
    entry = {
        "IsActualService": True,
        "IsRepresentativeToBeServed": False,
        "PartyType": "NaturalPerson",
        "FirstName": first_name,
        "LastName": last_name,
        "Relationship": INTAKE_RELATIONSHIP,
        "ServeeStatus": "Served",
        "ServiceDetails": {
            "ServedDateTime": served_datetime,
            "TypeServiceSerialNumber": TYPE_SERVICE_CORPORATE_REGISTERED_AGENT,
        },
    }
    entry.update(CT_OFFICE)
    return entry


def has_actual_service(servees):
    """True if a job already has a servee marked as the actual service."""
    return any(s.get("IsActualService") for s in servees or [])


def party_to_be_served(servees):
    for s in servees or []:
        if s.get("IsPartyToBeServed"):
            return s
    return None


_PARTY_FIELDS = ("PartyType", "Prefix", "FirstName", "LastName", "Suffix", "AddressType", "Address1",
                 "Address2", "City", "State", "Zip", "Relationship", "County",
                 "IsRepresentativeToBeServed", "IsActualService")


def _party_type_enum(value):
    return (value or "").replace(" ", "") or "NotSpecified"


def service_update_body(job_number, comment_text, served_datetime, recipient, servees):
    """One PUT for a job: the comment, plus (unless the job already has one) the served
    person with the service details, and the Party to be Served set to Ignore.

    Returns (body, added_person). The Party to be Served is sent back with all of its
    existing fields so nothing on it is blanked; only its status changes.
    """
    from pst_client import PstClient
    body = PstClient.comment_body(job_number, comment_text, served_datetime)
    if has_actual_service(servees):
        return body, False
    first, last = split_name(recipient)
    if not first:
        return body, False
    job = body["Job"]
    job["CreateServeeDetails"] = [served_person(first, last, served_datetime)]
    party = party_to_be_served(servees)
    if party and party.get("ID") and party.get("ServeeStatus") != "Ignore":
        update = {"ID": party["ID"], "ServeeStatus": "Ignore"}
        update.update({k: party[k] for k in _PARTY_FIELDS if k in party and party[k] is not None})
        update["PartyType"] = _party_type_enum(party.get("PartyType"))
        job["PartyToBeServed"] = update
    return body, True


def job_label(job):
    """Short label for a job button: number and party served."""
    name = job.get("ServeeLastFirstMiddle") or (job.get("PartyToBeServed") or {}).get("LastName") or ""
    full = job.get("ServeeFullNameAndAddress") or ""
    if not name and full:
        name = full.split(",")[0]
    return f"#{job.get('JobNumber')} {name}".strip()
