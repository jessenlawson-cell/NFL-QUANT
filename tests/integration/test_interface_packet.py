from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nfl_bets.config import Settings
from nfl_bets.db import connect, initialize_database
from scripts.export_interface_packet import (
    build_packet,
    export_snapshot,
    load_validated_snapshot,
    publish_packet,
)

SNAPSHOT_ID = "11111111-1111-4111-8111-111111111111"
SNAPSHOT_TIME = "2026-09-27T12:45:00Z"
KICKOFF = "2026-09-27T17:00:00Z"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _insert(connection, table: str, values: dict) -> None:
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    connection.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values())
    )


@pytest.fixture
def source(tmp_path: Path) -> tuple[Path, Path]:
    settings = Settings.for_root(tmp_path)
    initialize_database(settings)
    raw = tmp_path / "data" / "raw" / "board.json"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b'{"fixture":"board"}')
    manifests = tmp_path / "manifests"
    manifests.mkdir(exist_ok=True)
    for version, status in (
        ("1.1.2", "LOCKED_UNTESTED_2026"),
        ("challenger-0.2.0", "SHADOW_FROZEN_WEEK3_TO_8"),
    ):
        artifact = tmp_path / "artifacts" / "models" / version / "candidate.joblib"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(f"fixture-artifact-{version}".encode())
        spec = tmp_path / (
            "MODEL_SPEC_V1_1.md" if version == "1.1.2" else "CHALLENGER_SPEC.md"
        )
        spec.write_text(f"fixture spec {version}\n", encoding="utf-8")
        (manifests / f"model_{version}_development.json").write_text(
            json.dumps(
                {
                    "model_version": version,
                    "artifact": str(artifact.relative_to(tmp_path)).replace("\\", "/"),
                    "artifact_hash": _hash(artifact.read_bytes()),
                    "spec_hash": _hash(spec.read_bytes()),
                }
            ),
            encoding="utf-8",
        )
        (manifests / f"prospective_policy_{version}.json").write_text(
            json.dumps(
                {
                    "model_version": version,
                    "status": status,
                    "artifact_hash": _hash(artifact.read_bytes()),
                    "spec_hash": _hash(spec.read_bytes()),
                    "quote_max_age_minutes": 30,
                    "allowed_decisions": ["PASS"],
                }
            ),
            encoding="utf-8",
        )
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"challenger_challenger-0.2.0_{SNAPSHOT_ID}.json").write_text(
        json.dumps(
            {
                "snapshot_id": SNAPSHOT_ID,
                "snapshot_purpose": "DECISION",
                "snapshot_time": SNAPSHOT_TIME,
                "prediction_time": "2026-09-27T12:46:00Z",
                "model_version": "challenger-0.2.0",
                "decision": "PASS",
                "markets_recorded": 1,
            }
        ),
        encoding="utf-8",
    )
    with connect(settings) as connection:
        _insert(
            connection,
            "raw_snapshots",
            {
                "snapshot_id": SNAPSHOT_ID,
                "provider": "fixture",
                "kind": "odds",
                "snapshot_purpose": "DECISION",
                "path": str(raw.relative_to(tmp_path)).replace("\\", "/"),
                "retrieved_at_utc": SNAPSHOT_TIME,
                "content_hash": _hash(raw.read_bytes()),
                "byte_count": raw.stat().st_size,
            },
        )
        _insert(
            connection,
            "api_requests",
            {
                "request_id": "request-1",
                "slot": "sunday_0845",
                "request_kind": "full-board",
                "week_bucket": "2026-09-21",
                "started_at_utc": "2026-09-27T12:44:00Z",
                "completed_at_utc": SNAPSHOT_TIME,
                "status": "COMPLETE",
                "raw_snapshot_id": SNAPSHOT_ID,
            },
        )
        _insert(
            connection,
            "games",
            {
                "game_id": "game-1",
                "season": 2026,
                "week": 3,
                "game_type": "REG",
                "kickoff_utc": KICKOFF,
                "away_team": "AWY",
                "home_team": "HME",
                "away_score": 99,
                "home_score": 88,
                "result": 11,
                "total": 187,
                "source": "fixture",
                "retrieved_at_utc": "2026-09-27T12:00:00Z",
                "schema_version": "1.1.0",
                "content_hash": "game-hash",
            },
        )
        for selection in ("HOME", "AWAY"):
            _insert(
                connection,
                "market_odds",
                {
                    "snapshot_id": SNAPSHOT_ID,
                    "provider_event_id": "event-1",
                    "game_id": "game-1",
                    "commence_time_utc": KICKOFF,
                    "bookmaker_key": "pinnacle",
                    "bookmaker_title": "Pinnacle",
                    "bookmaker_group": "anchor",
                    "market": "spreads",
                    "selection": selection,
                    "point": -3.5 if selection == "HOME" else 3.5,
                    "canonical_line": -3.5,
                    "american_price": -110,
                    "decimal_price": 1.909090909,
                    "implied_probability": 0.5238095238,
                    "vig_free_probability": 0.5,
                    "overround": 0.0476190476,
                    "last_update_utc": "2026-09-27T12:40:00Z",
                    "source": "fixture",
                    "retrieved_at_utc": SNAPSHOT_TIME,
                    "schema_version": "1.1.0",
                    "content_hash": f"quote-{selection}",
                },
            )
        for version in ("1.1.2", "challenger-0.2.0"):
            policy_bytes = (
                manifests / f"prospective_policy_{version}.json"
            ).read_bytes()
            policy = json.loads(policy_bytes)
            _insert(
                connection,
                "model_predictions",
                {
                    "prediction_id": f"prediction-{version}",
                    "model_version": version,
                    "model_artifact_hash": policy["artifact_hash"],
                    "model_spec_hash": policy["spec_hash"],
                    "policy_hash": _hash(policy_bytes),
                    "git_commit": "c" * 40,
                    "snapshot_id": SNAPSHOT_ID,
                    "provider_event_id": "event-1",
                    "game_id": "game-1",
                    "season": 2026,
                    "week": 3,
                    "kickoff_utc": KICKOFF,
                    "market": "spreads",
                    "orientation": "HOME",
                    "prediction_created_at_utc": "2026-09-27T12:46:00Z",
                    "snapshot_retrieved_at_utc": SNAPSHOT_TIME,
                    "feature_as_of_utc": "2026-09-27T12:00:00Z",
                    "feature_input_hash": "d" * 64,
                    "feature_row_hash": "e" * 64,
                    "pinnacle_updated_at_utc": "2026-09-27T12:40:00Z",
                    "pinnacle_line": -3.5,
                    "pinnacle_orientation_price": -110,
                    "pinnacle_other_price": -110,
                    "pinnacle_orientation_no_vig_probability": 0.5,
                    "calibrated_non_push_win_probability": 0.54,
                    "model_win_probability": 0.52,
                    "model_push_probability": 0.04,
                    "model_loss_probability": 0.44,
                    "retail_books_count": 0,
                    "uncertainty_status": "SHADOW_ONLY",
                    "eligibility_status": "SHADOW_ELIGIBLE",
                    "decision": "PASS",
                    "pass_reason": "research",
                    "source": "fixture",
                    "retrieved_at_utc": "2026-09-27T12:46:00Z",
                    "schema_version": "1.1.0",
                    "content_hash": f"content-{version}",
                },
            )
        connection.commit()
    return settings.db_path, tmp_path


