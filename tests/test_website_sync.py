"""Offline tests for website_sync.py and its use in the photo flow. servect.net is never contacted."""
import hashlib
import hmac
import json
import unittest
from datetime import datetime

try:  # sets fake env and imports bot
    from tests import test_photo_service as flow
except ImportError:  # run as: python -m unittest discover -s tests
    import test_photo_service as flow

import bot
import website_sync
from photo_service import PACIFIC


class Signing(unittest.TestCase):
    def test_signature_matches_what_the_website_checks(self):
        body = {"job_ids": ["2026000552"], "served_at": "2026-11-14T12:56:00-08:00", "recipient": "PAT EXAMPLE, INTAKE SPECIALIST", "location": "C T Corporation System"}
        headers, raw = website_sync.signed_request(body, "synthetic-bot-token", now=1794700000)
        self.assertEqual(headers["X-ServeCT-Timestamp"], "1794700000")
        self.assertEqual(headers["User-Agent"], "ServeCT-Dispatch/1.0 (Raspberry Pi)", "the site firewall blocks python-requests")
        expected = hmac.new(b"synthetic-bot-token", b"1794700000." + raw, hashlib.sha256).hexdigest()
        self.assertEqual(headers["X-ServeCT-Signature"], expected, "PHP: hash_hmac('sha256', ts . '.' . body, token)")
        self.assertEqual(json.loads(raw), body)

    def test_summary(self):
        self.assertIn("now shows Served for: #2026000552 (no email", website_sync.summary({"2026000552": "tracking page now shows Served", "2026000550": "not a website order"}))
        self.assertIn("already past Served", website_sync.summary({"2026000552": "already proof ready; service details added"}))
        self.assertEqual(website_sync.summary({"2026000550": "not a website order"}), "None of these are website orders, so no tracking page changed.")


class FlowReportsToWebsite(unittest.TestCase):
    def setUp(self):
        self.pst = flow.FakePst()
        bot.pst = self.pst
        bot.photo_pending.clear()
        self.calls = []
        self._real = website_sync.report_served

    def tearDown(self):
        website_sync.report_served = self._real

    def serve(self):
        msg = flow.FakeMessage(caption="JANE DOE, INTAKE SPECIALIST", document=flow.FakeMedia(flow.jpeg("2026:11:10 12:56:31")))
        flow.run(bot.handle_photo(flow.FakeUpdate(msg), None))
        flow.run(bot.handle_photo_button(flow.FakeUpdate(query=flow.FakeQuery("ok", msg)), None))
        return msg.replies[-1][0]

    def test_served_jobs_are_sent_with_time_and_name(self):
        def fake(jobs, served_at, recipient, location):
            self.calls.append((list(jobs), served_at, recipient, location))
            return {str(jobs[0]): "tracking page now shows Served"}
        website_sync.report_served = fake
        reply = self.serve()
        self.assertEqual(len(self.calls), 1)
        jobs, served_at, recipient, location = self.calls[0]
        self.assertEqual(sorted(jobs), [541, 546])
        self.assertEqual(served_at, datetime(2026, 11, 10, 12, 56, 31, tzinfo=PACIFIC))
        self.assertEqual((recipient, location), ("JANE DOE, INTAKE SPECIALIST", "C T Corporation System"))
        self.assertIn("Website tracking page now shows Served for: #541", reply)

    def test_website_trouble_never_hides_the_pst_result(self):
        def down(*a, **k):
            raise website_sync.WebsiteSyncError("could not reach servect.net (ConnectTimeout)")
        website_sync.report_served = down
        reply = self.serve()
        self.assertIn("Added \"JANE DOE, INTAKE SPECIALIST\"", reply)
        self.assertIn("Website tracking not updated: could not reach servect.net", reply)
        self.assertEqual(sorted(a[0] for a in self.pst.added), [541, 546], "PST was still updated")


if __name__ == "__main__":
    unittest.main()
