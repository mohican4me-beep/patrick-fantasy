"""The three permitted sources: how to fetch each and how to read what comes back.

Parsers are written to each provider's documented format and are deliberately defensive:
a record missing a required field is reported as a problem, never filled in. Nothing here
was verified against a live response until the probe ran; see data/probe/report.md.
"""

from __future__ import annotations

import csv
import io
import json
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from uclfa.ingest import http


@dataclass
class Parsed:
    records: list[dict[str, Any]]
    problems: list[str] = field(default_factory=list)
    fields_seen: list[str] = field(default_factory=list)
    fields_missing: list[str] = field(default_factory=list)
    raw_sample: Any = None


@dataclass(frozen=True)
class Source:
    key: str  # snapshot folder name
    title: str
    secret_env: str | None  # environment variable holding the key; None if no key is needed
    build_url: Callable[[date, str | None], str]
    build_headers: Callable[[str | None], dict[str, str]]
    parse: Callable[[str], Parsed]
    minimum_records: int  # fewer than this means the response is rejected
    quota_headers: tuple[str, ...] = ()


def _missing(expected: tuple[str, ...], seen: list[str]) -> list[str]:
    return [name for name in expected if name not in seen]


def _utc(value: str) -> str:
    """Normalise an ISO timestamp to UTC, e.g. 2026-11-24T17:45:00+00:00."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


# -- football-data.org: fixtures and results ------------------------------------------

FIXTURE_FIELDS = ("id", "utcDate", "status", "matchday", "stage", "homeTeam", "awayTeam", "score")


def parse_football_data(text: str) -> Parsed:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return Parsed([], [f"Response is not JSON: {exc}"])
    matches = data.get("matches") if isinstance(data, dict) else None
    if not isinstance(matches, list):
        return Parsed([], ["Response has no 'matches' list."], raw_sample=data)
    out = Parsed([], raw_sample=matches[:2])
    if matches and isinstance(matches[0], dict):
        out.fields_seen = sorted(matches[0])
        out.fields_missing = _missing(FIXTURE_FIELDS, out.fields_seen)
    for m in matches:
        try:
            home, away = m["homeTeam"], m["awayTeam"]
            full_time = (m.get("score") or {}).get("fullTime") or {}
            record = {
                "source_id": m["id"],
                "kickoff_utc": _utc(m["utcDate"]),
                "status": m["status"],
                "matchday": m.get("matchday"),
                "stage": m.get("stage"),
                "home": home.get("name"),
                "home_short": home.get("shortName"),
                "away": away.get("name"),
                "away_short": away.get("shortName"),
                "home_goals": full_time.get("home"),
                "away_goals": full_time.get("away"),
            }
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            out.problems.append(f"Match skipped, unreadable ({exc!r}): {str(m)[:120]}")
            continue
        if not record["home"] or not record["away"]:
            # Knockout ties not yet drawn have no teams; that is expected, not an error.
            continue
        out.records.append(record)
    return out


# -- ClubElo: daily club ratings --------------------------------------------------------

ELO_FIELDS = ("Rank", "Club", "Country", "Level", "Elo", "From", "To")


def parse_clubelo(text: str) -> Parsed:
    reader = csv.DictReader(io.StringIO(text))
    seen = list(reader.fieldnames or [])
    out = Parsed([], fields_seen=seen, fields_missing=_missing(ELO_FIELDS, seen))
    if "Club" not in seen or "Elo" not in seen:
        out.problems.append("Response is not the expected CSV: no Club or Elo column.")
        out.raw_sample = text[:300]
        return out
    for row in reader:
        try:
            out.records.append(
                {
                    "club": row["Club"],
                    "country": row.get("Country"),
                    "level": int(row["Level"]) if row.get("Level") else None,
                    "elo": round(float(row["Elo"]), 2),
                    "valid_from": row.get("From"),
                    "valid_to": row.get("To"),
                }
            )
        except (KeyError, ValueError) as exc:
            out.problems.append(f"Row skipped, unreadable ({exc!r}): {row}")
    out.raw_sample = out.records[:2]
    return out


# -- The Odds API: match odds -----------------------------------------------------------

ODDS_FIELDS = ("id", "commence_time", "home_team", "away_team", "bookmakers")


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def parse_odds_api(text: str) -> Parsed:
    try:
        events = json.loads(text)
    except json.JSONDecodeError as exc:
        return Parsed([], [f"Response is not JSON: {exc}"])
    if not isinstance(events, list):
        return Parsed([], ["Response is not a list of events."], raw_sample=events)
    out = Parsed([], raw_sample=events[:1])
    if events and isinstance(events[0], dict):
        out.fields_seen = sorted(events[0])
        out.fields_missing = _missing(ODDS_FIELDS, out.fields_seen)
    for e in events:
        try:
            home, away = e["home_team"], e["away_team"]
            prices: dict[str, list[float]] = {k: [] for k in ("home", "draw", "away")}
            # Bookmakers quote different goal lines, so totals are kept per line.
            lines: dict[float, dict[str, list[float]]] = {}
            books = 0
            for book in e.get("bookmakers") or []:
                used = False
                for market in book.get("markets") or []:
                    for o in market.get("outcomes") or []:
                        price = float(o["price"])
                        if market.get("key") == "h2h":
                            side = {home: "home", away: "away", "Draw": "draw"}.get(o.get("name"))
                            if side:
                                prices[side].append(price)
                                used = True
                        elif market.get("key") == "totals" and o.get("point") is not None:
                            side = {"Over": "over", "Under": "under"}.get(o.get("name"))
                            if side:
                                line = lines.setdefault(
                                    float(o["point"]), {"over": [], "under": []}
                                )
                                line[side].append(price)
                books += used
            totals = [
                {
                    "line": point,
                    "bookmakers": min(len(v["over"]), len(v["under"])),
                    "over_price": _median(v["over"]),
                    "under_price": _median(v["under"]),
                }
                for point, v in sorted(lines.items())
                if v["over"] and v["under"]
            ]
            # The main line is the one most bookmakers quote; a tie goes to the lower line.
            main = max(totals, key=lambda t: (t["bookmakers"], -t["line"]), default=None)
            out.records.append(
                {
                    "source_id": e["id"],
                    "kickoff_utc": _utc(e["commence_time"]),
                    "home": home,
                    "away": away,
                    "bookmakers": books,
                    "home_price": _median(prices["home"]),
                    "draw_price": _median(prices["draw"]),
                    "away_price": _median(prices["away"]),
                    "total_line": main["line"] if main else None,
                    "total_bookmakers": main["bookmakers"] if main else 0,
                    "over_price": main["over_price"] if main else None,
                    "under_price": main["under_price"] if main else None,
                    "totals": totals,
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            out.problems.append(f"Event skipped, unreadable ({exc!r}): {str(e)[:120]}")
    return out


# -- registry ---------------------------------------------------------------------------

SOURCES: dict[str, Source] = {
    "fixtures": Source(
        key="fixtures",
        title="football-data.org (Champions League fixtures and results)",
        secret_env="FOOTBALL_DATA_TOKEN",
        build_url=lambda _day, _key: "https://api.football-data.org/v4/competitions/CL/matches",
        build_headers=lambda key: {"X-Auth-Token": key or ""},
        parse=parse_football_data,
        minimum_records=100,  # the league phase alone has 144 matches
        quota_headers=("x-requests-available-minute", "x-requestcounter-reset"),
    ),
    "elo": Source(
        key="elo",
        title="ClubElo (daily club ratings)",
        secret_env=None,
        build_url=lambda day, _key: f"http://api.clubelo.com/{day.isoformat()}",
        build_headers=lambda _key: {},
        parse=parse_clubelo,
        minimum_records=300,
    ),
    "odds": Source(
        key="odds",
        title="The Odds API (Champions League match odds)",
        secret_env="ODDS_API_KEY",
        build_url=lambda _day, key: (
            "https://api.the-odds-api.com/v4/sports/soccer_uefa_champs_league/odds"
            f"?regions=eu&markets=h2h,totals&oddsFormat=decimal&dateFormat=iso&apiKey={key or ''}"
        ),
        build_headers=lambda _key: {},
        parse=parse_odds_api,
        minimum_records=0,  # no listed matches is a valid answer between rounds
        quota_headers=("x-requests-remaining", "x-requests-used", "x-requests-last"),
    ),
}


def fetch(source: Source, day: date, key: str | None) -> http.Response:
    return http.get(source.build_url(day, key), headers=source.build_headers(key))
