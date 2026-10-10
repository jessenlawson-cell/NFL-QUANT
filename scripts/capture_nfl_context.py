"""Free personal-research NFL context. No credentials, odds calls or identity joins."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

NFL = "https://www.nfl.com"
WEATHER_FIELDS = (
    "temperature_2m",
    "wind_speed_10m",
    "wind_gusts_10m",
    "precipitation",
    "precipitation_probability",
)
STATES = dict(
    zip(
        [
            "AZ",
            "CA",
            "CO",
            "FL",
            "GA",
            "IL",
            "IN",
            "LA",
            "MA",
            "MD",
            "MI",
            "MN",
            "MO",
            "NC",
            "NJ",
            "NV",
            "NY",
            "OH",
            "PA",
            "TN",
            "TX",
            "WA",
            "WI",
        ],
        [
            "Arizona",
            "California",
            "Colorado",
            "Florida",
            "Georgia",
            "Illinois",
            "Indiana",
            "Louisiana",
            "Massachusetts",
            "Maryland",
            "Michigan",
            "Minnesota",
            "Missouri",
            "North Carolina",
            "New Jersey",
            "Nevada",
            "New York",
            "Ohio",
            "Pennsylvania",
            "Tennessee",
            "Texas",
            "Washington",
            "Wisconsin",
        ],
        strict=True,
    )
)


def instant(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Missing timezone")
    return value.astimezone(UTC)


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return " ".join(
            " ".join(c.text() if isinstance(c, Node) else c for c in self.children).split()
        )

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()


class Document(HTMLParser):
    """Small structural parser; scripts/styles never become evidence text."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not any(n.tag in {"script", "style"} for n in self.stack):
            self.stack[-1].children.append(data)


