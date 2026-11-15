"""Tell servect.net which jobs were just served, so each website order's private tracking
page shows "Served" with the time and who accepted the papers (no email to the client).

The website checks an HMAC-SHA256 signature made with the Dispatch bot token, which both
sides already have (TELEGRAM_BOT_TOKEN here, SERVECT_TELEGRAM_BOT_TOKEN in wp-config.php).
Job numbers that aren't website orders are reported back and left alone.

This never blocks or undoes a PST update: if the website can't be reached, Dispatch just
says so, and Nick can set the status in ServeCT Orders by hand.
"""
import hashlib
import hmac
import json
import os
import time

import requests

SITE = os.environ.get("SERVECT_SITE_URL", "https://servect.net").rstrip("/")
PATH = "/wp-json/servect/v1/dispatch-served"
TIMEOUT = 20


def signed_request(body, token, now=None):
    """(headers, body bytes) for the website. Pure, for tests."""
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    ts = str(int(now if now is not None else time.time()))
    sig = hmac.new(token.encode("utf-8"), ts.encode("ascii") + b"." + raw, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-ServeCT-Timestamp": ts, "X-ServeCT-Signature": sig}, raw


def report_served(job_numbers, served_at, recipient, location, token=None):
    """Returns {job number: what the website did} or raises WebsiteSyncError."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise WebsiteSyncError("no bot token")
    body = {
        "job_ids": [str(n) for n in job_numbers],
        "served_at": served_at.isoformat(timespec="seconds"),
        "recipient": recipient or "",
        "location": location or "",
    }
    headers, raw = signed_request(body, token)
    try:
        response = requests.post(SITE + PATH, data=raw, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise WebsiteSyncError(f"could not reach servect.net ({type(exc).__name__})") from exc
    if response.status_code in (401, 403):
        raise WebsiteSyncError("servect.net refused the update (website plugin 1.7.0 or newer needed, with Telegram alerts on)")
    try:
        data = response.json()
    except ValueError:
        data = None
    if not response.ok or not isinstance(data, dict) or not isinstance(data.get("results"), dict):
        raise WebsiteSyncError(f"servect.net answered HTTP {response.status_code}")
    return data["results"]


def summary(results):
    """One or two lines for Dispatch's reply."""
    shown = [n for n, r in results.items() if r.startswith("tracking page")]
    already = [n for n, r in results.items() if r.startswith("already")]
    lines = []
    if shown:
        lines.append("Website tracking page now shows Served for: " + ", ".join(f"#{n}" for n in shown) + " (no email sent to the client).")
    if already:
        lines.append("Website orders already past Served (details added): " + ", ".join(f"#{n}" for n in already) + ".")
    if not lines:
        lines.append("None of these are website orders, so no tracking page changed.")
    return "\n".join(lines)


class WebsiteSyncError(Exception):
    pass
