"""Player expected points (Release 2 Phase C). Every output is an analyst estimate."""

from __future__ import annotations

import math
import random
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uclfa import cli
from uclfa.model.player import (
    PlayerInputs,
    TeamContext,
    _expected_blocks,
    expected_points,
    load_player_settings,
)
from uclfa.rules import Position
from uclfa.rules.scoring import MatchEvents, score_player
from uclfa.service import player_points_view

MD5 = Path(__file__).parent / "data" / "md5"
NOW = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)
TEAM = TeamContext(goals_for=2.0, goals_against=1.0, clean_sheet=0.36)


@pytest.fixture(scope="module")
def settings():
    return load_player_settings()


def player(position="MID", **over):
    base = dict(
        name="Test Player",
        club="Arsenal",
        position=position,
        start_prob=1.0,
        p60_if_start=1.0,
        minutes_if_start=90,
        goal_share=0.0,
        assist_share=0.0,
        recoveries_p90=0.0,
        saves_p90=0.0 if position == "GK" else None,
    )
    return PlayerInputs(**{**base, **over})


def test_hand_worked_forward(rules, settings):
    """Certain starter, 90 minutes, a quarter of 2.0 team goals, a tenth of the assists:
    1 + 1 + 2.0*0.25*4 + 2.0*0.10*3 = 4.6."""
    pts = expected_points(player("FWD", goal_share=0.25, assist_share=0.10), TEAM, rules, settings)
    assert pts.expected == pytest.approx(4.6)
    assert pts.components["goals"] == pytest.approx(2.0) and pts.plays_prob == 1.0


