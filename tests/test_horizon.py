"""Choices over the coming matchdays (Release 2 Phase E)."""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uclfa.horizon import best_lineup, evaluate_move, free_transfers_at
from uclfa.model.player import PlayerInputs
from uclfa.optimize import Candidate, OptimizerSettings, optimise_horizon
from uclfa.rules import Chip, Player, Position, Role, Squad, SquadSlot
from uclfa.rules.validators import next_free_transfers, validate_lineup
from uclfa.service import match_outlook_view, team_ratings

MD5 = Path(__file__).parent / "data" / "md5"
NOW = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)
LAYOUT = [("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]
S = OptimizerSettings(bench_weight=0.0, max_transfers=2, wildcard_margin=8.0)


@pytest.fixture()
def rules(confirm):
    return confirm(selling_value="current_price")


@dataclass
class State:
    squad: Squad
    bank: float
    free_transfers: int | None
    chips_used: frozenset
    matchday: int = 5
    label: str = "wildcard"


def squad_players() -> list[tuple[str, Position]]:
    return [(f"{p}{j}", Position(p)) for p, k in LAYOUT for j in range(k)]


def state_of(players: list[tuple[str, Position]], bank: float = 1.0) -> State:
    slots = tuple(
        SquadSlot(player=Player(n, n, f"Club{k}", pos, 5.0), role=Role.BENCH)
        for k, (n, pos) in enumerate(players)
    )
    return State(Squad(slots), bank, None, frozenset({Chip.WILDCARD, Chip.LIMITLESS}))


# -- best lineup ---------------------------------------------------------------------


def brute_best(players, xp) -> float:
    best = 0.0
    for eleven in itertools.combinations(players, 11):
        count = {p: sum(1 for _, q in eleven if q is p) for p in Position}
        if count[Position.GK] != 1 or count[Position.DEF] < 3 or count[Position.MID] < 2:
            continue
        if count[Position.FWD] < 1:
            continue
        pts = [xp[n] for n, _ in eleven]
        best = max(best, sum(pts) + max(pts))
    return best


def test_best_lineup_matches_brute_force_and_passes_the_rules(rules):
    """[lineup] The enumerated best eleven equals an exhaustive search and is legal."""
    players = squad_players()
    rng = random.Random(11)
    for _ in range(3):
        xp = {n: round(rng.uniform(0, 10), 2) for n, _ in players}
        lu = best_lineup(players, xp, rules)
        assert lu.points == pytest.approx(brute_best(players, xp))
        slots = tuple(
            SquadSlot(
                player=Player(n, n, f"C{k}", pos, 5.0),
                role=Role.STARTER if n in lu.starters else Role.BENCH,
                bench_order=None
                if n in lu.starters or pos is Position.GK
                else [m for m, q in players if m not in lu.starters and q is not Position.GK].index(
                    n
                )
                + 1,
                is_captain=n == lu.captain,
            )
            for k, (n, pos) in enumerate(players)
        )
        assert str(validate_lineup(Squad(slots), rules).status) == "valid"


def test_unknown_players_count_as_zero_and_are_named(rules):
    players = squad_players()
    xp = {n: 5.0 for n, _ in players}
    xp["FWD0"] = None
    lu = best_lineup(players, xp, rules)
    assert "FWD0" not in lu.starters and lu.unknown == ["FWD0"]


# -- free transfers ahead ------------------------------------------------------------


def test_free_transfers_after_a_wildcard_follow_the_rules_engine(rules):
    """[free_transfers] No carry-over into the matchday after a chip; carry later."""
    st = state_of(squad_players())
    assert free_transfers_at(st, 6, rules) == next_free_transfers(
        5, None, 0, rules, chip_played=True
    )
    md6 = free_transfers_at(st, 6, rules)
    assert free_transfers_at(st, 7, rules) == next_free_transfers(6, md6, 0, rules)
    assert free_transfers_at(st, 5, rules) is None  # its own matchday: as saved


# -- evaluating a move ---------------------------------------------------------------


def test_evaluation_by_hand(rules):
    """Swapping a bench player gains nothing; a better starter gains the difference."""
    players = squad_players()
    st = state_of(players)
    xp = {n: 4.0 for n, _ in players}
    xp["FWD0"], xp["DEF4"] = 6.0, 1.0
    xp.update({"NewFWD": 9.0, "NewDEF": 1.5})
    by_md = {6: dict(xp), 7: dict(xp)}
    fwd = {"name": "NewFWD", "club": "X", "position": "FWD", "price": 5.0}
    ev = evaluate_move(st, ["FWD1"], [fwd], 6, by_md, {6: "odds", 7: "projection"}, rules)
    # NewFWD (9.0) becomes captain instead of FWD0 (6.0): +5 starter, +3 captain extra.
    assert ev.status == "valid" and ev.gain_by_matchday == [8.0, 8.0] and ev.hit_points == 0
    bench = {"name": "NewDEF", "club": "Y", "position": "DEF", "price": 5.0}
    ev2 = evaluate_move(st, ["DEF4"], [bench], 6, by_md, {6: "odds", 7: "odds"}, rules)
    assert ev2.net_gain == 0.0  # a bench defender changes nothing
    with pytest.raises(ValueError, match="Not in the squad"):
        evaluate_move(st, ["Nobody"], [bench], 6, by_md, {}, rules)


# -- the goalkeeper example: good next week, poor after --------------------------------


def test_stretch_optimizer_prefers_the_steady_player(rules):
    """Patrick's example: a keeper who is best next matchday but poor after should lose
    to one who is good across the stretch."""
    players = squad_players()
    st = state_of(players, bank=2.0)
    owned = [
        Candidate(n, f"Club{k}", pos, 5.0, 0.0, True, True, "entered")
        for k, (n, pos) in enumerate(players)
    ]
    flash = Candidate("FlashGK", "F", Position.GK, 5.0, 0.0, False, True, "third_party")
    steady = Candidate("SteadyGK", "G", Position.GK, 5.0, 0.0, False, True, "third_party")
    base = {n: 4.0 for n, _ in players}
    by_md = {
        6: {**base, "FlashGK": 9.0, "SteadyGK": 6.0},
        7: {**base, "FlashGK": 1.0, "SteadyGK": 6.0},
        8: {**base, "FlashGK": 1.0, "SteadyGK": 6.0},
    }
    result = optimise_horizon(owned + [flash, steady], by_md, st, rules, S, free_transfers=1)
    one = next(p for p in result["plans"] if p["label"] == "1 transfer(s)")
    assert one["status"] == "valid" and one["transfers_in"] == ["SteadyGK"]
    # Ten outfield players at 4.0, SteadyGK 6.0, and he is also the best captain choice.
    assert one["points_by_matchday"] == [pytest.approx(x) for x in (52.0, 52.0, 52.0)]
    only_next = optimise_horizon(owned + [flash, steady], {6: by_md[6]}, st, rules, S, 1)
    first = next(p for p in only_next["plans"] if p["label"] == "1 transfer(s)")
    assert first["transfers_in"] == ["FlashGK"]  # judged on one matchday, it would differ


# -- projected matches ---------------------------------------------------------------


def test_matches_without_odds_are_projected_and_marked():
    ratings = team_ratings(MD5)
    assert ratings is not None and ratings.matches_used == 72 + 18
    md6 = match_outlook_view(6, data_dir=MD5, now=NOW, ratings=ratings)
    assert md6["projected"] == 18 and md6["fitted"] == 0
    assert {m["source"] for m in md6["matches"]} == {"projection"}
    assert all(m["tag"] == "analyst_estimate" for m in md6["matches"])
    md5 = match_outlook_view(5, data_dir=MD5, now=NOW, ratings=ratings)
    assert md5["fitted"] == 18 and {m["source"] for m in md5["matches"]} == {"odds"}
    bare = match_outlook_view(6, data_dir=MD5, now=NOW)
    assert bare["tag"] == "unavailable"


def test_team_news_applies_to_its_matchdays_only():
    p = PlayerInputs(
        name="X",
        club="Y",
        position="FWD",
        start_prob=0.9,
        start_prob_by_matchday={5: 0.0, 6: 0.0},
        sub_prob_by_matchday={5: 0.0},
    )
    assert p.for_matchday(5).start_prob == 0.0 and p.for_matchday(6).start_prob == 0.0
    assert p.for_matchday(7).start_prob == 0.9
