"""Capture-only, free-tier NFL market intelligence. Never imports model code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Toronto")
SPORT = "americanfootball_nfl"
CORE = ("player_pass_yds", "player_rush_yds", "player_reception_yds", "player_receptions")
EXTRA = (
    "player_pass_tds",
    "player_pass_attempts",
    "player_pass_completions",
    "player_pass_interceptions",
    "player_rush_attempts",
    "player_rush_longest",
    "player_reception_longest",
    "player_anytime_td",
)
BOARD = ("h2h", "spreads", "totals")
# Coverage candidates, NOT a fixed sharp anchor; Ontario quotes are region-specific.
BOOKS = (
    "pinnacle",
    "betonlineag",
    "draftkings",
    "fanduel",
    "betmgm",
    "betmgm_ca_on",
    "betrivers_ca_on",
    "sportsinteraction_ca_on",
)
WEEKLY_LIMIT = 84
RESERVE = 80
SAFE_HEADERS = ("x-requests-used", "x-requests-remaining", "x-requests-last")


class BudgetError(RuntimeError):
    pass


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Missing timestamp timezone")
    return parsed.astimezone(UTC)


def week_bucket(now):
    local = now.astimezone(TZ)
    return (local - timedelta(days=(local.weekday() - 1) % 7)).date().isoformat()


def open_ledger(root):
    directory = root / "data/runtime/market_intelligence"
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "captures.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS calls(
            slot TEXT PRIMARY KEY, week TEXT NOT NULL, estimated INTEGER NOT NULL,
            charged INTEGER, status TEXT NOT NULL, started TEXT NOT NULL,
            raw_path TEXT, packet_path TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS events(
            id TEXT PRIMARY KEY, week TEXT NOT NULL, kickoff TEXT NOT NULL,
            payload TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
    """)
    return db


@contextmanager
def worker_lock(root):
    directory = root / "data/runtime/market_intelligence"
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / "worker.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            if handle.seek(0, 2) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise BudgetError("Another market worker is active; no calls attempted") from None
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise BudgetError("Another market worker is active; no calls attempted") from None
        yield
    finally:
        # Closing releases the OS lock, including after a process crash. Never unlink it.
        handle.close()


def save_inventory(db, events, now):
    for event in events:
        kickoff = timestamp(event["commence_time"])
        db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "week=excluded.week,kickoff=excluded.kickoff,payload=excluded.payload,"
            "last_seen=excluded.last_seen",
            (
                event["id"],
                week_bucket(kickoff),
                kickoff.isoformat(),
                json.dumps(event),
                now.isoformat(),
                now.isoformat(),
            ),
        )
    db.commit()


def affordable_job(job, weekly_available, provider_remaining, future_cores):
    future_cost = max(0, future_cores - (job["kind"] == "props")) * 4
    discretionary = min(weekly_available, provider_remaining - RESERVE) - future_cost
    if len(job["markets"]) <= discretionary:
        return job
    if job["kind"] == "props" and min(weekly_available, provider_remaining - RESERVE) >= 4:
        return {**job, "markets": list(CORE), "enhanced": False}
    return None


def observe_quota(db, headers):
    try:
        used, remaining = (int(headers[k]) for k in SAFE_HEADERS[:2])
        if min(used, remaining) < 0 or used + remaining != 500:
            raise ValueError("Unexpected free-plan quota")
    except (KeyError, TypeError, ValueError):
        raise BudgetError(
            "Missing/invalid quota headers or account is not a 500-credit plan"
        ) from None
    previous = db.execute("SELECT value FROM metadata WHERE key='used'").fetchone()
    cycle = db.execute("SELECT value FROM metadata WHERE key='cycle'").fetchone()
    generation = int(cycle[0]) if cycle else 0
    if previous and used < int(previous[0]):
        generation += 1
    for key, value in (("used", used), ("remaining", remaining), ("cycle", generation)):
        db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (key, str(value)))
    db.commit()
    return remaining


