"""Match model (Release 2 Phase B). Every output is an analyst estimate.

Real-data tests use a pinned copy of the 15 November 2026 snapshots in tests/data/md5, so
they do not change as the daily fetch adds files.
"""

from __future__ import annotations

import asyncio
import json
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp.client import Client

from uclfa import cli
from uclfa.mcp_server import build_server
from uclfa.model.match import (
    MarketInput,
    fit_match,
    load_settings,
    main_half_line,
    margin,
    remove_margin,
    scoreline_grid,
)
from uclfa.service import match_outlook_view

MD5 = Path(__file__).parent / "data" / "md5"
NOW = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def settings():
    return load_settings()


@pytest.fixture(scope="module")
def outlook(settings):
    return match_outlook_view(5, data_dir=MD5, settings=settings, now=NOW)


def fair_odds(grid, line=2.5):
    over = grid.over(line)
    return [1 / grid.home_win, 1 / grid.draw, 1 / grid.away_win], [1 / over, 1 / (1 - over)]


# -- margin removal ------------------------------------------------------------------


def test_margin_removal_sums_to_one_and_keeps_a_fair_book():
    probs = remove_margin([1.395, 4.925, 7.45])
    assert math.isclose(sum(probs), 1.0, abs_tol=1e-12)
    assert probs[0] > probs[1] > probs[2]
    assert remove_margin([2.0, 2.0]) == pytest.approx([0.5, 0.5])
    assert remove_margin([2.0, 4.0, 4.0]) == pytest.approx([0.5, 0.25, 0.25])
    assert margin([2.0, 2.0]) == pytest.approx(0.0)


def test_margin_removal_shrinks_longshots_more_than_favourites():
    """The power method corrects the favourite-longshot bias of proportional scaling."""
    odds = [1.2, 7.0, 13.0]
    proportional = [(1 / o) / sum(1 / x for x in odds) for o in odds]
    power = remove_margin(odds)
    assert power[0] > proportional[0] and power[2] < proportional[2]


def test_margin_removal_refuses_impossible_odds():
    for bad in ([1.0, 3.0], [0.0, 2.0], [2.0], [-1.5, 2.5]):
        with pytest.raises(ValueError):
            remove_margin(bad)


# -- grid and fit --------------------------------------------------------------------


def test_grid_is_consistent(settings):
    g = scoreline_grid(1.7, 1.1, settings.low_score_correction, settings.max_goals)
    assert math.isclose(sum(map(sum, g.cells)), 1.0, abs_tol=1e-12)
    assert math.isclose(g.home_win + g.draw + g.away_win, 1.0, abs_tol=1e-12)
    assert g.home_clean_sheet == pytest.approx(g.prob(lambda i, j: j == 0))
    assert g.away_clean_sheet == pytest.approx(g.prob(lambda i, j: i == 0))
    assert g.truncated_mass < 1e-9
    heavy = scoreline_grid(4.3, 0.8, settings.low_score_correction, settings.max_goals)
    assert heavy.truncated_mass < 1e-8
    assert g.expected_home_goals == pytest.approx(1.7, abs=0.01)


def test_low_score_correction_raises_draws_and_off_is_plain_poisson():
    plain = scoreline_grid(1.3, 1.1, 0.0, 10)
    corrected = scoreline_grid(1.3, 1.1, -0.05, 10)
    assert corrected.draw > plain.draw
    assert plain.cells[0][0] == pytest.approx(math.exp(-2.4), rel=1e-6)


@pytest.mark.parametrize("home, away", [(1.8, 0.9), (0.6, 2.9), (1.3, 1.3), (3.4, 0.5)])
def test_round_trip_recovers_the_goal_rates(settings, home, away):
    """Known rates -> fair odds -> fitted rates within 0.01."""
    grid = scoreline_grid(home, away, settings.low_score_correction, settings.max_goals)
    result, goals = fair_odds(grid)
    fit = fit_match(MarketInput(*result, 20, 2.5, *goals, 20), settings)
    assert fit.home_rate == pytest.approx(home, abs=0.01)
    assert fit.away_rate == pytest.approx(away, abs=0.01)
    assert fit.max_error < 1e-4 and fit.confidence == "normal"


def test_without_a_half_goal_line_the_fit_uses_the_result_only_and_says_so(settings):
    grid = scoreline_grid(1.6, 1.0, settings.low_score_correction, settings.max_goals)
    result, _ = fair_odds(grid)
    quarter = fit_match(MarketInput(*result, 20, 3.25, 1.9, 1.9, 10), settings)
    assert quarter.goals_line is None and "over_3.25" not in quarter.market
    assert quarter.confidence == "low" and "not a half-goal line" in quarter.reasons[0]
    none = fit_match(MarketInput(*result, 20), settings)
    assert "no goals line" in none.reasons[0]


def test_thin_markets_are_low_confidence(settings):
    grid = scoreline_grid(1.6, 1.0, settings.low_score_correction, settings.max_goals)
    result, goals = fair_odds(grid)
    fit = fit_match(MarketInput(*result, 2, 2.5, *goals, 1), settings)
    assert fit.confidence == "low" and len(fit.reasons) == 2


