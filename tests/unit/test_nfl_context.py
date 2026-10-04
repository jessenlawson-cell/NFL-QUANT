"""Offline tests for free-source context; never request sportsbook data."""

import importlib.util
import json
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parents[2]


class ContextTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "nfl_context", ROOT / "scripts/capture_nfl_context.py"
        )
        self.assertTrue(Path(spec.origin).exists(), "free context collector not implemented")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 10, 4, 15, 0, tzinfo=UTC)

    def injury_html(self):
        return """<title>Injury Report - Week 4 of the 2026 Season</title>
        <div class="d3-o-section-sub-title"><span>Colts</span></div>
        <table><tr><th>Player</th><th>Position</th><th>Injuries</th>
        <th>Practice Status</th><th>Game Status</th></tr>
        <tr><td><a href="/players/raw-label/">Raw Label</a></td><td>QB</td>
        <td>Shoulder</td><td>Limited</td><td>Questionable</td></tr></table>"""

    def test_injury_schema_and_null_identity(self):
        result = self.m.parse_injuries(self.injury_html(), 2026, 4)
        self.assertEqual(result[0]["game_status"], "Questionable")
        self.assertIsNone(result[0]["player_gsis_id"])
        self.assertEqual(result[0]["source_player_url"], "/players/raw-label/")

    def test_stale_week_and_schema_drift_rejected(self):
        for html in [
            self.injury_html().replace("Week 4", "Week 3"),
            self.injury_html().replace("Game Status", "Changed"),
        ]:
            with self.assertRaises(ValueError):
                self.m.parse_injuries(html, 2026, 4)

    def test_inactives_only_article_lists_not_navigation(self):
        html = """<li>Navigation</li><h3>Noise</h3>
        <div class="story-part-rich-text-editor-wrapper"><h3>COLTS</h3>
        <ul><li>QB Raw Label (emergency third QB)</li></ul><h3>COMMANDERS</h3></div>
        <div class="story-part-rich-text-editor-wrapper"><ul>
        <li>WHERE: Another stadium</li><li>WHEN: 1 p.m.</li></ul></div>"""
        result = self.m.parse_inactives(html)
        self.assertEqual(result["COLTS"][0]["source_text"], "QB Raw Label (emergency third QB)")
        self.assertNotIn("Noise", result)
        self.assertNotIn("COMMANDERS", result)
        self.assertIsNone(result["COLTS"][0]["player_gsis_id"])

    def test_future_source_time_rejected(self):
        with self.assertRaises(ValueError):
            self.m.article_times('{"dateModified":"2026-10-05T15:00:00Z"}', self.now)

    def test_location_requires_unambiguous_city_country_state(self):
        venue = {"address": {"city": "Charlotte", "state": "NC", "country": "USA"}}
        candidate = {
            "name": "Charlotte",
            "country_code": "US",
            "admin1": "North Carolina",
            "latitude": 35.2,
            "longitude": -80.8,
        }
        result = self.m.choose_location({"results": [candidate]}, venue)
        self.assertEqual(result["precision"], "APPROXIMATE_CITY_NOT_STADIUM")
        self.assertIsNone(self.m.choose_location({"results": [candidate, candidate]}, venue))
        self.assertIsNone(
            self.m.choose_location({"results": [{**candidate, "admin1": "Virginia"}]}, venue)
        )

    def test_forecast_is_utc_hourly_window_not_observation_or_roof_claim(self):
        event = {"id": "1", "date": "2026-10-04T17:25Z", "venue": {"indoor": True}}
        hourly = {
            "time": ["2026-10-04T17:00", "2026-10-04T18:00"],
            "temperature_2m": [20, 21],
            "wind_speed_10m": [10, 11],
            "wind_gusts_10m": [15, 16],
            "precipitation": [0, 0.1],
            "precipitation_probability": [10, 20],
        }
        result = self.m.forecast_rows(
            {"utc_offset_seconds": 0, "hourly": hourly, "hourly_units": {"wind_speed_10m": "km/h"}},
            event,
        )
        self.assertEqual(result[0]["forecast_valid_at_utc"], "2026-10-04T17:00:00+00:00")
        self.assertEqual(result[0]["wind_gusts_10m"], 15)
        with self.assertRaises(ValueError):
            self.m.forecast_rows({"utc_offset_seconds": 3600, "hourly": hourly}, event)

    def test_failed_refresh_preserves_prior_capture_without_freshening_it(self):
        def ok(url):
            return b'{"value":1}', {}

        first = self.m.source(self.root, "test", "https://example.test", self.now, ok, json.loads)

        def fail(url):
            raise OSError("offline")

        later = self.now + timedelta(hours=1)
        second = self.m.source(self.root, "test", "https://example.test", later, fail, json.loads)
        self.assertEqual(second["captured_at_utc"], first["captured_at_utc"])
        self.assertEqual(second["status"], "STALE_REFRESH_FAILED")
        self.assertTrue((self.root / first["raw_path"]).exists())

    def test_source_cache_and_immutable_hashes(self):
        def transport(url):
            return b'{"value":1}', {"last-modified": "Sun, 04 Oct 2026 14:00:00 GMT"}

        first = self.m.source(
            self.root, "test", "https://example.test", self.now, transport, json.loads
        )
        second = self.m.source(
            self.root,
            "test",
            "https://example.test",
            self.now,
            lambda url: self.fail("duplicate network call"),
            json.loads,
        )
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(second["source_last_modified"], "Sun, 04 Oct 2026 14:00:00 GMT")
        self.assertEqual(
            len(list((self.root / "data/raw/market_intelligence/context").rglob("*.body"))), 1
        )

    def test_article_link_list_is_valid_source_data(self):
        result = self.m.source(
            self.root,
            "links",
            "https://example.test",
            self.now,
            lambda url: (b'["https://www.nfl.com/news/example"]', {}),
            json.loads,
        )
        self.assertEqual(result["status"], "CAPTURED")
        self.assertEqual(result["data"], ["https://www.nfl.com/news/example"])

    def test_failed_long_lived_source_can_retry_after_15_minutes(self):
        self.m.source(
            self.root,
            "geo",
            "https://example.test",
            self.now,
            lambda url: (_ for _ in ()).throw(OSError()),
            json.loads,
            ttl=30 * 86400,
        )
        result = self.m.source(
            self.root,
            "geo",
            "https://example.test",
            self.now + timedelta(minutes=16),
            lambda url: (b'{"latitude":35}', {}),
            json.loads,
            ttl=30 * 86400,
        )
        self.assertEqual(result["data"], {"latitude": 35})

    def test_future_cache_not_accepted(self):
        self.m.source(
            self.root,
            "test",
            "https://example.test",
            self.now + timedelta(days=1),
            lambda url: (b'{"value":1}', {}),
            json.loads,
        )
        current = self.m.source(
            self.root,
            "test",
            "https://example.test",
            self.now,
            lambda url: (_ for _ in ()).throw(OSError()),
            json.loads,
        )
        self.assertIsNone(current["data"])

    def test_handoff_reads_context_without_network(self):
        import scripts.capture_market_intelligence as worker

        path = self.root / "data/runtime/market_intelligence/context/latest.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "nfl-context-1",
                    "generated_at_utc": self.now.isoformat(),
                    "sources": {},
                }
            )
        )
        with closing(worker.open_ledger(self.root)) as db:
            handoff = json.loads(worker.export_handoff(self.root, db, [], self.now).read_bytes())
        self.assertEqual(handoff["football_context"]["schema_version"], "nfl-context-1")

    def test_cached_context_age_alone_does_not_duplicate_handoffs(self):
        import scripts.capture_market_intelligence as worker

        path = self.root / "data/runtime/market_intelligence/context/latest.json"
        self.m.atomic_json(
            path,
            {
                "schema_version": "nfl-context-1",
                "sources": {},
                "generated_at_utc": self.now.isoformat(),
            },
        )
        with closing(worker.open_ledger(self.root)) as db:
            first = worker.export_handoff(self.root, db, [], self.now, only_if_changed=True)
            second = worker.export_handoff(
                self.root, db, [], self.now + timedelta(minutes=1), only_if_changed=True
            )
        self.assertTrue(first.exists())
        self.assertIsNone(second)

    def test_free_context_failure_does_not_stop_odds_handoff(self):
        from unittest.mock import patch

        import scripts.capture_market_intelligence as worker

        def odds(path, params, key):
            return b"[]", {
                "x-requests-last": "0",
                "x-requests-remaining": "498",
                "x-requests-used": "2",
            }

        with (
            patch.object(worker, "fetch", odds),
            patch.object(worker, "load_key", return_value="test"),
            patch("scripts.capture_nfl_context.collect", side_effect=OSError()),
        ):
            result = worker.run(self.root, execute=True)
        self.assertEqual(result["captures"], [])
        self.assertTrue(Path(result["handoff"]).exists())

    def test_odds_discovery_failure_still_exports_free_context(self):
        from unittest.mock import patch

        import scripts.capture_market_intelligence as worker

        def context(root, now):
            self.m.atomic_json(
                root / "data/runtime/market_intelligence/context/latest.json",
                {
                    "generated_at_utc": now.isoformat(),
                    "sources": {},
                    "schema_version": "nfl-context-1",
                },
            )

        with (
            patch.object(worker, "fetch", side_effect=OSError()),
            patch.object(worker, "load_key", return_value="test"),
            patch("scripts.capture_nfl_context.collect", side_effect=context),
            self.assertRaises(OSError),
        ):
            worker.run(self.root, execute=True)
        handoffs = list((self.root / "outputs/nfl-quant-interface").rglob("weekly_handoff_*.json"))
        self.assertEqual(len(handoffs), 1)
        self.assertEqual(
            json.loads(handoffs[0].read_bytes())["football_context"]["schema_version"],
            "nfl-context-1",
        )

    def test_weekly_collection_includes_monday_night_and_uses_supported_week_query(self):
        event = {
            "id": "monday",
            "date": "2026-10-06T00:15Z",
            "name": "Display only",
            "season": {"year": 2026},
            "competitions": [
                {
                    "competitors": [],
                    "venue": {
                        "id": "clt",
                        "indoor": False,
                        "address": {"city": "Charlotte", "state": "NC", "country": "USA"},
                    },
                }
            ],
        }

        def fetch(url):
            if "injuries/" in url:
                return self.injury_html().encode(), {}
            if "scoreboard?" in url:
                params = parse_qs(urlparse(url).query)
                if ("week" in params and params["week"] != ["4"]) or "dates" in params:
                    raise ValueError("Unsupported NFL scoreboard query")
                return json.dumps({"week": {"number": 4}, "events": [event]}).encode(), {}
            if "geocoding" in url:
                return json.dumps(
                    {
                        "results": [
                            {
                                "name": "Charlotte",
                                "country_code": "US",
                                "admin1": "North Carolina",
                                "latitude": 35.2,
                                "longitude": -80.8,
                            }
                        ]
                    }
                ).encode(), {}
            if "forecast?" in url:
                return json.dumps(
                    {
                        "utc_offset_seconds": 0,
                        "hourly_units": {},
                        "hourly": {
                            "time": ["2026-10-06T00:00", "2026-10-06T01:00"],
                            **{f: [1, 2] for f in self.m.WEATHER_FIELDS},
                        },
                    }
                ).encode(), {}
            if url.endswith("/news"):
                return b"<html></html>", {}
            raise ValueError("Unexpected source")

        body = self.m.collect(self.root, self.now, fetch)
        self.assertEqual(body["season"], 2026)
        self.assertEqual(body["weather"][0]["source_event_id"], "monday")
        self.assertEqual(body["weather"][0]["status"], "CAPTURED")

    def test_missing_or_mismatched_injuries_do_not_suppress_independent_sources(self):
        for bad_report in [
            None,
            self.injury_html().replace("Week 4", "Week 3"),
            self.injury_html().replace("Week 4", "Week 5"),
        ]:
            with self.subTest(report=bad_report), tempfile.TemporaryDirectory() as directory:
                event = {
                    "id": "monday",
                    "date": "2026-10-06T00:15Z",
                    "name": "Game",
                    "season": {"year": 2026},
                    "competitions": [{"competitors": []}],
                }

                def fetch(url, event=event, bad_report=bad_report):
                    if "scoreboard?" in url:
                        return json.dumps({"week": {"number": 4}, "events": [event]}).encode(), {}
                    if "injuries/" in url:
                        if bad_report is None:
                            raise OSError("injury source offline")
                        return bad_report.encode(), {}
                    if url.endswith("/news"):
                        return b'<a href="/news/week-4-monday-inactives">article</a>', {}
                    if url.endswith("/week-4-monday-inactives"):
                        return (
                            b"""<script>{"datePublished":"2026-10-04T14:00:00Z"}</script>
                        <div class="story-part-rich-text-editor-wrapper"><h3>TEAM</h3>
                        <ul><li>QB Display Label</li></ul></div>""",
                            {},
                        )
                    raise ValueError("Unexpected source")

                result = self.m.collect(Path(directory), self.now, fetch)
                self.assertEqual(result["season"], 2026)
                self.assertEqual(result["nfl_week"], 4)
                self.assertEqual(result["sources"]["injuries"]["status"], "UNAVAILABLE")
                self.assertEqual(result["sources"]["inactives_0"]["status"], "CAPTURED")

    def test_tuesday_uses_upcoming_week_and_rejects_previous_injury_page(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

        def fetch(url):
            if "scoreboard?" in url:
                week = int(parse_qs(urlparse(url).query).get("week", ["4"])[0])
                date = "2026-10-06T00:15Z" if week == 4 else "2026-10-11T17:00Z"
                return json.dumps(
                    {
                        "week": {"number": week},
                        "season": {"type": 2},
                        "events": [
                            {
                                "id": str(week),
                                "date": date,
                                "name": "Display",
                                "season": {"year": 2026},
                                "competitions": [{"competitors": []}],
                            }
                        ],
                    }
                ).encode(), {}
            if "injuries/" in url:
                return self.injury_html().encode(), {}
            if url.endswith("/news"):
                return b"<html></html>", {}
            raise ValueError("Unexpected source")

        result = self.m.collect(self.root, now, fetch)
        self.assertEqual(result["week_bucket"], "2026-10-06")
        self.assertEqual(result["nfl_week"], 5)
        self.assertEqual(result["sources"]["schedule"]["data"]["events"][0]["id"], "5")
        self.assertEqual(result["sources"]["injuries"]["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