def test_loads_only_pregame_pass_rows_and_scoreless_games(source) -> None:
    db_path, root = source
    loaded = load_validated_snapshot(db_path, root, SNAPSHOT_ID)
    assert loaded["snapshot"]["snapshot_id"] == SNAPSHOT_ID
    assert {row["model_version"] for row in loaded["predictions"]} == {
        "1.1.2",
        "challenger-0.2.0",
    }
    assert all(row["decision"] == "PASS" for row in loaded["predictions"])
    assert loaded["games"] == [
        {
            "game_id": "game-1",
            "season": 2026,
            "week": 3,
            "kickoff_utc": KICKOFF,
            "away_team": "AWY",
            "home_team": "HME",
        }
    ]
    assert "away_score" not in json.dumps(loaded)
    assert "prospective_evaluations" not in json.dumps(loaded)


def test_ineligible_null_probabilities_remain_null(source) -> None:
    db_path, root = source
    with connect(Settings.for_root(root)) as connection:
        connection.execute(
            "UPDATE model_predictions SET eligibility_status='INELIGIBLE_FEATURES', "
            "calibrated_non_push_win_probability=NULL, "
            "pinnacle_orientation_no_vig_probability=NULL, "
            "pinnacle_orientation_price=NULL, pinnacle_other_price=NULL "
            "WHERE model_version='challenger-0.2.0'"
        )
        connection.commit()
    loaded = load_validated_snapshot(db_path, root, SNAPSHOT_ID)
    row = next(r for r in loaded["predictions"] if r["model_version"] == "challenger-0.2.0")
    assert row["calibrated_non_push_win_probability"] is None
    assert row["eligibility_status"] == "INELIGIBLE_FEATURES"


