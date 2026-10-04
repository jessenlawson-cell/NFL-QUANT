"""Offline capture tests: actual worker with an in-memory provider transport."""

import importlib.util
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "market_capture", Path(__file__).parents[2] / "scripts/capture_market_intelligence.py"
)


class MarketCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assertTrue(SPEC.origin and Path(SPEC.origin).exists(), "capture worker missing")
        self.m = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(self.m)
        self.now = datetime(2026, 10, 4, 16, 0, tzinfo=UTC)
        self.store = self.m.open_ledger(self.root)
        self.addCleanup(self.store.close)

    def test_weekly_and_provider_reserve_block_before_call(self):
        with self.assertRaises(self.m.BudgetError):
            self.m.reserve(self.store, "a", "2026-09-29", 4, 83, self.now)
        for i in range(21):
            self.m.reserve(self.store, str(i), "2026-09-29", 4, 498, self.now)
            self.store.execute("UPDATE calls SET status='COMPLETE' WHERE slot=?", (str(i),))
            self.store.commit()
        with self.assertRaises(self.m.BudgetError):
            self.m.reserve(self.store, "overflow", "2026-09-29", 1, 498, self.now)

    def test_duplicate_and_uncertain_calls_never_retry(self):
        self.m.reserve(self.store, "a", "2026-09-29", 4, 498, self.now)
        self.assertFalse(self.m.reserve(self.store, "a", "2026-09-29", 4, 498, self.now))
        with self.assertRaises(self.m.BudgetError):
            self.m.reserve(self.store, "b", "2026-09-29", 4, 498, self.now)

    def test_due_calls_are_pregame_and_only_once(self):
        event = {"id": "event1", "commence_time": "2026-10-04T17:00:00Z"}
        jobs = self.m.plan([event], self.now, [], None)
        self.assertEqual(
            [(j["kind"], len(j["markets"])) for j in jobs], [("board", 3), ("props", 12)]
        )
        self.assertEqual(self.m.plan([event], self.now + timedelta(hours=1), [], None), [])
        self.assertEqual(self.m.plan([event], self.now, [j["slot"] for j in jobs], None), [])

    def test_provider_reset_is_observed_not_calendar_assumed(self):
        self.m.observe_quota(self.store, {"x-requests-used": "420", "x-requests-remaining": "80"})
        self.m.observe_quota(self.store, {"x-requests-used": "0", "x-requests-remaining": "500"})
        self.assertEqual(
            self.store.execute("SELECT value FROM metadata WHERE key='cycle'").fetchone()[0], "1"
        )
        with self.assertRaises(self.m.BudgetError):
            self.m.observe_quota(self.store, {})

    def test_capture_preserves_raw_player_identity_and_is_idempotent(self):
        payload = {
            "id": "event1",
            "commence_time": "2026-10-04T17:00:00Z",
            "home_team": "A",
            "away_team": "B",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_pass_yds",
                            "last_update": "2026-10-04T15:59:00Z",
                            "outcomes": [
                                {
                                    "name": "Over",
                                    "description": "Raw Player",
                                    "point": 200.5,
                                    "price": 1.9,
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        def fetch(path, params, key):
            return json.dumps(payload).encode(), {
                "x-requests-last": "1",
                "x-requests-used": "3",
                "x-requests-remaining": "497",
            }

        job = {
            "slot": "2026-09-29:props:event1",
            "kind": "props",
            "event_id": "event1",
            "markets": ["player_pass_yds"],
        }
        result = self.m.capture(self.root, self.store, job, "secret", 498, self.now, fetch)
        self.assertEqual(result["quotes"][0]["player_gsis_id"], None)
        self.assertEqual(result["quotes"][0]["provider_description"], "Raw Player")
        self.assertTrue((self.root / result["raw_path"]).exists())
        self.assertIsNone(
            self.m.capture(self.root, self.store, job, "secret", 497, self.now, fetch)
        )

    def test_failure_is_secret_safe_and_blocks_other_charged_requests(self):
        def fetch(path, params, key):
            raise RuntimeError("https://example/?apiKey=secret")

        job = {
            "slot": "2026-09-29:props:event1",
            "kind": "props",
            "event_id": "event1",
            "markets": ["player_pass_yds"],
        }
        with self.assertRaisesRegex(self.m.BudgetError, "reconciliation"):
            self.m.capture(self.root, self.store, job, "secret", 498, self.now, fetch)
        self.assertNotIn("secret", str(list(self.store.execute("SELECT * FROM calls"))))

    def test_concurrent_connection_cannot_reserve_second_paid_request(self):
        other = self.m.open_ledger(self.root)
        self.addCleanup(other.close)
        self.m.reserve(self.store, "a", "2026-09-29", 4, 498, self.now)
        with self.assertRaises(self.m.BudgetError):
            self.m.reserve(other, "b", "2026-09-29", 4, 498, self.now)

    def test_bad_timestamp_is_raw_saved_and_fail_closed(self):
        payload = {
            "id": "event1",
            "home_team": "A",
            "away_team": "B",
            "commence_time": "2026-10-04T17:00:00Z",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_pass_yds",
                            "last_update": "2026-10-04T16:01:00Z",
                            "outcomes": [],
                        }
                    ],
                }
            ],
        }

        def fetch(path, params, key):
            return json.dumps(payload).encode(), {
                "x-requests-last": "1",
                "x-requests-used": "3",
                "x-requests-remaining": "497",
            }

        job = {
            "slot": "2026-09-29:props:event1",
            "kind": "props",
            "event_id": "event1",
            "markets": ["player_pass_yds"],
        }
        with self.assertRaises(self.m.BudgetError):
            self.m.capture(self.root, self.store, job, "secret", 498, self.now, fetch)
        row = self.store.execute("SELECT raw_path,status FROM calls").fetchone()
        self.assertTrue((self.root / row[0]).exists())
        self.assertEqual(row[1], "RECONCILIATION_REQUIRED")

    def test_deep_capture_cannot_move_to_second_game(self):
        events = [
            {"id": "event1", "commence_time": "2026-10-04T17:00:00Z"},
            {"id": "event2", "commence_time": "2026-10-04T17:00:00Z"},
        ]
        jobs = self.m.plan(events, self.now, ["2026-09-29:deep"], None)
        self.assertEqual([len(j["markets"]) for j in jobs if j["kind"] == "props"], [4, 4])

    def test_weekly_handoff_is_immutable_and_reports_missing_games(self):
        event = {"id": "event1", "commence_time": "2026-10-04T17:00:00Z"}
        output = self.m.export_handoff(self.root, self.store, [event], self.now)
        packet = json.loads(output.read_bytes())
        self.assertEqual(packet["uncaptured_event_ids"], ["event1"])
        self.assertEqual(packet["snapshots"], [])
        self.assertTrue(packet["bet365_ontario_covered"] is False)
        self.assertNotEqual(output, self.m.export_handoff(self.root, self.store, [event], self.now))

    def test_optional_depth_degrades_to_affordable_core(self):
        job = {"kind": "props", "markets": list(self.m.CORE + self.m.EXTRA), "enhanced": True}
        adjusted = self.m.affordable_job(job, 84, 88, 1)
        self.assertEqual(adjusted["markets"], list(self.m.CORE))
        self.assertFalse(adjusted["enhanced"])
        self.assertIsNone(
            self.m.affordable_job({"kind": "board", "markets": list(self.m.BOARD)}, 84, 84, 1)
        )

    def test_worker_lock_excludes_overlapping_discovery(self):
        with (
            self.m.worker_lock(self.root),
            self.assertRaises(self.m.BudgetError),
            self.m.worker_lock(self.root),
        ):
            self.fail("second worker acquired lock")

    def test_disappeared_game_remains_a_reported_missed_capture(self):
        self.m.save_inventory(
            self.store, [{"id": "gone", "commence_time": "2026-10-04T15:00:00Z"}], self.now
        )
        output = self.m.export_handoff(self.root, self.store, [], self.now)
        body = json.loads(output.read_bytes())
        self.assertEqual(body["missed_event_ids"], ["gone"])
        self.assertEqual(body["uncaptured_event_ids"], ["gone"])

    def test_failed_paid_call_updates_handoff_even_without_success(self):
        event = {"id": "event1", "commence_time": "2026-10-04T17:00:00Z"}

        def fake_fetch(path, params, key):
            if path.endswith("/events"):
                return json.dumps([event]).encode(), {
                    "x-requests-used": "2",
                    "x-requests-remaining": "498",
                    "x-requests-last": "0",
                }
            raise RuntimeError("unknown provider outcome")

        with (
            patch.object(self.m, "fetch", fake_fetch),
            patch.object(self.m, "load_key", return_value="secret"),
            self.assertRaises(self.m.BudgetError),
        ):
            self.m.run_locked(self.root, execute=True, now=self.now)
        outputs = list(self.root.glob("outputs/nfl-quant-interface/*/weekly_handoff_*.json"))
        self.assertEqual(len(outputs), 1)
        body = json.loads(outputs[0].read_bytes())
        self.assertEqual(len(body["unresolved_calls"]), 1)
        self.assertEqual(body["unresolved_calls"][0]["status"], "RECONCILIATION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
