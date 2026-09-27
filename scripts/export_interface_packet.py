"""Read-only, explicit export of persisted PASS-only prediction evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
            development_path = root / "manifests" / f"model_{version}_development.json"
            development = json.loads(development_path.read_text(encoding="utf-8"))
            artifact_path = _within_root(root, str(development["artifact"]))
            if not artifact_path.is_file() or _sha256(artifact_path) != policy["artifact_hash"]:
                raise ValueError(f"frozen artifact hash mismatch for {version}")
            spec_name = "MODEL_SPEC_V1_1.md" if version == "1.1.2" else "CHALLENGER_SPEC.md"
            spec_bytes = (root / spec_name).read_bytes().replace(b"\r\n", b"\n")
            if hashlib.sha256(spec_bytes).hexdigest() != policy["spec_hash"]:
                raise ValueError(f"frozen specification hash mismatch for {version}")
            if (
                development.get("model_version") != version
                or development.get("artifact_hash") != policy["artifact_hash"]
                or development.get("spec_hash") != policy["spec_hash"]
            ):
                raise ValueError(f"development manifest identity mismatch for {version}")
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
        quote_rows = _rows(
            connection,
            "SELECT snapshot_id,provider_event_id,game_id,bookmaker_key,market,selection,"
            "canonical_line,american_price,vig_free_probability,last_update_utc,"
            "source_updated_at_utc FROM market_odds WHERE snapshot_id=? "
            "AND bookmaker_key='pinnacle'",
            (snapshot_id,),
        )
        quotes: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for quote in quote_rows:
            quote_key = (
                str(quote["provider_event_id"]),
                str(quote["game_id"]),
                str(quote["market"]),
            )
            quotes.setdefault(quote_key, []).append(quote)
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
                quote_key = (
                    str(row["provider_event_id"]),
                    str(row["game_id"]),
                    str(row["market"]),
                )
                paired = quotes.get(quote_key, [])
                opposite = "AWAY" if row["orientation"] == "HOME" else "UNDER"
                if len(paired) != 2 or {q["selection"] for q in paired} != {
                    row["orientation"], opposite
                }:
                    raise ValueError("paired quote missing or ambiguous")
                by_selection = {str(q["selection"]): q for q in paired}
                oriented = by_selection[str(row["orientation"])]
                other = by_selection[opposite]
                if (
                    oriented["canonical_line"] != row["pinnacle_line"]
                    or other["canonical_line"] != row["pinnacle_line"]
                    or oriented["american_price"] != row["pinnacle_orientation_price"]
                    or other["american_price"] != row["pinnacle_other_price"]
                    or abs(
                        float(oriented["vig_free_probability"])
                        - float(row["pinnacle_orientation_no_vig_probability"])
                    ) > 1e-9
                ):
                    raise ValueError("paired quote differs from persisted prediction")
                update_times = [
                    _utc(q["source_updated_at_utc"] or q["last_update_utc"], "quote")
                    for q in paired
                ]
                if (
                    max(update_times) != _utc(row["pinnacle_updated_at_utc"], "quote")
                    or min(update_times)
                    < snapshot_time
                    - timedelta(minutes=int(policy_identity["quote_max_age_minutes"]))
                    or max(update_times) > snapshot_time
                ):
                    raise ValueError("paired quote has invalid timestamp")

        game_columns = ",".join((*GAME_FIELDS, "retrieved_at_utc", "source_updated_at_utc"))
        games = _rows(
            connection,
            f"SELECT {game_columns} FROM games WHERE game_id IN "
            f"({','.join('?' for _ in game_ids)}) ORDER BY game_id",
            tuple(sorted(game_ids)),
        )
        if {str(game["game_id"]) for game in games} != game_ids:
            raise ValueError("unmatched game ID")
        game_map = {str(game["game_id"]): game for game in games}
        for game in games:
            if _utc(game["retrieved_at_utc"], "game metadata") > snapshot_time:
                raise ValueError("game metadata retrieved after decision")
            if game["source_updated_at_utc"] is not None and (
                _utc(game["source_updated_at_utc"], "game metadata") > snapshot_time
            ):
                raise ValueError("game metadata updated after decision")
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
            {field: game[field] for field in GAME_FIELDS} for game in games
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


def _json_bytes(value: dict[str, Any]) -> bytes:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return (serialized + "\n").encode("utf-8")


def build_packet(source: dict[str, Any], generated_at_utc: str) -> dict[str, Any]:
    """Construct a deterministic, scoreless weekly view of the frozen records."""
    generated = _utc(generated_at_utc, "generation")
    snapshot = source["snapshot"]
    decision = _utc(snapshot["retrieved_at_utc"], "snapshot")
    if generated < decision:
        raise ValueError("packet generation predates decision")
    games = source["games"]
    if not games:
        raise ValueError("packet requires pregame games")
    season, week = games[0]["season"], games[0]["week"]
    if any((game["season"], game["week"]) != (season, week) for game in games):
        raise ValueError("packet contains mixed weeks")
    lanes = {
        version: [
            row for row in source["predictions"] if row["model_version"] == version
        ]
        for version in MODEL_VERSIONS
    }
    if any(not rows for rows in lanes.values()):
        raise ValueError("packet requires both frozen lanes")
    packet: dict[str, Any] = {
        "packet_version": "1.0.0",
        "snapshot_id": snapshot["snapshot_id"],
        "season": season,
        "week": week,
        "generated_at_utc": generated_at_utc,
        "decision_as_of_utc": snapshot["retrieved_at_utc"],
        "official_decision": "PASS",
        "research_status": "RESEARCH_ONLY_UNWEIGHTED",
        "source": {
            "raw_snapshot": snapshot,
            "request": source["request"],
            "challenger_report": source["challenger_report"],
            "frozen_policies": source["policies"],
        },
        "games": games,
        "lanes": lanes,
        "row_counts": {version: len(rows) for version, rows in lanes.items()},
        "excluded_future_week_rows": source["excluded_future_week_rows"],
    }
    packet["payload_sha256"] = hashlib.sha256(_json_bytes(packet)).hexdigest()
    return packet


def _atomic_new_file(path: Path, content: bytes) -> None:
    """Link a complete temporary file into place without replacing any existing evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError(f"immutable interface evidence differs: {path}") from None
    finally:
        temporary.unlink(missing_ok=True)