def reserve(db, slot, week, estimate, remaining, now):
    if not 1 <= estimate <= 12:
        raise BudgetError("Unapproved request size")
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT 1 FROM calls WHERE slot=?", (slot,)).fetchone():
            db.rollback()
            return False
        if db.execute("SELECT 1 FROM calls WHERE status!='COMPLETE' LIMIT 1").fetchone():
            raise BudgetError("Prior capture requires operator reconciliation; no automatic retry")
        spent = db.execute(
            "SELECT COALESCE(SUM(COALESCE(charged,estimated)),0) FROM calls WHERE week=?",
            (week,),
        ).fetchone()[0]
        latest = db.execute("SELECT value FROM metadata WHERE key='remaining'").fetchone()
        available = min(remaining, int(latest[0])) if latest else remaining
        if spent + estimate > WEEKLY_LIMIT or available - estimate < RESERVE:
            raise BudgetError("Weekly ceiling or protected provider reserve reached")
        db.execute(
            "INSERT INTO calls(slot,week,estimated,status,started) VALUES(?,?,?,'RESERVED',?)",
            (slot, week, estimate, now.isoformat()),
        )
        db.commit()
        return True
    except BaseException:
        db.rollback()
        raise


def plan(events, now, completed, deep_event):
    local, week = now.astimezone(TZ), week_bucket(now)
    end = datetime.fromisoformat(week).replace(tzinfo=TZ) + timedelta(days=7)
    eligible = []
    seen = set()
    for event in events:
        event_id = event["id"]
        if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", event_id):
            raise ValueError("Invalid provider event ID")
        if event_id in seen:
            raise ValueError("Duplicate provider event ID")
        seen.add(event_id)
        kickoff = timestamp(event["commence_time"])
        if now < kickoff < end:
            eligible.append(event)
    eligible.sort(key=lambda e: (timestamp(e["commence_time"]), e["id"]))
    captured_ids = {s.split(":props:", 1)[1] for s in completed if s.startswith(f"{week}:props:")}
    if len(captured_ids | {e["id"] for e in eligible}) > 16:
        raise BudgetError("More than 16 upcoming games in weekly scope; operator review required")
    deep_done = f"{week}:deep" in completed
    selected = deep_event or (eligible[0]["id"] if eligible else None)
    jobs = []
    # One-hour windows: no stale catch-up paid board when laptop wakes much later.
    for weekday, hour in ((2, 18), (4, 18), (6, 12), (0, 18)):
        slot = f"{week}:board:{weekday}"
        if local.weekday() == weekday and local.hour == hour and slot not in completed:
            jobs.append({"slot": slot, "kind": "board", "markets": list(BOARD), "event_id": None})
    for event in eligible:
        slot = f"{week}:props:{event['id']}"
        until = timestamp(event["commence_time"]) - now
        if timedelta(minutes=45) <= until <= timedelta(minutes=90) and slot not in completed:
            enhanced = event["id"] == selected and not deep_done
            jobs.append(
                {
                    "slot": slot,
                    "kind": "props",
                    "event_id": event["id"],
                    "markets": list(CORE + (EXTRA if enhanced else ())),
                    "enhanced": enhanced,
                }
            )
    return jobs


def fetch(path, params, key):
    query = urlencode({**params, "apiKey": key})
    request = Request(
        f"https://api.the-odds-api.com/v4/{path}?{query}", headers={"Accept": "application/json"}
    )
    # No retries or exception URLs: credentials travel only to the documented provider.
    with urlopen(request, timeout=30) as response:
        body = response.read(20_000_001)
        if len(body) > 20_000_000:
            raise ValueError("Response exceeds capture size limit")
        headers = {k: response.headers[k] for k in SAFE_HEADERS if k in response.headers}
        return body, headers


