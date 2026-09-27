"""Read-only, explicit export of persisted PASS-only prediction evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MODEL_VERSIONS = ("1.1.2", "challenger-0.2.0")
PREDICTION_FIELDS = (
    "prediction_id", "model_version", "model_artifact_hash", "model_spec_hash",
    "policy_hash", "git_commit", "snapshot_id", "provider_event_id", "game_id",
    "season", "week", "kickoff_utc", "market", "orientation",
    "prediction_created_at_utc", "snapshot_retrieved_at_utc", "feature_as_of_utc",
    "feature_input_hash", "feature_row_hash", "pinnacle_updated_at_utc",
    "pinnacle_line", "pinnacle_orientation_price", "pinnacle_other_price",
    "pinnacle_orientation_no_vig_probability", "pinnacle_overround",
    "consensus_line", "consensus_probability", "consensus_status",
    "retail_books_count", "raw_adjustment", "adjustment_weight", "final_projection",
    "raw_non_push_win_probability", "calibrated_non_push_win_probability",
    "model_win_probability", "model_push_probability", "model_loss_probability",
    "uncertainty_status", "eligibility_status", "decision", "pass_reason",
    "source", "retrieved_at_utc", "source_updated_at_utc", "schema_version",
    "content_hash",
)
GAME_FIELDS = ("game_id", "season", "week", "kickoff_utc", "away_team", "home_team")


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing {label} timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {label} timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"naive {label} timestamp")
    return parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _within_root(root: Path, value: str) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("source path escapes repository")
    return resolved


def _rows(
    connection: sqlite3.Connection, query: str, params: tuple[Any, ...]
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, params)]


def load_validated_snapshot(db_path: Path, root: Path, snapshot_id: str) -> dict[str, Any]:
    """Select one pregame decision board, with no database or operational writes."""
    try:
        if str(uuid.UUID(snapshot_id)) != snapshot_id:
            raise ValueError("invalid snapshot ID")
    except (ValueError, AttributeError) as exc:
        raise ValueError("invalid snapshot ID") from exc
    if not db_path.is_file():
        raise ValueError("operational database is missing")
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        snapshots = _rows(
            connection,
            "SELECT snapshot_id,snapshot_purpose,path,headers_path,retrieved_at_utc,"
            "content_hash,byte_count,provider,kind FROM raw_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        )
        if len(snapshots) != 1 or snapshots[0]["snapshot_purpose"] != "DECISION":
            raise ValueError("one DECISION snapshot is required")
        snapshot = snapshots[0]
        snapshot_time = _utc(snapshot["retrieved_at_utc"], "snapshot")
        requests = _rows(
            connection,
            "SELECT request_id,slot,completed_at_utc,status,raw_snapshot_id "
            "FROM api_requests WHERE raw_snapshot_id=?",
            (snapshot_id,),
        )
        if len(requests) != 1 or requests[0]["status"] != "COMPLETE":
            raise ValueError("one COMPLETE request is required")
        completed = _utc(requests[0]["completed_at_utc"], "request completion")
        if completed < snapshot_time:
            raise ValueError("request completed before snapshot")
        raw_path = _within_root(root, str(snapshot["path"]))
        if not raw_path.is_file() or raw_path.stat().st_size != snapshot["byte_count"]:
            raise ValueError("raw snapshot file missing or changed")
        if _sha256(raw_path) != snapshot["content_hash"]:
            raise ValueError("raw snapshot content hash mismatch")
        if snapshot["headers_path"]:
            headers_path = _within_root(root, str(snapshot["headers_path"]))
            if not headers_path.is_file():
                raise ValueError("raw snapshot headers missing")

        policies: dict[str, dict[str, Any]] = {}
        for version, expected_status in (
            ("1.1.2", "LOCKED_UNTESTED_2026"),
            ("challenger-0.2.0", "SHADOW_FROZEN_WEEK3_TO_8"),
        ):
            policy_path = root / "manifests" / f"prospective_policy_{version}.json"
            policy_bytes = policy_path.read_bytes()
            policy = json.loads(policy_bytes)
            if (policy.get("model_version"), policy.get("status")) != (
                version, expected_status
            ) or policy.get("allowed_decisions") != ["PASS"]:
                raise ValueError(f"invalid policy identity for {version}")
            policies[version] = {
                "model_version": version,
                "status": expected_status,
                "policy_hash": hashlib.sha256(policy_bytes).hexdigest(),
                "artifact_hash": policy["artifact_hash"],
                "spec_hash": policy["spec_hash"],
                "quote_max_age_minutes": policy["quote_max_age_minutes"],
            }

        columns = ",".join(PREDICTION_FIELDS)
        predictions = _rows(
            connection,
            f"SELECT {columns} FROM model_predictions WHERE snapshot_id=? "
            "AND model_version IN (?,?) ORDER BY model_version,game_id,market,prediction_id",
            (snapshot_id, *MODEL_VERSIONS),
        )
        if not predictions or {row["model_version"] for row in predictions} != set(MODEL_VERSIONS):
            raise ValueError("both frozen prediction versions are required")
        keys: set[tuple[str, str, str]] = set()
        game_ids: set[str] = set()
        for row in predictions:
            version = str(row["model_version"])
            policy_identity = policies[version]
            key = (version, str(row["game_id"]), str(row["market"]))
            if key in keys:
                raise ValueError("duplicate game-market-version prediction")
            keys.add(key)
            game_ids.add(str(row["game_id"]))
            if row["decision"] != "PASS":
                raise ValueError("non-PASS prediction")
            for field, policy_field in (
                ("policy_hash", "policy_hash"),
                ("model_artifact_hash", "artifact_hash"),
                ("model_spec_hash", "spec_hash"),
            ):
                if row[field] != policy_identity[policy_field]:
                    raise ValueError(f"{field} policy identity mismatch")
            if row["snapshot_retrieved_at_utc"] != snapshot["retrieved_at_utc"]:
                raise ValueError("prediction snapshot timestamp mismatch")
            kickoff = _utc(row["kickoff_utc"], "kickoff")
            prediction_time = _utc(row["prediction_created_at_utc"], "prediction")
            if not snapshot_time <= prediction_time < kickoff:
                raise ValueError("prediction at or after kickoff or before snapshot")
            if row["feature_as_of_utc"] is not None and not (
                _utc(row["feature_as_of_utc"], "feature") < snapshot_time
            ):
                raise ValueError("feature at or after decision")
            if row["feature_as_of_utc"] is None and row["eligibility_status"] == "SHADOW_ELIGIBLE":
                raise ValueError("eligible feature timestamp missing")
            quote_time_text = row["pinnacle_updated_at_utc"]
            if quote_time_text is not None:
                quote_time = _utc(quote_time_text, "quote")
                max_age = timedelta(minutes=int(policy_identity["quote_max_age_minutes"]))
                if not snapshot_time - max_age <= quote_time <= snapshot_time:
                    raise ValueError("quote outside pre-decision freshness window")
            if row["eligibility_status"] == "SHADOW_ELIGIBLE":
                required = (
                    "feature_as_of_utc", "pinnacle_updated_at_utc", "pinnacle_line",
                    "pinnacle_orientation_price", "pinnacle_other_price",
                    "pinnacle_orientation_no_vig_probability",
                    "calibrated_non_push_win_probability", "model_push_probability",
                )
                if any(row[field] is None for field in required):
                    raise ValueError("eligible prediction has missing probability or price")

        game_columns = ",".join(GAME_FIELDS)
        games = _rows(
            connection,
            f"SELECT {game_columns} FROM games WHERE game_id IN "
            f"({','.join('?' for _ in game_ids)}) ORDER BY game_id",
            tuple(sorted(game_ids)),
        )
        if {str(game["game_id"]) for game in games} != game_ids:
            raise ValueError("unmatched game ID")
        game_map = {str(game["game_id"]): game for game in games}
        for row in predictions:
            game = game_map[str(row["game_id"])]
            if (row["season"], row["week"], row["kickoff_utc"]) != (
                game["season"], game["week"], game["kickoff_utc"]
            ):
                raise ValueError("prediction-game identity mismatch")
        report_path = root / "reports" / f"challenger_challenger-0.2.0_{snapshot_id}.json"
        if not report_path.is_file():
            raise ValueError("matching challenger report missing")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (
            report.get("snapshot_id") != snapshot_id
            or report.get("snapshot_purpose") != "DECISION"
            or report.get("model_version") != "challenger-0.2.0"
            or report.get("decision") != "PASS"
            or report.get("snapshot_time") != snapshot["retrieved_at_utc"]
            or report.get("markets_recorded")
            != sum(row["model_version"] == "challenger-0.2.0" for row in predictions)
        ):
            raise ValueError("challenger report does not match snapshot")
        report_time = _utc(report.get("prediction_time"), "report prediction")
        if report_time < snapshot_time or any(
            report_time >= _utc(game["kickoff_utc"], "kickoff") for game in games
        ):
            raise ValueError("challenger report time outside pregame window")
        selected_season_week = min((game["season"], game["week"]) for game in games)
        selected_games = [
            game for game in games
            if (game["season"], game["week"]) == selected_season_week
        ]
        selected_ids = {str(game["game_id"]) for game in selected_games}
        selected_predictions = [
            row for row in predictions if str(row["game_id"]) in selected_ids
        ]
        if {row["model_version"] for row in selected_predictions} != set(MODEL_VERSIONS):
            raise ValueError("both frozen versions required in selected week")
        connection.commit()
        return {
            "snapshot": snapshot,
            "request": requests[0],
            "policies": policies,
            "games": selected_games,
            "predictions": selected_predictions,
            "excluded_future_week_rows": len(predictions) - len(selected_predictions),
            "challenger_report": {
                "path": str(report_path.relative_to(root)).replace("\\", "/"),
                "content_hash": _sha256(report_path),
                "snapshot_id": snapshot_id,
                "prediction_time": report["prediction_time"],
                "markets_recorded": report["markets_recorded"],
                "decision": "PASS",
            },
        }
    finally:
        connection.close()
