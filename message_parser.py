import re

MESSAGE_PATTERN = re.compile(
    r"^served\s+(?P<count>\d+)\s+at\s+(?P<firm>[^,]+),\s*(?P<city>[^,]+)\s+at\s+"
    r"(?P<time>\d{1,2}:\d{2}\s*[APMapm]{2})\s+to\s+(?P<recipient>[^,]+),\s*(?P<title>.+)$"
)

USAGE = (
    "Couldn't understand that. Use the format:\n"
    "served <count> at <firm>, <city> at <time> to <recipient name>, <recipient title>\n\n"
    "Example:\n"
    "served 10 at CT Corporation, Glendale at 12:00 PM to John Doe, Intake Specialist"
)


class ParseError(Exception):
    pass


def parse_message(text):
    match = MESSAGE_PATTERN.match(text.strip())
    if not match:
        raise ParseError(USAGE)
    return {
        "count": int(match.group("count")),
        "firm": match.group("firm").strip(),
        "city": match.group("city").strip(),
        "time": match.group("time").strip(),
        "recipient": match.group("recipient").strip(),
        "title": match.group("title").strip(),
    }
