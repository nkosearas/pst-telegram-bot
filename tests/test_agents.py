"""Offline tests for agents.py. Synthetic names only: never put real C T staff names here."""
import json
import os
import tempfile
import unittest
from datetime import date

import agents


class Agents(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.list_path = os.path.join(self.dir, "ct_agents.json")
        self.usage_path = os.path.join(self.dir, "ct_agents_usage.json")

    def write_list(self, data):
        with open(self.list_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_missing_file_is_empty(self):
        self.assertEqual(agents.load(self.list_path), {"updated": "", "names": []})

    def test_load_cleans_spaces_and_duplicates(self):
        self.write_list({"updated": "2026-11-14", "names": ["PAT  EXAMPLE", "pat example", " ", "LEE SAMPLE-TEST"]})
        self.assertEqual(agents.load(self.list_path)["names"], ["PAT EXAMPLE", "LEE SAMPLE-TEST"])

    def test_most_picked_first_then_alphabetical(self):
        names = ["ZED ONE", "AMY TWO", "MAX THREE"]
        agents.record_pick("MAX THREE", self.usage_path)
        agents.record_pick("MAX THREE", self.usage_path)
        agents.record_pick("Zed One", self.usage_path)
        usage = agents.load_usage(self.usage_path)
        self.assertEqual(usage, {"MAX THREE": 2, "ZED ONE": 1})
        self.assertEqual(agents.ordered(names, usage), ["MAX THREE", "ZED ONE", "AMY TWO"])

    def test_recipient_matches_typed_format(self):
        self.assertEqual(agents.recipient_for("PAT EXAMPLE"), "PAT EXAMPLE, INTAKE SPECIALIST")

    def test_age_note(self):
        self.assertEqual(agents.age_note("2026-11-14", date(2026, 12, 1)), "")
        self.assertIn("(47 days old)", agents.age_note("2026-10-15", date(2026, 12, 1)))
        self.assertIn("Oct 15, 2026", agents.age_note("2026-10-15", date(2026, 12, 1)))
        self.assertIn("no date", agents.age_note("", date(2026, 12, 1)))


if __name__ == "__main__":
    unittest.main()
