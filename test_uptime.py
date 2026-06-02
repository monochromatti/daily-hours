import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import uptime


class WorkEventsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"XDG_STATE_HOME": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def read_log(self):
        path = Path(self.tmp.name) / "daily-hours" / "work-events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_status_defaults_off(self):
        self.assertEqual(uptime.current_state(), "off")

    def test_on_is_idempotent(self):
        ts = datetime(2026, 6, 2, 8, tzinfo=timezone.utc)
        self.assertTrue(uptime.set_work_state("on", "test", ts))
        self.assertFalse(uptime.set_work_state("on", "test", ts + timedelta(minutes=1)))
        events = self.read_log()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["state"], "on")
        self.assertEqual(events[0]["source"], "test")

    def test_off_is_idempotent(self):
        ts = datetime(2026, 6, 2, 8, tzinfo=timezone.utc)
        uptime.set_work_state("on", "test", ts)
        self.assertTrue(uptime.set_work_state("off", "test", ts + timedelta(hours=1)))
        self.assertFalse(uptime.set_work_state("off", "test", ts + timedelta(hours=2)))
        self.assertEqual([event["state"] for event in self.read_log()], ["on", "off"])

    def test_toggle(self):
        ts = datetime(2026, 6, 2, 8, tzinfo=timezone.utc)
        self.assertEqual(uptime.toggle_work_state("test", ts), "on")
        self.assertEqual(uptime.toggle_work_state("test", ts + timedelta(hours=1)), "off")
        self.assertEqual([event["state"] for event in self.read_log()], ["on", "off"])

    def test_open_interval_counts_until_now(self):
        events = [{"ts": "2026-06-02T08:00:00+00:00", "state": "on"}]
        sessions = uptime.events_to_sessions(
            events, datetime(2026, 6, 2, 10, tzinfo=timezone.utc)
        )
        self.assertEqual(
            sessions,
            [
                (
                    datetime(2026, 6, 2, 8, tzinfo=timezone.utc),
                    datetime(2026, 6, 2, 10, tzinfo=timezone.utc),
                )
            ],
        )

    def test_midnight_split(self):
        spans = uptime.calculate_daily_spans(
            [
                (
                    datetime(2026, 6, 2, 23, 30, tzinfo=timezone.utc),
                    datetime(2026, 6, 3, 0, 30, tzinfo=timezone.utc),
                )
            ]
        )
        self.assertEqual(spans[datetime(2026, 6, 2).date()], [(23.5, 24.0)])
        self.assertEqual(spans[datetime(2026, 6, 3).date()], [(0.0, 0.5)])


if __name__ == "__main__":
    unittest.main()
