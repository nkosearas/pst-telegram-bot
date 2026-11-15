"""The people Nick can serve at C T Corporation, shown as buttons in the photo flow.

The list is C T Corporation System's "CA Registered Corporate (1505) Agent Authorized
Employee(s)" from the CA Secretary of State (bizfileonline.sos.ca.gov). It contains real
people's names, so it lives only on the Pi in ct_agents.json (gitignored), never in the repo:

    {"updated": "2026-11-14", "names": ["FIRST LAST", ...]}

ct_agents_usage.json counts how often each name was picked, so the people Nick serves
most often come first. A typed name always overrides the list.
"""
import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS_FILE = os.path.join(HERE, "ct_agents.json")
USAGE_FILE = os.path.join(HERE, "ct_agents_usage.json")
TITLE = "INTAKE SPECIALIST"
STALE_DAYS = 45


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def load(path=None):
    """{"updated": "YYYY-MM-DD" or "", "names": [...]}; empty when the file is missing."""
    data = _read(path or AGENTS_FILE, {})
    names = [" ".join(str(n).split()) for n in data.get("names", []) if str(n).strip()]
    seen, unique = set(), []
    for name in names:
        if name.upper() not in seen:
            seen.add(name.upper())
            unique.append(name)
    return {"updated": str(data.get("updated", "")), "names": unique}


def ordered(names, usage):
    """Most-picked first, then alphabetical."""
    return sorted(names, key=lambda n: (-int(usage.get(n.upper(), 0)), n.upper()))


def load_usage(path=None):
    data = _read(path or USAGE_FILE, {})
    return data if isinstance(data, dict) else {}


def record_pick(name, path=None):
    path = path or USAGE_FILE
    usage = load_usage(path)
    usage[name.upper()] = int(usage.get(name.upper(), 0)) + 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(usage, fh)
    os.replace(tmp, path)


def recipient_for(name):
    """The comment text for a picked name, the same shape Nick types: "JANE DOE, INTAKE SPECIALIST"."""
    return f"{name}, {TITLE}"


def age_note(updated, today=None):
    """A warning line when the list is old or undated, else ''."""
    today = today or date.today()
    try:
        then = date.fromisoformat(updated)
    except ValueError:
        return "The name list has no date. Ask Claude to refresh it from bizfile."
    days = (today - then).days
    if days > STALE_DAYS:
        return f"The name list is from {then:%b} {then.day}, {then.year} ({days} days old). Ask Claude to refresh it from bizfile."
    return ""