@pytest.mark.parametrize(
    ("sql", "pattern"),
    [
        ("UPDATE raw_snapshots SET snapshot_purpose='CLOSE'", "DECISION"),
        ("UPDATE api_requests SET status='FAILED'", "COMPLETE"),
        ("UPDATE model_predictions SET feature_as_of_utc='2026-09-27T12:45:00Z'", "feature"),
        ("UPDATE model_predictions SET pinnacle_updated_at_utc='2026-09-27T12:46:00Z'", "quote"),
        (
            "UPDATE model_predictions SET prediction_created_at_utc='2026-09-27T17:00:00Z'",
            "kickoff",
        ),
        ("UPDATE model_predictions SET policy_hash='bad'", "policy"),
    ],
)
def test_rejects_invalid_snapshot_state(source, sql: str, pattern: str) -> None:
    db_path, root = source
    with connect(Settings.for_root(root)) as connection:
        if sql.startswith("UPDATE raw_snapshots"):
            connection.execute("DROP TRIGGER immutable_decision_close_snapshot_update")
            connection.execute("DROP TRIGGER immutable_raw_snapshot_purpose")
        connection.execute(sql)
        connection.commit()
    with pytest.raises(ValueError, match=pattern):
        load_validated_snapshot(db_path, root, SNAPSHOT_ID)


def test_rejects_missing_or_mismatched_report(source) -> None:
    db_path, root = source
    report = root / "reports" / f"challenger_challenger-0.2.0_{SNAPSHOT_ID}.json"
    report.write_text(report.read_text().replace(SNAPSHOT_ID, "other-id"), encoding="utf-8")
    with pytest.raises(ValueError, match="report"):
        load_validated_snapshot(db_path, root, SNAPSHOT_ID)
    report.unlink()
    with pytest.raises(ValueError, match="report"):
        load_validated_snapshot(db_path, root, SNAPSHOT_ID)


def test_rejects_duplicate_game_market_version(source) -> None:
    db_path, root = source
    with connect(Settings.for_root(root)) as connection:
        connection.execute(
            "INSERT INTO model_predictions SELECT 'duplicate', model_version, "
            "model_artifact_hash,model_spec_hash,policy_hash,git_commit,snapshot_id,"
            "provider_event_id,game_id,season,week,kickoff_utc,market,orientation,"
            "prediction_created_at_utc,snapshot_retrieved_at_utc,feature_as_of_utc,"
            "feature_input_hash,feature_row_hash,pinnacle_updated_at_utc,pinnacle_line,"
            "pinnacle_orientation_price,pinnacle_other_price,"
            "pinnacle_orientation_no_vig_probability,pinnacle_overround,consensus_line,"
            "consensus_probability,consensus_status,retail_books_count,raw_adjustment,"
            "adjustment_weight,final_projection,raw_non_push_win_probability,"
            "calibrated_non_push_win_probability,model_win_probability,model_push_probability,"
            "model_loss_probability,uncertainty_status,eligibility_status,decision,pass_reason,"
            "source,retrieved_at_utc,source_updated_at_utc,schema_version,content_hash "
            "FROM model_predictions WHERE model_version='1.1.2'"
        )
        connection.commit()
    with pytest.raises(ValueError, match="duplicate"):
        load_validated_snapshot(db_path, root, SNAPSHOT_ID)