def write_new(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def packet(payload, job, captured_at, raw_path, digest):
    events = payload if isinstance(payload, list) else [payload]
    quotes, returned = [], set()
    for event in events:
        kickoff = timestamp(event["commence_time"])
        if kickoff <= captured_at:
            continue  # An NFL board may also contain in-play games; omit them from the packet.
        if job["event_id"] and event["id"] != job["event_id"]:
            raise ValueError("Response event does not match requested provider ID")
        keys = set()
        for book in event.get("bookmakers", []):
            if book["key"] not in BOOKS:
                raise ValueError("Unrequested bookmaker")
            for market in book.get("markets", []):
                if market["key"] not in job["markets"]:
                    raise ValueError("Unrequested market")
                updated = timestamp(market.get("last_update") or book.get("last_update", ""))
                if updated > captured_at or updated >= kickoff:
                    raise ValueError("Future/post-kickoff quote timestamp")
                returned.add(market["key"])
                for outcome in market["outcomes"]:
                    price = outcome["price"]
                    if (
                        isinstance(price, bool)
                        or not isinstance(price, (int, float))
                        or not 1 < price < float("inf")
                    ):
                        raise ValueError("Invalid decimal price")
                    key = (
                        book["key"],
                        market["key"],
                        outcome.get("description"),
                        outcome["name"],
                        outcome.get("point"),
                    )
                    if key in keys:
                        raise ValueError("Duplicate quote key")
                    keys.add(key)
                    quotes.append(
                        {
                            "provider_event_id": event["id"],
                            "home_team": event["home_team"],
                            "away_team": event["away_team"],
                            "kickoff_utc": kickoff.isoformat(),
                            "bookmaker": book["key"],
                            "market": market["key"],
                            "selection": outcome["name"],
                            "provider_description": outcome.get("description"),
                            "player_gsis_id": None,
                            "point": outcome.get("point"),
                            "decimal_odds": price,
                            "quote_time_utc": updated.isoformat(),
                            "age_seconds": (captured_at - updated).total_seconds(),
                        }
                    )
    return {
        "schema_version": "market-intelligence-1",
        "captured_at_utc": captured_at.isoformat(),
        "slot": job["slot"],
        "raw_path": raw_path,
        "raw_sha256": digest,
        "requested_markets": job["markets"],
        "returned_markets": sorted(returned),
        "missing_markets": sorted(set(job["markets"]) - returned),
        "quotes": quotes,
        "limits": [
            "bet365 Ontario is not covered by this provider",
            "No canonical player mapping; no name joins or derived player features",
            "Snapshot quotes are not guaranteed executable or still current",
            "No calibrated forecasts, EV, stakes or correlation probabilities computed",
            "Reference selection must be market-specific; no universal sharp anchor",
            "Current injuries/weather/player usage require separate sources",
        ],
    }


def capture(root, db, job, key, remaining, now, transport=fetch):
    estimate = len(job["markets"])
    week = week_bucket(now)
    if not reserve(db, job["slot"], week, estimate, remaining, now):
        return None
    try:
        path = f"sports/{SPORT}/odds"
        if job["event_id"]:
            path = f"sports/{SPORT}/events/{job['event_id']}/odds"
        params = {
            "markets": ",".join(job["markets"]),
            "bookmakers": ",".join(BOOKS),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        body, headers = transport(path, params, key)
        captured_at = datetime.now(UTC) if transport is fetch else now
        name = job["slot"].replace(":", "_")
        raw_path = f"data/raw/market_intelligence/{week}/{name}.json"
        envelope = {
            "captured_at_utc": captured_at.isoformat(),
            "request_path": path,
            "request_params": params,
            "headers": {k: headers[k] for k in SAFE_HEADERS if k in headers},
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_text": body.decode("utf-8"),
        }
        raw_bytes = json.dumps(envelope, ensure_ascii=False).encode()
        write_new(root / raw_path, raw_bytes)
        db.execute("UPDATE calls SET raw_path=? WHERE slot=?", (raw_path, job["slot"]))
        db.commit()
        observe_quota(db, headers)
        charged = int(headers["x-requests-last"])
        if not 0 <= charged <= estimate:
            raise BudgetError("Unexpected provider credit charge; operator reconciliation required")
        result = packet(
            json.loads(body), job, captured_at, raw_path, hashlib.sha256(raw_bytes).hexdigest()
        )
        result["provider_credit_cost"] = charged
        packet_path = f"outputs/nfl-quant-interface/{week}/{name}.json"
        write_new(root / packet_path, json.dumps(result, ensure_ascii=False, indent=2).encode())
        db.execute(
            "UPDATE calls SET charged=?,status='COMPLETE',packet_path=? WHERE slot=?",
            (charged, packet_path, job["slot"]),
        )
        if job.get("enhanced"):
            db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (f"{week}:deep", "done"))
        db.commit()
        return result
    except BaseException as exc:
        # Do not record exception text: urllib errors may include an authenticated URL.
        db.execute(
            "UPDATE calls SET status='RECONCILIATION_REQUIRED',error=? WHERE slot=?",
            (type(exc).__name__, job["slot"]),
        )
        db.commit()
        raise BudgetError(
            "Capture requires operator reconciliation; automatic retry disabled"
        ) from None


def load_key(root):
    key = os.environ.get("THE_ODDS_API_KEY", "")
    if not key:
        env = root / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8-sig").splitlines():
                name, sep, value = line.partition("=")
                if sep and name.strip() == "THE_ODDS_API_KEY":
                    key = value.strip().strip("\"'")
    if not key:
        raise BudgetError("THE_ODDS_API_KEY is missing; no provider call attempted")
    return key


def export_handoff(root, db, events, now, only_if_changed=False):
    from scripts.capture_nfl_context import read_context

    week = week_bucket(now)
    rows = list(db.execute("SELECT * FROM calls WHERE week=? ORDER BY started", (week,)))
    snapshots = [
        json.loads((root / r["packet_path"]).read_bytes())
        for r in rows
        if r["status"] == "COMPLETE"
    ]
    captured = {
        r["slot"].split(":props:", 1)[1]
        for r in rows
        if r["status"] == "COMPLETE" and ":props:" in r["slot"]
    }
    in_scope = {
        r["id"]: json.loads(r["payload"])
        for r in db.execute("SELECT * FROM events WHERE week=?", (week,))
    }
    in_scope.update(
        {e["id"]: e for e in events if week_bucket(timestamp(e["commence_time"])) == week}
    )
    body = {
        "schema_version": "market-intelligence-weekly-1",
        "week_bucket": week,
        "generated_at_utc": now.isoformat(),
        "football_context": read_context(root, now),
        "snapshots": snapshots,
        "uncaptured_event_ids": sorted(e for e in in_scope if e not in captured),
        "missed_event_ids": sorted(
            e
            for e in in_scope
            if e not in captured and timestamp(in_scope[e]["commence_time"]) <= now
        ),
        "unresolved_calls": [dict(r) for r in rows if r["status"] != "COMPLETE"],
        "bet365_ontario_covered": False,
        "weekly_credit_usage": sum(
            r["charged"] if r["charged"] is not None else r["estimated"] for r in rows
        ),
        "instructions": "Use individual capture/quote times, not this packet's generation time. "
        "Missing data is unknown. US prices are not Ontario prices. No player name joins. "
        "This is market evidence, not a calibrated prediction or proven edge. "
        "Use football_context source timestamps and coverage limits; missing inactives "
        "do not mean active. City weather is approximate, not stadium observations. "
        "Ask for current bet365 Ontario quotes and verify any stale football context.",
    }
    meaningful = {k: v for k, v in body.items() if k != "generated_at_utc"}
    meaningful["football_context"] = {
        k: v
        for k, v in body["football_context"].items()
        if k not in {"generated_at_utc", "context_age_seconds", "free_requests_this_refresh"}
    }
    fingerprint = hashlib.sha256(json.dumps(meaningful, sort_keys=True).encode()).hexdigest()
    previous = db.execute("SELECT value FROM metadata WHERE key=?", (f"{week}:handoff",)).fetchone()
    if only_if_changed and previous and previous[0] == fingerprint:
        return None
    name = f"weekly_handoff_{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}.json"
    output = root / f"outputs/nfl-quant-interface/{week}" / name
    write_new(output, json.dumps(body, ensure_ascii=False, indent=2).encode())
    db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", (f"{week}:handoff", fingerprint))
    db.commit()
    return output


def run(root, execute=False, events_path=None, deep_event=None, preflight=False):
    # Serialize free discovery too: a stale balance must never overwrite a paid response.
    with worker_lock(root):
        result, output = None, None
        try:
            result = run_locked(root, execute, events_path, deep_event, preflight)
        finally:
            if execute:
                # Independent free context still runs if odds discovery/budgeting fails.
                try:
                    from scripts.capture_nfl_context import collect

                    collect(root, datetime.now(UTC))
                except Exception as error:
                    print(f"FREE_CONTEXT_REFRESH_FAILED: {type(error).__name__}", file=sys.stderr)
                try:
                    with closing(open_ledger(root)) as db:
                        event_file = root / "data/runtime/market_intelligence/events.json"
                        events = json.loads(event_file.read_bytes()) if event_file.exists() else []
                        output = export_handoff(
                            root, db, events, datetime.now(UTC), only_if_changed=True
                        )
                except Exception as error:
                    print(f"CONTEXT_HANDOFF_FAILED: {type(error).__name__}", file=sys.stderr)
        if output and result is not None:
            result["handoff"] = str(output)
        return result


def run_locked(root, execute=False, events_path=None, deep_event=None, preflight=False, now=None):
    now = now or datetime.now(UTC)
    with closing(open_ledger(root)) as db:
        completed = [r[0] for r in db.execute("SELECT slot FROM calls")]
        week = week_bucket(now)
        if db.execute("SELECT 1 FROM metadata WHERE key=?", (f"{week}:deep",)).fetchone():
            completed.append(f"{week}:deep")
        key = None
        if execute or preflight:
            key = load_key(root)
            body, headers = fetch(f"sports/{SPORT}/events", {"dateFormat": "iso"}, key)
            if headers.get("x-requests-last") != "0":
                raise BudgetError("Event discovery no longer reports zero cost; stop for review")
            remaining = observe_quota(db, headers)
            events = json.loads(body)
            event_file = root / "data/runtime/market_intelligence/events.json"
            # Atomic refresh of a disposable schedule cache, not historical evidence.
            pending = event_file.with_suffix(".tmp")
            pending.write_bytes(body)
            pending.replace(event_file)
        else:
            event_file = events_path or root / "data/runtime/market_intelligence/events.json"
            events = json.loads(event_file.read_bytes()) if event_file.exists() else []
            remaining = None
        jobs = plan(events, now, completed, deep_event)
        if not execute:
            if preflight:
                save_inventory(db, events, now)
            return {
                "mode": "FREE_PROVIDER_PREFLIGHT" if preflight else "OFFLINE_DRY_RUN",
                "jobs": jobs,
                "weekly_limit": 84,
                "protected_reserve": 80,
                "events_cached": len(events),
                "network_calls": 1 if preflight else 0,
                "provider_remaining": remaining,
            }
        save_inventory(db, events, now)
        results = []
        # Core coverage first. Deep data and board calls must not crowd out remaining cores.
        jobs.sort(key=lambda job: job["kind"] != "props")
        future_cores = sum(
            1
            for e in events
            if now < timestamp(e["commence_time"])
            and week_bucket(timestamp(e["commence_time"])) == week
            and f"{week}:props:{e['id']}" not in completed
        )
        try:
            for job in jobs:
                spent = db.execute(
                    "SELECT COALESCE(SUM(COALESCE(charged,estimated)),0) FROM calls WHERE week=?",
                    (week,),
                ).fetchone()[0]
                job = affordable_job(job, WEEKLY_LIMIT - spent, remaining, future_cores)
                if job is None:
                    continue
                result = capture(root, db, job, key, remaining, now, transport=fetch)
                if result:
                    remaining = int(
                        db.execute("SELECT value FROM metadata WHERE key='remaining'").fetchone()[0]
                    )
                    results.append(
                        {
                            "slot": job["slot"],
                            "quotes": len(result["quotes"]),
                            "cost": result["provider_credit_cost"],
                        }
                    )
                    if job["kind"] == "props":
                        future_cores -= 1
        finally:
            # Surface missed windows and failed calls even when no capture succeeded.
            output = export_handoff(root, db, events, datetime.now(UTC), only_if_changed=True)
        return {
            "mode": "CAPTURE_ONLY",
            "captures": results,
            "provider_remaining": remaining,
            "handoff": str(output) if output else None,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Allow budgeted provider calls")
    parser.add_argument(
        "--refresh-context",
        action="store_true",
        help="Refresh free NFL context and export a handoff; no odds provider calls",
    )
    parser.add_argument(
        "--preflight", action="store_true", help="Free event discovery only; no odds calls"
    )
    parser.add_argument("--events", type=Path, help="Offline event fixture/cache for dry-run")
    parser.add_argument(
        "--deep-event", help="Exact provider event ID for this week's deeper capture"
    )
    args = parser.parse_args()
    if args.refresh_context:
        if args.execute or args.preflight:
            parser.error("--refresh-context cannot be combined with odds network modes")
        from scripts.capture_nfl_context import collect

        root = Path(__file__).resolve().parents[1]
        with worker_lock(root), closing(open_ledger(root)) as db:
            body = collect(root, datetime.now(UTC))
            event_file = root / "data/runtime/market_intelligence/events.json"
            events = json.loads(event_file.read_bytes()) if event_file.exists() else []
            output = export_handoff(root, db, events, datetime.now(UTC))
        print(
            json.dumps(
                {
                    "mode": "FREE_CONTEXT_ONLY",
                    "requests": body["free_requests_this_refresh"],
                    "handoff": str(output),
                }
            )
        )
        return 0
    if args.preflight and args.execute:
        parser.error("Choose either --preflight or --execute")
    root = Path(__file__).resolve().parents[1]
    try:
        print(json.dumps(run(root, args.execute, args.events, args.deep_event, args.preflight)))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "reason": type(exc).__name__,
                    "detail": str(exc)
                    if isinstance(exc, BudgetError)
                    else "Invalid input or runtime failure",
                    "action": "Inspect local ledger; do not blindly retry charged calls",
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
