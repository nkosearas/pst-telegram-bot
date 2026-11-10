"""Offline tests for the photo + name service flow. No Telegram or PST is contacted.

Run:  python -m unittest discover -s tests -v
"""
import asyncio
import io
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# bot.py reads these at import; fake values keep the real .env out of tests.
os.environ.update({
    "TELEGRAM_ALLOWED_USER_ID": "111",
    "PST_SERVER_SERIAL_NUMBER": "4",
    "PST_API_USERNAME": "fake",
    "PST_API_PASSWORD": "fake",
    "PST_DBS_CODE": "fake",
    "TELEGRAM_BOT_TOKEN": "fake",
})

from PIL import Image  # noqa: E402

import photo_service  # noqa: E402
from photo_service import PACIFIC  # noqa: E402


def jpeg(taken=None, offset=None):
    image = Image.new("RGB", (40, 30), "white")
    exif = Image.Exif()
    if taken:
        details = exif.get_ifd(0x8769)
        details[36867] = taken
        if offset:
            details[36881] = offset
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    return out.getvalue()


class PhotoTime(unittest.TestCase):
    def test_reads_time_taken(self):
        t = photo_service.photo_taken_at(jpeg("2026:11:10 12:56:31"))
        self.assertEqual((t.month, t.day, t.hour, t.minute), (11, 10, 12, 56))
        self.assertEqual(t.utcoffset().total_seconds(), -8 * 3600)  # PST in November

    def test_uses_recorded_offset(self):
        t = photo_service.photo_taken_at(jpeg("2026:11:10 15:56:00", "-05:00"))  # taken on Eastern time
        self.assertEqual((t.hour, t.minute), (12, 56))

    def test_no_metadata_gives_none(self):
        self.assertIsNone(photo_service.photo_taken_at(jpeg()))
        self.assertIsNone(photo_service.photo_taken_at(b"not an image"))

    def test_heic_from_iphone(self):
        try:
            import pillow_heif
        except ImportError:
            self.skipTest("pillow-heif not installed")
        pillow_heif.register_heif_opener()
        exif = Image.Exif()
        exif.get_ifd(0x8769)[36867] = "2026:11:10 09:05:00"
        out = io.BytesIO()
        Image.new("RGB", (40, 30), "white").save(out, "HEIF", exif=exif.tobytes())
        t = photo_service.photo_taken_at(out.getvalue())
        self.assertEqual((t.hour, t.minute), (9, 5))

    def test_message_time_to_pacific(self):
        t = photo_service.to_pacific(datetime(2026, 11, 10, 20, 56, tzinfo=timezone.utc))
        self.assertEqual((t.hour, t.minute), (12, 56))


class Recipient(unittest.TestCase):
    def test_exactly_as_typed(self):
        self.assertEqual(photo_service.parse_recipient("JANE DOE, INTAKE SPECIALIST"), "JANE DOE, INTAKE SPECIALIST")
        self.assertEqual(photo_service.parse_recipient("  Pat Example,   Intake Specialist. "), "Pat Example, Intake Specialist")
        self.assertEqual(photo_service.parse_recipient("served to Jane Doe, Intake Specialist"), "Jane Doe, Intake Specialist")
        self.assertEqual(photo_service.parse_recipient("Jane Doe"), "Jane Doe")

    def test_missing(self):
        for bad in ("", "   ", "...", None):
            with self.assertRaises(photo_service.NoRecipientError):
                photo_service.parse_recipient(bad)


class Formats(unittest.TestCase):
    def test_pst_datetime_matches_pst(self):
        self.assertEqual(photo_service.pst_datetime(datetime(2026, 11, 6, 12, 56, tzinfo=PACIFIC)), "11/6/2026 12:56 pm")
        self.assertEqual(photo_service.pst_datetime(datetime(2026, 11, 6, 9, 5, tzinfo=PACIFIC)), "11/6/2026 9:05 am")
        self.assertEqual(photo_service.pst_datetime(datetime(2026, 11, 6, 0, 1, tzinfo=PACIFIC)), "11/6/2026 12:01 am")

    def test_reads_pst_received_time(self):
        t = photo_service.parse_pst_datetime("11/7/2026  1:33 pm")
        self.assertEqual((t.day, t.hour, t.minute), (7, 13, 33))
        self.assertIsNone(photo_service.parse_pst_datetime(""))