def test_hand_worked_defender_clean_sheet_and_goals_conceded(rules, settings):
    """Appearance 1 + sixty 1 + clean sheet 4*0.36 - E[floor(N/2)], N ~ Poisson(1.0)."""
    conceded = sum((n // 2) * math.exp(-1) / math.factorial(n) for n in range(30))
    pts = expected_points(player("DEF"), TEAM, rules, settings)
    assert pts.components["clean_sheet"] == pytest.approx(1.44)
    assert pts.components["goals_conceded"] == pytest.approx(-conceded)
    assert pts.expected == pytest.approx(2 + 1.44 - conceded)


def test_position_decides_goal_and_clean_sheet_points(rules, settings):
    by_pos = {
        pos: expected_points(player(pos, goal_share=0.5), TEAM, rules, settings).components
        for pos in ("GK", "DEF", "MID", "FWD")
    }
    assert [by_pos[p]["goals"] for p in ("GK", "DEF", "MID", "FWD")] == pytest.approx([6, 6, 5, 4])
    assert by_pos["MID"]["clean_sheet"] == pytest.approx(0.36)
    assert "clean_sheet" not in by_pos["FWD"] and "goals_conceded" not in by_pos["MID"]
    assert "saves" in by_pos["GK"] and "saves" not in by_pos["DEF"]


def test_blocks_of_three_and_two():
    assert _expected_blocks(0.0, 3, 40) == 0
    exact = sum((n // 3) * math.exp(-6) * 6**n / math.factorial(n) for n in range(60))
    assert _expected_blocks(6.0, 3, 40) == pytest.approx(exact, abs=1e-9)
    assert _expected_blocks(6.0, 3, 40) < 6 / 3  # flooring always costs something


def test_start_chance_and_substitute_appearances(rules, settings):
    sure = expected_points(player("FWD", goal_share=0.3), TEAM, rules, settings)
    doubt = expected_points(player("FWD", goal_share=0.3, start_prob=0.5), TEAM, rules, settings)
    assert doubt.expected == pytest.approx(sure.expected / 2)
    assert doubt.if_starts == pytest.approx(sure.expected) and doubt.plays_prob == 0.5
    bench = expected_points(
        player("FWD", goal_share=0.3, start_prob=0.0, sub_prob=1.0, minutes_if_sub=30),
        TEAM,
        rules,
        settings,
    )
    # A substitute: appearance point and a third of the goal expectation, no 60-minute point.
    assert bench.expected == pytest.approx(1 + 2.0 * 0.3 * (30 / 90) * 4)


def test_leaving_before_sixty_loses_the_point_and_the_clean_sheet(rules, settings):
    early = expected_points(
        player("DEF", p60_if_start=0.0, minutes_if_start=45), TEAM, rules, settings
    )
    assert "clean_sheet" not in early.components and early.components["sixty_minutes"] == 0
    part = expected_points(
        player("DEF", p60_if_start=0.8, minutes_if_start=80), TEAM, rules, settings
    )
    # Reaching 60 in 80% of games with an 80-minute average implies 88.75 when he does.
    assert part.components["clean_sheet"] == pytest.approx(4 * 0.8 * 0.36 ** (88.75 / 90))


def test_missing_inputs_give_no_number(rules, settings):
    with pytest.raises(ValueError, match="start_prob"):
        expected_points(
            PlayerInputs(name="X", club="Arsenal", position="DEF"), TEAM, rules, settings
        )
    keeper = player("GK", saves_p90=None)
    assert keeper.missing() == ["saves_p90"]
    pts = expected_points(player("MID"), TEAM, rules, settings)
    assert any("yellow cards left out" in n for n in pts.notes)
    carded = expected_points(player("MID", cards_p90=0.2), TEAM, rules, settings)
    assert carded.components["yellow_cards"] == pytest.approx(-0.2)


def _poisson(rng: random.Random, rate: float) -> int:
    n, p, limit = 0, 1.0, math.exp(-rate)
    while True:
        p *= rng.random()
        if p <= limit:
            return n
        n += 1


@pytest.mark.parametrize("position", ["GK", "DEF", "MID", "FWD"])
def test_model_agrees_with_the_scoring_engine_in_simulation(rules, settings, position):
    """Simulate full matches under the model's assumptions, score each with the rules
    engine, and compare the average with the formula. Ties the model to the scoring table."""
    p = player(
        position,
        goal_share=0.2,
        assist_share=0.15,
        recoveries_p90=6.0,
        saves_p90=3.0 if position == "GK" else None,
    )
    team = TeamContext(goals_for=1.8, goals_against=1.2, clean_sheet=math.exp(-1.2))
    rng, total, runs = random.Random(7), 0, 40000
    for _ in range(runs):
        conceded = _poisson(rng, team.goals_against)
        events = MatchEvents(
            minutes_played=90,
            goals=_poisson(rng, team.goals_for * p.goal_share),
            assists=_poisson(rng, team.goals_for * p.assist_share),
            balls_recovered=_poisson(rng, p.recoveries_p90),
            saves=_poisson(rng, p.saves_p90) if position == "GK" else 0,
            goals_conceded_on_pitch=conceded,
        )
        total += score_player(Position(position), events, rules).total
    assert expected_points(p, team, rules, settings).expected == pytest.approx(
        total / runs, abs=0.06
    )


# -- view and command ----------------------------------------------------------------


def pool_dir(tmp_path: Path, body: str) -> Path:
    shutil.copytree(MD5, tmp_path / "data")
    (tmp_path / "data" / "players").mkdir()
    (tmp_path / "data" / "players" / "pool.yaml").write_text(body, encoding="utf-8")
    return tmp_path / "data"


POOL = """
as_of: "2026-11-15"
players:
  - {name: "Complete Defender", club: "Arsenal", position: DEF, price: 5.0, price_tag: third_party,
     price_source: "example.test", price_date: "2026-11-15", start_prob: 0.9, p60_if_start: 0.95,
     minutes_if_start: 88, goal_share: 0.03, assist_share: 0.04, recoveries_p90: 6,
     sources: ["test"]}
  - {name: "No Inputs", club: "Arsenal", position: MID, price: 6.0, price_tag: entered}
  - {name: "Unknown Club", club: "Nowhere United", position: FWD}
"""


def test_view_tags_everything_and_never_fills_gaps(tmp_path, rules):
    data = pool_dir(tmp_path, POOL)
    view = player_points_view(5, rules, data_dir=data, now=NOW, squad_names={"No Inputs"})
    assert view["tag"] == "analyst_estimate"
    assert (view["estimated"], view["unavailable"]) == (1, 2)
    done, gap, lost = (
        next(r for r in view["players"] if r["name"] == n)
        for n in ("Complete Defender", "No Inputs", "Unknown Club")
    )
    assert done["tag"] == "analyst_estimate" and done["price"]["tag"] == "third_party"
    assert done["opponent"] == "Borussia Dortmund (H)" and 3 < done["expected_points"] < 8
    assert done["components"]["clean_sheet"] > 1.0 and not done["in_squad"]
    assert gap["expected_points"] is None and "missing inputs" in gap["reason"]
    assert gap["in_squad"] and gap["price"] == {"value": 6.0, "tag": "entered"}
    assert "not matched" in lost["reason"] and lost["price"]["tag"] == "unavailable"


def test_view_without_a_pool_is_unavailable(rules):
    assert player_points_view(5, rules, data_dir=MD5, now=NOW)["tag"] == "unavailable"


def test_points_command_labels_its_output(tmp_path, monkeypatch, capsys):
    data = pool_dir(tmp_path, POOL)
    monkeypatch.setattr("uclfa.ingest.run.DATA_DIR", data)
    monkeypatch.setenv("UCLFA_DB", str(tmp_path / "none.db"))
    assert cli.main(["points", "--matchday", "5"]) == 0
    out = capsys.readouterr().out
    assert "ANALYST ESTIMATE" in out and "Complete Defender" in out and "5.0*" in out
    assert "unavailable: missing inputs" in out