def test_main_line_is_the_most_quoted_half_line():
    record = {
        "total_line": 3.25,
        "totals": [
            {"line": 2.5, "bookmakers": 3, "over_price": 1.5, "under_price": 2.6},
            {"line": 3.25, "bookmakers": 9, "over_price": 1.9, "under_price": 1.9},
            {"line": 3.5, "bookmakers": 4, "over_price": 2.1, "under_price": 1.7},
        ],
    }
    line, over, under, books, note = main_half_line(record)
    assert (line, over, under, books) == (3.5, 2.1, 1.7, 4) and "3.25" in note
    assert main_half_line({"total_line": 3.25, "totals": []})[1] is None
    old = main_half_line({"total_line": 2.5, "over_price": 1.8, "under_price": 2.0})
    assert old[:3] == (2.5, 1.8, 2.0) and "old snapshot" in old[4]


# -- real Matchday 5 data ------------------------------------------------------------


def test_every_matchday_5_match_is_fitted_from_real_odds(outlook):
    """Acceptance 2: all 18 matches listed with estimates, odds age and bookmaker count."""
    assert outlook["tag"] == "analyst_estimate"
    assert (outlook["fitted"], outlook["unavailable"]) == (18, 0)
    assert outlook["odds_not_matched_to_a_fixture"] == []
    assert outlook["odds_age_hours"] is not None
    for m in outlook["matches"]:
        assert m["tag"] == "analyst_estimate"
        assert m["bookmakers"]["result"] >= 5 and m["goals_line"] is not None
        assert 0 < m["clean_sheet"]["home"] < 1 and 0 < m["expected_goals"]["away"] < 6


def test_model_reproduces_the_market_or_flags_the_match(outlook, settings):
    """Acceptance 3: within one percentage point of every market probability, or flagged
    as low confidence with the size of the miss."""
    for m in outlook["matches"]:
        if m["max_error_points"] > settings.fit_tolerance * 100:
            assert m["confidence"] == "low"
            assert any("misses a market probability" in r for r in m["reasons"])
        for key, value in m["market"].items():
            assert abs(m["model"][key] - value) <= 0.012, (m["home"], key)
    fitted_within = [m for m in outlook["matches"] if m["max_error_points"] <= 1.0]
    assert len(fitted_within) >= 15


def test_known_match_values(outlook):
    """Pins one real fit so a change in the method shows up in review."""
    m = next(m for m in outlook["matches"] if m["home"] == "Arsenal FC")
    assert m["away"] == "Borussia Dortmund" and m["goals_line"] == 2.5
    assert m["expected_goals"] == {"home": 2.26, "away": 0.8}
    assert m["clean_sheet"]["home"] == pytest.approx(0.45, abs=0.01)
    assert m["kickoff_athens"] == "Tue 24 Nov 22:00"


# -- missing data --------------------------------------------------------------------


def copy_md5(tmp_path: Path) -> Path:
    shutil.copytree(MD5, tmp_path / "data")
    return tmp_path / "data"


def rewrite_odds(data: Path, change) -> None:
    path = next((data / "snapshots" / "odds").glob("*.json"))
    snapshot = json.loads(path.read_text("utf-8"))
    change(snapshot["records"])
    path.write_text(json.dumps(snapshot), "utf-8")


def test_matches_without_odds_are_unavailable_not_guessed(tmp_path, settings):
    data = copy_md5(tmp_path)
    rewrite_odds(data, lambda records: records.clear())
    view = match_outlook_view(5, data_dir=data, settings=settings, now=NOW)
    assert view["tag"] == "unavailable" and view["fitted"] == 0
    assert all(m["reason"] == "no odds listed for this match" for m in view["matches"])
    assert all("expected_goals" not in m for m in view["matches"])


def test_reversed_unknown_and_broken_odds_are_reported(tmp_path, settings):
    data = copy_md5(tmp_path)

    def change(records):
        first, second, third = records[0], records[1], records[2]
        first["home"], first["away"] = first["away"], first["home"]
        second["home"] = "Nowhere United"
        third["home_price"] = 1.0

    rewrite_odds(data, change)
    view = match_outlook_view(5, data_dir=data, settings=settings, now=NOW)
    reasons = [m["reason"] for m in view["matches"] if m["status"] == "unavailable"]
    assert view["unavailable"] == 3 and view["fitted"] == 15
    assert any("other way round" in r for r in reasons)
    assert any(r.startswith("odds unusable") for r in reasons)
    assert any("Nowhere United" in s for s in view["odds_not_matched_to_a_fixture"])


def test_no_fixtures_for_the_matchday(settings):
    view = match_outlook_view(12, data_dir=MD5, settings=settings, now=NOW)
    assert view["tag"] == "unavailable" and "No fixtures" in view["note"]


# -- command line and tool server ----------------------------------------------------


def test_outlook_command_labels_its_output(monkeypatch, capsys):
    monkeypatch.setattr("uclfa.ingest.run.DATA_DIR", MD5)
    assert cli.main(["outlook", "--matchday", "5"]) == 0
    out = capsys.readouterr().out
    assert "ANALYST ESTIMATE" in out and "Arsenal FC v Borussia Dortmund" in out


def test_tool_server_returns_the_outlook_tagged(tmp_path):
    server = build_server(tmp_path / "none.db", data_dir=MD5)

    async def run():
        async with Client(server) as client:
            result = await client.call_tool("match_outlook", {"matchday": 5})
            assert not result.is_error, result.content
            return result.structured_content

    view = asyncio.run(run())
    assert view["fitted"] == 18 and view["tag"] == "analyst_estimate"
    assert {m["tag"] for m in view["matches"]} == {"analyst_estimate"}