def test_rejects_invalid_snapshot_id(source) -> None:
    db_path, root = source
    with pytest.raises(ValueError, match="snapshot ID"):
        load_validated_snapshot(db_path, root, "../not-a-uuid")


def test_rejects_prediction_without_matching_paired_quote(source) -> None:
    db_path, root = source
    with connect(Settings.for_root(root)) as connection:
        connection.execute("DELETE FROM market_odds WHERE selection='AWAY'")
        connection.commit()
    with pytest.raises(ValueError, match="paired quote"):
        load_validated_snapshot(db_path, root, SNAPSHOT_ID)


def test_rejects_tampered_frozen_artifact(source) -> None:
    db_path, root = source
    artifact = root / "artifacts" / "models" / "1.1.2" / "candidate.joblib"
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="artifact"):
        load_validated_snapshot(db_path, root, SNAPSHOT_ID)


def test_mixed_week_board_exports_only_earliest_week(source) -> None:
    db_path, root = source
    with connect(Settings.for_root(root)) as connection:
        game = dict(connection.execute("SELECT * FROM games WHERE game_id='game-1'").fetchone())
        game.update(game_id="game-2", week=4, kickoff_utc="2026-10-04T17:00:00Z")
        _insert(connection, "games", game)
        for row in connection.execute("SELECT * FROM market_odds").fetchall():
            quote = dict(row)
            quote.update(game_id="game-2", provider_event_id="event-2")
            _insert(connection, "market_odds", quote)
        for row in connection.execute("SELECT * FROM model_predictions").fetchall():
            prediction = dict(row)
            prediction.update(
                prediction_id=prediction["prediction_id"] + "-week4",
                game_id="game-2",
                provider_event_id="event-2",
                week=4,
                kickoff_utc="2026-10-04T17:00:00Z",
            )
            _insert(connection, "model_predictions", prediction)
        connection.commit()
    report = root / "reports" / f"challenger_challenger-0.2.0_{SNAPSHOT_ID}.json"
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["markets_recorded"] = 2
    report.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_validated_snapshot(db_path, root, SNAPSHOT_ID)
    assert len(loaded["predictions"]) == 2
    assert loaded["games"][0]["week"] == 3
    assert loaded["excluded_future_week_rows"] == 2


def test_packet_has_separate_pass_only_lanes_and_no_outcomes(source) -> None:
    db_path, root = source
    packet = build_packet(
        load_validated_snapshot(db_path, root, SNAPSHOT_ID), "2026-09-27T13:00:00Z"
    )
    assert packet["packet_version"] == "1.0.0"
    assert packet["snapshot_id"] == SNAPSHOT_ID
    assert packet["generated_at_utc"] == "2026-09-27T13:00:00Z"
    assert packet["official_decision"] == "PASS"
    assert packet["research_status"] == "RESEARCH_ONLY_UNWEIGHTED"
    assert set(packet["lanes"]) == {"1.1.2", "challenger-0.2.0"}
    assert all(
        row["decision"] == "PASS" for lane in packet["lanes"].values() for row in lane
    )
    assert packet["games"][0]["game_id"] == "game-1"
    assert "away_score" not in json.dumps(packet)
    assert "profit_loss" not in json.dumps(packet)
    assert "prospective_evaluations" not in json.dumps(packet)


