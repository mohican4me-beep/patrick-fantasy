"""Ingestion: parsers, snapshot writing, rejection of bad responses, secrets and probe.

No test touches the network. The sample responses below are SYNTHETIC: they follow each
provider's documented format with made-up clubs, and exist only to exercise the parsers.
They are replaced by real samples once the probe has run (see data/probe/).
"""

import json
from datetime import UTC, date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

from uclfa import cli
from uclfa.ingest import http
from uclfa.ingest.clubs import match_report, normalise
from uclfa.ingest.run import fetch_all, fetch_source, latest_snapshot, write_probe_report
from uclfa.ingest.sources import (
    SOURCES,
    parse_clubelo,
    parse_football_data,
    parse_odds_api,
)

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)
DAY = date(2026, 11, 13)


def fd_match(i: int, *, matchday=5, utc="2026-11-24T17:45:00Z", home=None, away=None):
    return {
        "id": 1000 + i,
        "utcDate": utc,
        "status": "TIMED",
        "matchday": matchday,
        "stage": "LEAGUE_STAGE",
        "homeTeam": {"id": i, "name": home or f"Home Club {i} FC", "shortName": f"Home {i}"},
        "awayTeam": {"id": 500 + i, "name": away or f"Away Club {i} FC", "shortName": f"Away {i}"},
        "score": {"fullTime": {"home": None, "away": None}},
    }


def fd_body(n=144, **kwargs) -> str:
    return json.dumps({"matches": [fd_match(i, **kwargs) for i in range(n)]})


def elo_body(n=400) -> str:
    rows = ["Rank,Club,Country,Level,Elo,From,To"]
    rows += [f"{i},Elo Club {i},ENG,1,{1900 - i}.5,2026-11-10,2026-11-14" for i in range(1, n + 1)]
    return "\n".join(rows)


def odds_body() -> str:
    def book(name, h, d, a, over, under):
        return {
            "key": name,
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Home Club 1 FC", "price": h},
                        {"name": "Away Club 1 FC", "price": a},
                        {"name": "Draw", "price": d},
                    ],
                },
                {
                    "key": "totals",
                    "outcomes": [
                        {"name": "Over", "price": over, "point": 2.5},
                        {"name": "Under", "price": under, "point": 2.5},
                        {"name": "Over", "price": 9.9, "point": 3.5},
                    ],
                },
            ],
        }

    return json.dumps(
        [
            {
                "id": "evt1",
                "sport_key": "soccer_uefa_champs_league",
                "commence_time": "2026-11-24T17:45:00Z",
                "home_team": "Home Club 1 FC",
                "away_team": "Away Club 1 FC",
                "bookmakers": [
                    book("a", 2.0, 3.4, 3.8, 1.8, 2.0),
                    book("b", 2.1, 3.5, 3.6, 1.9, 1.9),
                    book("c", 2.2, 3.6, 3.4, 2.0, 1.8),
                ],
            }
        ]
    )


def responder(bodies: dict[str, str | Exception], headers: dict[str, str] | None = None):
    def fetcher(source, _day, _key):
        body = bodies[source.key]
        if isinstance(body, Exception):
            raise body
        return http.Response(200, body, headers or {})

    return fetcher


KEYS = {"FOOTBALL_DATA_TOKEN": "fd-secret-token", "ODDS_API_KEY": "odds-secret-key"}


# -- parsers -------------------------------------------------------------------------


def test_fixtures_parser_reads_documented_format():
    parsed = parse_football_data(fd_body(3))
    assert len(parsed.records) == 3 and not parsed.problems and not parsed.fields_missing
    first = parsed.records[0]
    assert first["kickoff_utc"] == "2026-11-24T17:45:00+00:00"
    assert first["home"] == "Home Club 0 FC" and first["matchday"] == 5
    assert first["home_goals"] is None  # not played: no score is invented


def test_kickoff_converts_to_the_deadline_patrick_read_from_the_game(rules):
    """The game shows the matchday 5 deadline as 24 November, 19:45 in Athens."""
    record = parse_football_data(fd_body(1)).records[0]
    kickoff = datetime.fromisoformat(record["kickoff_utc"])
    assert (
        kickoff.astimezone(ZoneInfo("Europe/Athens")).strftime("%d %B, %H:%M")
        == "24 November, 19:45"
    )
    assert kickoff == rules.matchday(5).deadline_utc