SERVED = datetime(2026, 11, 10, 12, 56, tzinfo=PACIFIC)
JOBS = [
    {"JobNumber": 541, "ReceivedDateTime": "11/7/2026  1:33 pm", "ServeeFullNameAndAddress": "Acme Widgets, Inc., C T Corporation System, 330 N Brand Blvd"},
    {"JobNumber": 543, "ReceivedDateTime": "11/8/2026  9:00 am", "ServeeFullNameAndAddress": "Gamma Holdings, LLC, C T Corporation System"},
    {"JobNumber": 545, "ReceivedDateTime": "11/10/2026  2:10 pm", "ServeeFullNameAndAddress": "Late Order Inc., C T Corporation System"},
]
COMMENTS = {
    541: [{"CommentText": "Created by ServeCT website order #60", "IsAttempt": False}],
    543: [{"CommentText": "Sam Example, Intake Specialist", "IsAttempt": True}],
    545: [],
}


class Eligible(unittest.TestCase):
    def test_filters(self):
        eligible, skipped = photo_service.eligible_jobs(JOBS, COMMENTS, SERVED)
        self.assertEqual([j["JobNumber"] for j in eligible], [541])
        self.assertEqual({j["JobNumber"]: r for j, r in skipped}, {543: "already has a service comment", 545: "received after the photo was taken"})

    def test_label(self):
        self.assertEqual(photo_service.job_label(JOBS[0]), "#541 Acme Widgets")


# ---------------------------------------------------------------- whole chat flow, fakes only

import bot  # noqa: E402


class FakePst:
    def __init__(self):
        self.added = []
        self.searches = []

    def search_jobs(self, **params):
        self.searches.append(params)
        return [dict(j) for j in JOBS] + [{"JobNumber": 546, "ReceivedDateTime": "11/9/2026  8:00 am", "ServeeFullNameAndAddress": "Beta LLC, C T Corporation System"}]

    def get_comments(self, number):
        return COMMENTS.get(number, [])

    def add_comment(self, number, text, when, is_attempt=True, is_status_report=True):
        self.added.append((number, text, when, is_attempt, is_status_report))


class FakeFile:
    def __init__(self, data):
        self.data = data

    async def download_as_bytearray(self):
        return bytearray(self.data)


class FakeMedia:
    def __init__(self, data):
        self.data = data

    async def get_file(self):
        return FakeFile(self.data)


class FakeMessage:
    def __init__(self, text=None, caption=None, photo=None, document=None, date=None):
        self.text, self.caption, self.document = text, caption, document
        self.photo = [photo] if photo else []
        self.date = date or datetime(2026, 11, 10, 21, 0, tzinfo=timezone.utc)  # 1:00 pm Pacific
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append((text, reply_markup))


class FakeQuery:
    def __init__(self, data, message):
        self.data, self.message = data, message
        self.answers, self.edits = [], []

    async def answer(self, text=None):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))

    async def edit_message_reply_markup(self, markup=None):
        self.edits.append((None, markup))


class FakeUpdate:
    def __init__(self, message=None, query=None, user=111):
        self.message = message
        self.callback_query = query
        self.effective_user = type("U", (), {"id": user})()
        self.effective_chat = type("C", (), {"id": 5})()


def run(coro):
    return asyncio.run(coro)