def test_publish_manifest_hash_and_immutable_rerun(source) -> None:
    db_path, root = source
    selected = load_validated_snapshot(db_path, root, SNAPSHOT_ID)
    packet = build_packet(selected, "2026-09-27T13:00:00Z")
    packet_path, manifest_path = publish_packet(packet, root)
    initial_bytes = packet_path.read_bytes()
    initial_mtime = packet_path.stat().st_mtime_ns
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["packet_sha256"] == _hash(initial_bytes)
    assert manifest["snapshot_id"] == SNAPSHOT_ID
    assert publish_packet(packet, root) == (packet_path, manifest_path)
    assert packet_path.read_bytes() == initial_bytes
    assert packet_path.stat().st_mtime_ns == initial_mtime
    changed = {**packet, "generated_at_utc": "2026-09-27T13:01:00Z"}
    with pytest.raises(ValueError, match="immutable"):
        publish_packet(changed, root)


def test_export_snapshot_is_read_only_and_idempotent(source) -> None:
    db_path, root = source
    with connect(Settings.for_root(root)) as connection:
        before = connection.execute("SELECT COUNT(*) FROM api_requests").fetchone()[0]
    packet_path, manifest_path = export_snapshot(
        db_path, root, SNAPSHOT_ID, generated_at_utc="2026-09-27T13:00:00Z"
    )
    assert packet_path.is_file() and manifest_path.is_file()
    assert export_snapshot(
        db_path, root, SNAPSHOT_ID, generated_at_utc="2026-09-27T13:01:00Z"
    ) == (packet_path, manifest_path)
    with connect(Settings.for_root(root)) as connection:
        after = connection.execute("SELECT COUNT(*) FROM api_requests").fetchone()[0]
    assert (before, after) == (1, 1)


def test_export_rejects_concurrent_operational_change(source, monkeypatch) -> None:
    db_path, root = source
    import scripts.export_interface_packet as module

    original_loader = module.load_validated_snapshot

    def concurrent_loader(db_path, root, snapshot_id):
        selected = original_loader(db_path, root, snapshot_id)
        with connect(Settings.for_root(root)) as connection:
            _insert(
                connection,
                "api_requests",
                {
                    "request_id": "concurrent",
                    "slot": "sunday_1245",
                    "request_kind": "full-board",
                    "week_bucket": "2026-09-21",
                    "started_at_utc": "2026-09-27T13:00:00Z",
                    "status": "IN_PROGRESS",
                },
            )
            connection.commit()
        return selected

    monkeypatch.setattr(module, "load_validated_snapshot", concurrent_loader)
    with pytest.raises(ValueError, match="operational state changed"):
        export_snapshot(db_path, root, SNAPSHOT_ID, generated_at_utc="2026-09-27T13:00:00Z")
    assert not list((root / "manifests" / "interface").rglob("*.json"))


def test_project_instructions_define_pass_only_interface_contract() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "docs" / "interface" / "NFL_QUANT_PROJECT_INSTRUCTIONS.md"
    )
    instructions = path.read_text(encoding="utf-8")
    assert len(instructions) < 8_000
    for required in (
        "PASS",
        "RESEARCH_ONLY_UNWEIGHTED",
        "snapshot_id",
        "Python",
        "no model rerun",
        "calibrated_non_push_win_probability",
        "pinnacle_orientation_no_vig_probability",
        "model_win_probability",
        "Frozen model record",
        "Exploratory interface interpretation",
    ):
        assert required in instructions
    assert "never compare model_win_probability" in instructions
    assert "Never give a stake" in instructions


def test_weekly_prompt_requires_validated_packet_and_as_of_cutoff() -> None:
    path = Path(__file__).resolve().parents[2] / "docs" / "interface" / "WEEKLY_PROMPT.md"
    prompt = path.read_text(encoding="utf-8")
    assert "packet" in prompt.lower()
    assert "snapshot_id" in prompt
    assert "as-of cutoff" in prompt