def publish_packet(packet: dict[str, Any], root: Path) -> tuple[Path, Path]:
    """Publish packet first and manifest last; manifest marks a complete export."""
    snapshot_id = str(packet["snapshot_id"])
    if str(uuid.UUID(snapshot_id)) != snapshot_id:
        raise ValueError("invalid snapshot ID")
    bucket = f'{int(packet["season"])}-W{int(packet["week"])}'
    packet_path = root / "reports" / "interface" / bucket / f"{snapshot_id}.json"
    manifest_path = root / "manifests" / "interface" / bucket / f"{snapshot_id}.json"
    packet_bytes = _json_bytes(packet)
    packet_hash = hashlib.sha256(packet_bytes).hexdigest()
    manifest = {
        "manifest_version": "1.0.0",
        "packet_version": packet["packet_version"],
        "snapshot_id": snapshot_id,
        "season": packet["season"],
        "week": packet["week"],
        "generated_at_utc": packet["generated_at_utc"],
        "packet_path": str(packet_path.relative_to(root)).replace("\\", "/"),
        "packet_sha256": packet_hash,
        "byte_count": len(packet_bytes),
        "status": "COMPLETE",
    }
    manifest_bytes = _json_bytes(manifest)
    if manifest_path.exists():
        if not packet_path.exists() or packet_path.read_bytes() != packet_bytes:
            raise ValueError("immutable packet differs from completed manifest")
        if manifest_path.read_bytes() != manifest_bytes:
            raise ValueError("immutable manifest differs")
        return packet_path, manifest_path
    _atomic_new_file(packet_path, packet_bytes)
    if packet_path.read_bytes() != packet_bytes:
        raise ValueError("packet hash verification failed")
    _atomic_new_file(manifest_path, manifest_bytes)
    return packet_path, manifest_path


def _protected_state(db_path: Path, root: Path, snapshot_id: str) -> dict[str, Any]:
    """Fingerprint protected files and operational table sizes without any write."""
    protected = [
        root / "MODEL_SPEC_V1_1.md",
        root / "CHALLENGER_SPEC.md",
        root / "manifests" / "prospective_policy_1.1.2.json",
        root / "manifests" / "prospective_policy_challenger-0.2.0.json",
        root / "manifests" / "model_1.1.2_development.json",
        root / "manifests" / "model_challenger-0.2.0_development.json",
        root / "artifacts" / "models" / "1.1.2" / "candidate.joblib",
        root / "artifacts" / "models" / "challenger-0.2.0" / "candidate.joblib",
        root / "market_odds.csv",
        root / "model_predictions.csv",
        root / "reports" / f"challenger_challenger-0.2.0_{snapshot_id}.json",
    ]
    protected.extend(sorted((root / "src").rglob("*.py")))
    hashes = {
        str(path.relative_to(root)).replace("\\", "/"): _sha256(path)
        for path in protected
        if path.is_file()
    }
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        raw_row = connection.execute(
            "SELECT path,headers_path FROM raw_snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        raw_paths = tuple(value for value in raw_row if value) if raw_row else ()
        names = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        counts = {name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                  for name in names}
        schema = [
            tuple(row) for row in connection.execute(
                "SELECT name,type,sql FROM sqlite_master ORDER BY type,name"
            )
        ]
        connection.commit()
    finally:
        connection.close()
    for raw_value in raw_paths:
        raw_path = _within_root(root, str(raw_value))
        if not raw_path.is_file():
            raise ValueError("operational raw source disappeared")
        hashes[str(raw_path.relative_to(root)).replace("\\", "/")] = _sha256(raw_path)
    return {
        "files": hashes,
        "table_counts": counts,
        "schema_sha256": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
    }


def export_snapshot(
    db_path: Path, root: Path, snapshot_id: str, *, generated_at_utc: str | None = None
) -> tuple[Path, Path]:
    """Validate, publish, and prove that no protected state moved during the export."""
    before = _protected_state(db_path, root, snapshot_id)
    selected = load_validated_snapshot(db_path, root, snapshot_id)
    if _protected_state(db_path, root, snapshot_id) != before:
        raise ValueError("operational state changed during selection")
    game = selected["games"][0]
    path = (
        root / "reports" / "interface" / f'{game["season"]}-W{game["week"]}'
        / f"{snapshot_id}.json"
    )
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            generated_at_utc = str(existing["generated_at_utc"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("immutable existing packet is malformed") from exc
    packet = build_packet(
        selected,
        generated_at_utc or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    if _protected_state(db_path, root, snapshot_id) != before:
        raise ValueError("operational state changed before publication")
    packet_path, manifest_path = publish_packet(packet, root)
    if _protected_state(db_path, root, snapshot_id) != before:
        manifest_path.unlink(missing_ok=True)
        raise ValueError("operational state changed during publication")
    return packet_path, manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    packet_path, manifest_path = export_snapshot(
        root / "data" / "runtime" / "nfl_bets.sqlite3", root, args.snapshot_id
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(json.dumps({
        "packet": str(packet_path),
        "manifest": str(manifest_path),
        "packet_sha256": manifest["packet_sha256"],
        "official_decision": "PASS",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