def test_fixtures_parser_skips_undrawn_ties_and_reports_broken_rows():
    body = json.loads(fd_body(2))
    body["matches"].append(fd_match(7) | {"homeTeam": {"name": None}, "awayTeam": {"name": None}})
    body["matches"].append({"id": 9})  # unreadable
    parsed = parse_football_data(json.dumps(body))
    assert len(parsed.records) == 2 and len(parsed.problems) == 1


def test_fixtures_parser_reports_missing_fields_and_garbage():
    trimmed = json.loads(fd_body(1))
    del trimmed["matches"][0]["stage"]
    assert parse_football_data(json.dumps(trimmed)).fields_missing == ["stage"]
    assert parse_football_data("<html>error</html>").problems
    assert parse_football_data('{"message": "bad token"}').problems


def test_elo_parser():
    parsed = parse_clubelo(elo_body(3))
    assert [r["club"] for r in parsed.records] == ["Elo Club 1", "Elo Club 2", "Elo Club 3"]
    assert parsed.records[0]["elo"] == 1899.5 and not parsed.fields_missing
    assert parse_clubelo("not,a,ratings,file\n1,2,3,4").problems


def test_odds_parser_takes_the_median_across_bookmakers():
    record = parse_odds_api(odds_body()).records[0]
    assert (record["home_price"], record["draw_price"], record["away_price"]) == (2.1, 3.5, 3.6)
    assert (record["over_price"], record["under_price"], record["total_line"]) == (1.9, 1.9, 2.5)
    assert record["bookmakers"] == 3
    assert parse_odds_api("[]").records == [] and not parse_odds_api("[]").problems
    assert parse_odds_api('{"message": "quota"}').problems


# -- fetching ------------------------------------------------------------------------


def test_fetch_writes_dated_snapshots(tmp_path):
    fetcher = responder(
        {"fixtures": fd_body(), "elo": elo_body(), "odds": odds_body()},
        {"x-requests-remaining": "498", "x-requests-used": "2"},
    )
    outcomes = fetch_all(data_dir=tmp_path, fetcher=fetcher, env=KEYS, now=NOW)
    assert [o.status for o in outcomes] == ["ok", "ok", "ok"]
    assert outcomes[2].quota == {"x-requests-remaining": "498", "x-requests-used": "2"}
    snapshot = latest_snapshot("fixtures", tmp_path)
    assert snapshot["record_count"] == 144 and snapshot["fetched_at"] == NOW.isoformat()
    assert (tmp_path / "snapshots" / "elo" / "2026-11-13.json").exists()


def test_bad_response_keeps_the_previous_snapshot(tmp_path):
    """Acceptance: a malformed or partial response never replaces good data."""
    good = responder({"fixtures": fd_body()})
    fetch_source(SOURCES["fixtures"], data_dir=tmp_path, fetcher=good, env=KEYS, now=NOW)
    before = (tmp_path / "snapshots" / "fixtures" / "2026-11-13.json").read_bytes()

    for bad in ("<html>Service unavailable</html>", fd_body(12), '{"matches": "none"}'):
        outcome = fetch_source(
            SOURCES["fixtures"],
            data_dir=tmp_path,
            fetcher=responder({"fixtures": bad}),
            env=KEYS,
            now=NOW,
        )
        assert outcome.status == "rejected" and outcome.snapshot is None
        assert "previous snapshot stays current" in outcome.message
    assert (tmp_path / "snapshots" / "fixtures" / "2026-11-13.json").read_bytes() == before
    assert latest_snapshot("fixtures", tmp_path)["record_count"] == 144


def test_network_failure_is_reported_and_writes_nothing(tmp_path):
    failing = responder({"elo": http.SourceError("Could not reach api.clubelo.com: timed out")})
    outcome = fetch_source(SOURCES["elo"], data_dir=tmp_path, fetcher=failing, env={}, now=NOW)
    assert outcome.status == "failed" and "timed out" in outcome.message
    assert latest_snapshot("elo", tmp_path) is None


def test_source_without_a_key_is_skipped_not_requested(tmp_path):
    def must_not_be_called(*_):
        raise AssertionError("a request was made without a key")

    outcome = fetch_source(SOURCES["odds"], data_dir=tmp_path, fetcher=must_not_be_called, env={})
    assert outcome.status == "skipped" and "ODDS_API_KEY" in outcome.message