def buttons(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


class ChatFlow(unittest.TestCase):
    def setUp(self):
        self.pst = FakePst()
        bot.pst = self.pst
        bot.photo_pending.clear()
        bot.pending_confirmations.clear()

    def test_photo_as_file_with_caption(self):
        msg = FakeMessage(caption="JANE DOE, INTAKE SPECIALIST", document=FakeMedia(jpeg("2026:11:10 12:56:31")))
        run(bot.handle_photo(FakeUpdate(msg), None))
        text, markup = msg.replies[-1]
        self.assertIn("Tue 11/10 12:56 PM (from the photo)", text)
        self.assertIn("Comment: JANE DOE, INTAKE SPECIALIST", text)
        self.assertIn("#543 Gamma Holdings: already has a service comment", text)
        self.assertIn("#545 Late Order Inc.: received after the photo was taken", text)
        self.assertEqual(buttons(markup), ["✅ #541 Acme Widgets", "✅ #546 Beta LLC", "Add to 2 job(s)", "Cancel"])
        self.assertEqual(self.pst.searches[0], {"ServerSerialNumber": 4, "ServeeAddress1": "C T Corporation System", "SearchPurpose": "UnfinishedJobs"})
        self.assertEqual(self.pst.added, [], "nothing written before confirming")

        # Leave #546 out, then confirm.
        q = FakeQuery("t:546", msg)
        run(bot.handle_photo_button(FakeUpdate(query=q), None))
        self.assertEqual(buttons(q.edits[-1][1])[1:3], ["⬜ #546 Beta LLC", "Add to 1 job(s)"])
        q = FakeQuery("ok", msg)
        run(bot.handle_photo_button(FakeUpdate(query=q), None))
        self.assertEqual(self.pst.added, [(541, "JANE DOE, INTAKE SPECIALIST", "11/10/2026 12:56 pm", True, True)])
        self.assertIn("to: #541", msg.replies[-1][0])
        self.assertNotIn(5, bot.photo_pending)

    def test_compressed_photo_uses_send_time_and_asks_for_name(self):
        msg = FakeMessage(photo=FakeMedia(jpeg()))  # Telegram stripped the metadata; no caption
        run(bot.handle_photo(FakeUpdate(msg), None))
        self.assertIn("Who did you serve?", msg.replies[-1][0])
        reply = FakeMessage(text="Pat Example, Intake Specialist")
        run(bot.handle_message(FakeUpdate(reply), None))
        text, markup = reply.replies[-1]
        self.assertIn("Tue 11/10 1:00 PM (when you sent it; the photo had no date", text)
        run(bot.handle_message(FakeUpdate(FakeMessage(text="yes")), None))
        self.assertEqual(sorted(a[0] for a in self.pst.added), [541, 546])
        self.assertTrue(all(a[2] == "11/10/2026 1:00 pm" for a in self.pst.added))

    def test_cancel_writes_nothing(self):
        msg = FakeMessage(caption="Jane Doe", document=FakeMedia(jpeg("2026:11:10 12:56:31")))
        run(bot.handle_photo(FakeUpdate(msg), None))
        q = FakeQuery("x", msg)
        run(bot.handle_photo_button(FakeUpdate(query=q), None))
        self.assertEqual(self.pst.added, [])
        self.assertIn("Cancelled", q.edits[-1][0])

    def test_old_photo_warns(self):
        msg = FakeMessage(caption="Jane Doe", document=FakeMedia(jpeg("2026:11:09 12:56:31")))
        run(bot.handle_photo(FakeUpdate(msg), None))
        self.assertIn("taken a while ago", msg.replies[-1][0])

    def test_stranger_is_refused(self):
        msg = FakeMessage(caption="Jane Doe", document=FakeMedia(jpeg("2026:11:10 12:56:31")))
        run(bot.handle_photo(FakeUpdate(msg, user=999), None))
        self.assertEqual(self.pst.searches, [])
        self.assertEqual(msg.replies[-1][0], "Not authorized.")

    def test_old_text_format_still_works(self):
        msg = FakeMessage(text="served 2 at CT Corporation, Glendale at 12:00 PM to John Doe, Intake Specialist")
        run(bot.handle_message(FakeUpdate(msg), None))
        self.assertIn("You said 2 job(s), but I found 4", msg.replies[-1][0])
        self.assertEqual(self.pst.added, [])


if __name__ == "__main__":
    unittest.main()