def parse_injuries(html, season, week):
    doc = Document(html)
    title = next((n.text() for n in doc.root.walk() if n.tag == "title"), "")
    if not re.search(rf"Week\s+{week}\b", title, re.I) or str(season) not in title:
        raise ValueError("Injury report season/week mismatch")
    expected = ["Player", "Position", "Injuries", "Practice Status", "Game Status"]
    team, rows = None, []
    for node in doc.root.walk():
        if "d3-o-section-sub-title" in node.attrs.get("class", "").split():
            team = node.text()
        if node.tag != "table":
            continue
        headers = [n.text() for n in node.walk() if n.tag == "th"]
        if headers != expected:
            continue
        if not team:
            raise ValueError("Injury table missing team context")
        for tr in (n for n in node.walk() if n.tag == "tr"):
            cells = [n for n in tr.children if isinstance(n, Node) and n.tag == "td"]
            if not cells:
                continue
            if len(cells) != 5:
                raise ValueError("Injury row schema drift")
            links = [n.attrs.get("href") for n in cells[0].walk() if n.tag == "a"]
            rows.append(
                dict(
                    zip(
                        ("player_label", "position", "injury", "practice_status", "game_status"),
                        [c.text() or None for c in cells],
                        strict=True,
                    )
                )
                | {
                    "team_label": team,
                    "player_gsis_id": None,
                    "source_player_url": links[0] if len(links) == 1 else None,
                }
            )
    if not rows:
        raise ValueError("No recognized injury rows; not an empty injury report")
    keys = [(r["team_label"], r["source_player_url"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate injury source keys")
    return rows


def parse_inactives(html):
    result = {}
    team = None
    for wrapper in Document(html).root.walk():
        if "story-part-rich-text-editor-wrapper" not in wrapper.attrs.get("class", ""):
            continue
        team = None
        for node in wrapper.walk():
            if node.tag == "h3":
                team = node.text()
            elif node.tag == "li" and team:
                text = node.text()
                if re.match(
                    r"^(?:QB|RB|FB|WR|TE|OL|OT|OG|C|G|T|DL|DT|DE|LB|ILB|OLB|DB|CB|S|FS|SS|K|P|LS)\s",
                    text,
                ):
                    result.setdefault(team, []).append(
                        {"source_text": text, "player_gsis_id": None}
                    )
    return result


def article_times(html, now):
    result = {}
    for field in ("datePublished", "dateModified"):
        values = re.findall(rf'"{field}"\s*:\s*"([^"\n]+)"', html)
        if values:
            stamp = instant(values[0])
            if stamp > now:
                raise ValueError("Future article timestamp")
            result[field] = stamp.isoformat()
    return result


def parse_scoreboard(body, start, end):
    events = []
    for e in body.get("events", []):
        if not start <= instant(e["date"]) < end:
            continue
        competitions = e.get("competitions", [])
        if len(competitions) != 1:
            raise ValueError("Ambiguous competition")
        c = competitions[0]
        events.append(
            {
                "id": str(e["id"]),
                "date": e["date"],
                "name": e.get("name"),
                "venue": c.get("venue"),
                "status": c.get("status"),
                "teams": [
                    {
                        "source_team_id": t["team"]["id"],
                        "home_away": t["homeAway"],
                        "label": t["team"]["displayName"],
                    }
                    for t in c.get("competitors", [])
                ],
            }
        )
    if not body.get("events") or len({e["id"] for e in events}) != len(events):
        raise ValueError("Empty/duplicate NFL schedule")
    years = {e.get("season", {}).get("year") for e in body["events"]}
    if len(years) != 1 or None in years:
        raise ValueError("Unknown/mixed season")
    week = body.get("week", {}).get("number")
    if not isinstance(week, int):
        raise ValueError("Unknown NFL week")
    return {
        "season": years.pop(),
        "week": week,
        "season_type": body.get("season", {}).get("type", 2),
        "events": events,
        "identity_notice": "ESPN event/team IDs only; not joined to odds or GSIS by names.",
    }


def choose_location(body, venue):
    address = venue.get("address", {})
    country = {
        "USA": "US",
        "England": "GB",
        "United Kingdom": "GB",
        "Germany": "DE",
        "Spain": "ES",
        "Brazil": "BR",
        "Mexico": "MX",
        "Australia": "AU",
    }.get(address.get("country"))
    state = STATES.get(address.get("state"))
    if not country or (country == "US" and not state):
        return None
    matches = [
        r
        for r in body.get("results", [])
        if r.get("name", "").casefold() == address.get("city", "").casefold()
        and r.get("country_code") == country
        and (country != "US" or r.get("admin1") == state)
    ]
    if len(matches) != 1:
        return None
    r = matches[0]
    lat, lon = r.get("latitude"), r.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return {
        "latitude": lat,
        "longitude": lon,
        "geocoding_id": r.get("id"),
        "precision": "APPROXIMATE_CITY_NOT_STADIUM",
        "city": r["name"],
    }


def forecast_rows(body, event):
    if body.get("utc_offset_seconds") != 0:
        raise ValueError("Weather timezone mismatch")
    hourly = body.get("hourly", {})
    times = hourly.get("time", [])
    if not times or any(len(hourly.get(f, [])) != len(times) for f in WEATHER_FIELDS):
        raise ValueError("Weather schema drift")
    kickoff = instant(event["date"])
    floor = kickoff.replace(minute=0, second=0, microsecond=0)
    result = []
    for i, value in enumerate(times):
        stamp = datetime.fromisoformat(value).replace(tzinfo=UTC)
        if floor <= stamp <= kickoff + timedelta(hours=3):
            result.append(
                {
                    "forecast_valid_at_utc": stamp.isoformat(),
                    **{f: hourly[f][i] for f in WEATHER_FIELDS},
                }
            )
    if not result or result[0]["forecast_valid_at_utc"] != floor.isoformat():
        raise ValueError("Kickoff outside forecast coverage")
    return result


def transport(url):
    allowed = {
        "www.nfl.com",
        "site.api.espn.com",
        "geocoding-api.open-meteo.com",
        "api.open-meteo.com",
    }
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in allowed:
        raise ValueError("Unapproved free-source URL")
    request = Request(
        url,
        headers={
            "User-Agent": "NFL-QUANT/1.0 personal research",
            "Accept": "application/json,text/html",
        },
    )
    with urlopen(request, timeout=8) as response:
        if urlparse(response.url).hostname not in allowed:
            raise ValueError("Unapproved redirect")
        body = response.read(3_000_001)
        if len(body) > 3_000_000:
            raise ValueError("Source size limit")
        return body, {
            k.lower(): v
            for k, v in response.headers.items()
            if k.lower() in {"last-modified", "date", "content-type"}
        }


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def source(root, key, url, now, fetch, parser, ttl=900):
    """Preserve raw capture, original observation time and failures separately."""
    cache = root / "data/runtime/market_intelligence/context" / f"{key}.json"
    previous = None
    if cache.exists():
        try:
            previous = json.loads(cache.read_bytes())
            age = (now - instant(previous["last_attempt_at_utc"])).total_seconds()
            if previous.get("url") != url or age < 0:
                previous = None
            elif age < (ttl if previous.get("status") == "CAPTURED" else min(ttl, 900)):
                return previous
        except (ValueError, KeyError):
            previous = None
    record = {
        "url": url,
        "last_attempt_at_utc": now.isoformat(),
        "captured_at_utc": None,
        "source_available_at_utc": None,
        "source_last_modified": None,
        "status": "UNAVAILABLE",
        "data": None,
    }
    try:
        body, headers = fetch(url)
        captured = (
            instant(headers["collector_capture_at_utc"])
            if ("collector_capture_at_utc" in headers)
            else now
        )
        digest = hashlib.sha256(body).hexdigest()
        raw = (
            root
            / "data/raw/market_intelligence/context"
            / now.strftime("%Y-%m-%d")
            / (f"{key}_{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}.body")
        )
        raw.parent.mkdir(parents=True, exist_ok=True)
        with raw.open("xb") as handle:
            handle.write(body)
        record.update(
            {
                "raw_path": str(raw.relative_to(root)),
                "content_hash": digest,
                "captured_at_utc": captured.isoformat(),
                "source_available_at_utc": captured.isoformat(),
                "source_last_modified": headers.get("last-modified"),
            }
        )
        # Last-Modified is metadata, not proof of historical public availability.
        data = parser(body.decode("utf-8"))
        record.update(
            {
                "status": "CAPTURED",
                "data": data,
                "schema_hash": hashlib.sha256(
                    json.dumps(
                        sorted(data.keys())
                        if isinstance(data, dict)
                        else sorted(data[0].keys())
                        if data and isinstance(data[0], dict)
                        else type(data).__name__,
                        sort_keys=True,
                    ).encode()
                ).hexdigest(),
            }
        )
    except Exception as error:
        if previous and previous.get("data") is not None:
            record = dict(previous) | {
                "status": "STALE_REFRESH_FAILED",
                "last_attempt_at_utc": now.isoformat(),
            }
        record["error_type"] = type(error).__name__
    atomic_json(cache, record)
    return record


def read_context(root, now):
    path = root / "data/runtime/market_intelligence/context/latest.json"
    try:
        body = json.loads(path.read_bytes())
        age = (now - instant(body["generated_at_utc"])).total_seconds()
        if age < 0:
            raise ValueError("Future context")
        # Do not change source timestamps when exporting a new odds handoff.
        return body | {"context_age_seconds": int(age), "stale": age > 3600}
    except (OSError, ValueError, KeyError):
        return {
            "status": "UNAVAILABLE",
            "sources": {},
            "weather": [],
            "limitations": ["Football context has not been captured successfully."],
        }


def collect(root, now, fetch=transport):
    """At most 24 free requests/60 seconds per refresh; no paid credentials."""
    local = now.astimezone(ZoneInfo("America/Toronto"))
    local_start = (local - timedelta(days=(local.weekday() - 1) % 7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = local_start.astimezone(UTC)
    end = (local_start + timedelta(days=7)).astimezone(UTC)
    week_key = local_start.date().isoformat()
    deadline, requests = time.monotonic() + 60, 0

    def bounded(url):
        nonlocal requests
        if requests >= 24 or time.monotonic() >= deadline:
            raise TimeoutError("Free context request/time bound")
        requests += 1
        body, headers = fetch(url)
        if fetch is transport:
            headers = dict(headers) | {"collector_capture_at_utc": datetime.now(UTC).isoformat()}
        return body, headers

    sources = {}
    old_events = (
        read_context(root, now).get("sources", {}).get("schedule", {}).get("data") or {}
    ).get("events", [])
    near = any(now <= instant(e["date"]) <= now + timedelta(hours=2) for e in old_events)
    ttl = 900 if near or not old_events else 3600

    scoreboard_base = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?"
    sources["schedule"] = source(
        root,
        f"{week_key}_schedule_discovery",
        scoreboard_base + "limit=100",
        now,
        bounded,
        lambda text: parse_scoreboard(json.loads(text), start, end),
        ttl,
    )
    schedule = sources.get("schedule", {}).get("data") or {}
    # On Tuesday the default NFL week can still be the completed previous week.
    # Query the next regular-season week only when it has no games in this bucket.
    if (
        schedule
        and not schedule["events"]
        and schedule.get("season_type") == 2
        and schedule["week"] < 18
    ):
        expected_season, expected_week = schedule["season"], schedule["week"] + 1

        def next_schedule(text):
            parsed = parse_scoreboard(json.loads(text), start, end)
            if parsed["season"] != expected_season or parsed["week"] != expected_week:
                raise ValueError("Requested NFL week mismatch")
            return parsed

        sources["schedule_discovery"] = sources["schedule"]
        sources["schedule"] = source(
            root,
            f"{week_key}_schedule_w{expected_week}",
            scoreboard_base
            + urlencode(
                {"week": expected_week, "year": expected_season, "seasontype": 2, "limit": 100}
            ),
            now,
            bounded,
            next_schedule,
            ttl,
        )
        schedule = sources["schedule"].get("data") or {}
    season, week = schedule.get("season"), schedule.get("week")
    events = schedule.get("events", [])
    near = any(now <= instant(e["date"]) <= now + timedelta(hours=2) for e in events)
    ttl = 900 if near else 3600
    if season and week:
        sources["injuries"] = source(
            root,
            f"{week_key}_injuries_w{week}",
            NFL + "/injuries/",
            now,
            bounded,
            lambda html: {
                "season": season,
                "week": week,
                "rows": parse_injuries(html, season, week),
            },
            ttl,
        )

        def news_links(html):
            return sorted(
                {
                    urljoin(NFL, n.attrs["href"])
                    for n in Document(html).root.walk()
                    if n.tag == "a"
                    and "href" in n.attrs
                    and urlparse(urljoin(NFL, n.attrs["href"])).hostname == "www.nfl.com"
                    and re.search(rf"week-{week}-(?:.*-)?inactives", n.attrs["href"])
                }
            )[:4]

        sources["inactive_index"] = source(
            root, f"{week_key}_news", NFL + "/news", now, bounded, news_links, ttl
        )
        for i, url in enumerate(sources["inactive_index"].get("data") or []):

            def inactive_article(html):
                dates = article_times(html, now)
                published = dates.get("datePublished")
                if not published or not start <= instant(published) < end:
                    raise ValueError("Unverified/stale inactive article")
                return {
                    "article_timestamps": dates,
                    "reported_lists": parse_inactives(html),
                    "coverage": "PARTIAL_PUBLISHED_LISTS_ONLY",
                    "notice": "Absent teams/players are unknown, never confirmed active.",
                }

            url_key = hashlib.sha256(url.encode()).hexdigest()[:12]
            sources[f"inactives_{i}"] = source(
                root, f"{week_key}_{url_key}_lists_v2", url, now, bounded, inactive_article, ttl
            )
    weather = []
    for event in events:
        kickoff = instant(event["date"])
        if not now < kickoff <= now + timedelta(days=3):
            continue
        venue = event.get("venue") or {}
        venue_id = venue.get("id")
        entry = {
            "source_event_id": event["id"],
            "game_label": event["name"],
            "kickoff_utc": event["date"],
            "venue": venue,
            "roof_status": "UNKNOWN",
            "status": "LOCATION_UNVERIFIED",
        }
        weather.append(entry)
        if not venue_id or not venue.get("address", {}).get("city"):
            continue
        location_url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
            {"name": venue["address"]["city"], "count": 20, "language": "en", "format": "json"}
        )
        location = source(
            root,
            f"venue_{venue_id}",
            location_url,
            now,
            bounded,
            lambda text, v=venue: choose_location(json.loads(text), v),
            30 * 86400,
        )
        entry["location_source"] = location
        coordinates = location.get("data")
        if not coordinates:
            continue
        weather_url = "https://api.open-meteo.com/v1/forecast?" + urlencode(
            {
                "latitude": coordinates["latitude"],
                "longitude": coordinates["longitude"],
                "hourly": ",".join(WEATHER_FIELDS),
                "timezone": "UTC",
                "forecast_days": 4,
                "wind_speed_unit": "kmh",
                "temperature_unit": "celsius",
                "precipitation_unit": "mm",
            }
        )

        def forecast(text, e=event):
            body = json.loads(text)
            return {
                "hours": forecast_rows(body, e),
                "units": body.get("hourly_units"),
                "kind": "FORECAST_NOT_OBSERVATION",
                "model_issue_time_utc": None,
                "location_precision": "APPROXIMATE_CITY_NOT_STADIUM",
                "attribution": "Weather data by Open-Meteo (https://open-meteo.com/), CC BY 4.0",
            }

        prediction = source(
            root, f"{week_key}_weather_{event['id']}", weather_url, now, bounded, forecast, ttl
        )
        entry.update(
            {
                "status": prediction["status"],
                "forecast": prediction,
                "interpretation": "Outdoor city forecast; not indoor playing conditions. "
                "Venue indoor flag does not establish today's retractable roof status.",
            }
        )
    body = {
        "schema_version": "nfl-context-1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "week_bucket": week_key,
        "season": season,
        "nfl_week": week,
        "sources": sources,
        "weather": weather,
        "free_requests_this_refresh": requests,
        "limitations": [
            "No player-name joins; source labels are display-only, GSIS unresolved.",
            "Injury designation is not a final inactive list.",
            "Inactive coverage includes only published, parsed official lists.",
            "City forecasts are approximate, not measured stadium conditions.",
            "Source issue times may be unknown; capture times are not publication times.",
        ],
    }
    atomic_json(root / "data/runtime/market_intelligence/context/latest.json", body)
    return body