def test_keys_never_reach_disk(tmp_path):
    """Acceptance: no key appears in any file the fetch or probe writes."""
    fetcher = responder({"fixtures": fd_body(), "elo": elo_body(), "odds": odds_body()})
    outcomes = fetch_all(data_dir=tmp_path, fetcher=fetcher, env=KEYS, now=NOW)
    write_probe_report(outcomes, tmp_path)
    written = "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())
    assert "fd-secret-token" not in written and "odds-secret-key" not in written
    assert "apiKey=REDACTED" in written


def test_redact_and_uefa_hosts_are_refused():
    assert "s3cret" not in http.redact("https://x.test/odds?regions=eu&apiKey=s3cret")
    for url in ("https://gaming.uefa.com/en/uclfantasy/x", "https://www.uefa.com/y"):
        with pytest.raises(http.SourceError, match="never fetched automatically"):
            http.get(url)
    hosts = [urlsplit(s.build_url(DAY, "k")).hostname for s in SOURCES.values()]
    assert hosts == ["api.football-data.org", "api.clubelo.com", "api.the-odds-api.com"]


def test_unknown_source_is_refused(tmp_path):
    with pytest.raises(ValueError):
        fetch_all(["scores"], data_dir=tmp_path)


def test_probe_report_lists_fields_and_results(tmp_path):
    fetcher = responder(
        {
            "fixtures": fd_body(),
            "elo": http.SourceError("HTTP 503 from api.clubelo.com: down"),
            "odds": odds_body(),
        }
    )
    outcomes = fetch_all(
        data_dir=tmp_path, fetcher=fetcher, env={"FOOTBALL_DATA_TOKEN": "t"}, now=NOW
    )
    report = write_probe_report(outcomes, tmp_path).read_text()
    assert "| football-data.org" in report and "| ok |" in report
    assert "failed" in report and "HTTP 503" in report
    assert "skipped" in report and "ODDS_API_KEY" in report
    assert (
        "Fields returned: awayTeam, homeTeam, id, matchday, score, stage, status, utcDate" in report
    )
    assert (tmp_path / "probe" / "fixtures-sample.json").exists()


# -- club names ----------------------------------------------------------------------


def test_normalise():
    assert normalise("FC Bayern München") == normalise("Bayern Munchen") == "bayern munchen"
    assert normalise("Manchester United FC") == "manchester united"


def test_unmatched_club_names_are_reported_not_guessed(tmp_path):
    fixtures = fd_body(144, home="Home Club 1 FC", away="Away Club 1 FC")
    elo = "Rank,Club,Country,Level,Elo,From,To\n" + "\n".join(
        f"{i},{name},ENG,1,1800,2026-11-10,2026-11-14"
        for i, name in enumerate(["Home Club 1"] + [f"Other {n}" for n in range(320)])
    )
    fetch_all(
        data_dir=tmp_path,
        env=KEYS,
        now=NOW,
        fetcher=responder({"fixtures": fixtures, "elo": elo, "odds": odds_body()}),
    )
    report = match_report(tmp_path)
    assert report["reference_clubs"] == 2
    assert report["elo"]["fixture_clubs_without_rating"] == ["Away Club 1 FC"]
    assert report["odds"]["unmatched_names"] == []

    (tmp_path / "club_aliases.yaml").write_text('clubs:\n  "Away Club 1 FC": ["Other 7"]\n')
    assert match_report(tmp_path)["elo"]["fixture_clubs_without_rating"] == []


def test_fixtures_command_without_data_says_unavailable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("uclfa.ingest.run.DATA_DIR", tmp_path)
    assert cli.main(["fixtures", "--matchday", "5"]) == 1
    assert "unavailable" in capsys.readouterr().out


def test_fixtures_command_checks_the_deadline(tmp_path, monkeypatch, capsys):
    fetch_source(
        SOURCES["fixtures"],
        data_dir=tmp_path,
        fetcher=responder({"fixtures": fd_body()}),
        env=KEYS,
        now=NOW,
    )
    monkeypatch.setattr("uclfa.ingest.run.DATA_DIR", tmp_path)
    assert cli.main(["fixtures", "--matchday", "5"]) == 0
    out = capsys.readouterr().out
    assert "Tue 24 Nov 19:45" in out and "matches the deadline recorded from the game" in out
