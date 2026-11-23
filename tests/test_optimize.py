"""Squad optimizer (Release 2 Phase D). Plans are analyst estimates, checked by the rules
engine; a brute-force search confirms the solver on small cases."""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import pytest

from uclfa.optimize import Candidate, OptimizerSettings, optimise
from uclfa.rules import Player, Position, Role, Squad, SquadSlot

S = OptimizerSettings(bench_weight=0.0, max_transfers=2, wildcard_margin=8.0)
LAYOUT = [("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)]


@pytest.fixture()
def rules(confirm):
    """Selling value confirmed as the current price, as Patrick confirmed in the game.
    Without it the rules engine blocks every sale, which test_sales_block_without_it shows."""
    return confirm(selling_value="current_price")


@dataclass
class State:
    squad: Squad
    bank: float
    free_transfers: int | None
    chips_used: frozenset


def owned_candidates() -> list[Candidate]:
    out, k = [], 0
    for pos, count in LAYOUT:
        for j in range(count):
            k += 1
            out.append(
                Candidate(
                    name=f"{pos}{j}",
                    club=f"Club{k}",
                    position=Position(pos),
                    price=5.0,
                    xp=float(2 + (k * 7) % 5),
                    owned=True,
                    known=True,
                    price_tag="entered",
                )
            )
    return out


def state_for(cands: list[Candidate], bank: float = 1.0, free: int = 1) -> State:
    slots = []
    for c in cands:
        if c.owned:
            starter = len(slots) < 11 and c.position is not Position.GK or c.name == "GK0"
            slots.append(
                SquadSlot(
                    player=Player(c.name, c.name, c.club, c.position, c.price),
                    role=Role.STARTER if starter else Role.BENCH,
                )
            )
    return State(Squad(tuple(slots)), bank, free, frozenset())


def best_lineup(squad: list[Candidate]) -> float:
    """Independent check: best XI and captain by enumerating formations."""
    by_pos = {p: sorted((c.xp for c in squad if c.position is p), reverse=True) for p in Position}
    best = 0.0
    for d, m, f in itertools.product(range(3, 6), range(2, 6), range(1, 4)):
        if d + m + f != 10:
            continue
        xi = [by_pos[Position.GK][0], *by_pos[Position.DEF][:d], *by_pos[Position.MID][:m]]
        xi += by_pos[Position.FWD][:f]
        best = max(best, sum(xi) + max(xi))
    return best


def test_zero_transfers_keeps_the_squad_and_finds_the_best_lineup(rules):
    cands = owned_candidates()
    result = optimise(cands, state_for(cands), 5, rules, S)
    plan = result["plans"][0]
    assert plan.label == "0 transfer(s)" and plan.status == "valid"
    assert plan.transfers_in == [] and plan.hit_points == 0
    assert plan.expected_points == pytest.approx(best_lineup(cands))


def test_one_transfer_matches_brute_force(rules):
    owned = owned_candidates()
    market = [
        Candidate("StarFWD", "ClubX", Position.FWD, 9.0, 9.5, False, True, "third_party"),
        Candidate("CheapMID", "ClubY", Position.MID, 4.0, 6.5, False, True, "third_party"),
        Candidate("GoodDEF", "Club1", Position.DEF, 5.5, 7.0, False, True, "third_party"),
        Candidate("PriceyGK", "ClubZ", Position.GK, 7.0, 9.0, False, True, "third_party"),
    ]
    cands, bank = owned + market, 1.0
    brute = best_lineup(owned)
    for out, new in itertools.product(owned, market):
        squad = [c for c in owned if c is not out] + [new]
        if out.position is not new.position or new.price > bank + out.price:
            continue
        if max(sum(c.club == club for c in squad) for club in {c.club for c in squad}) > 3:
            continue
        brute = max(brute, best_lineup(squad))
    result = optimise(cands, state_for(cands, bank=bank), 5, rules, S)
    plan = next(p for p in result["plans"] if p.label == "1 transfer(s)")
    assert plan.status == "valid" and plan.expected_points == pytest.approx(brute)


def test_budget_hits_club_limit_and_unknown_players(rules):
    owned = owned_candidates()
    market = [
        Candidate("TooDear", "ClubX", Position.FWD, 20.0, 50.0, False, True, "third_party"),
        Candidate("Unknown", "ClubY", Position.MID, 4.0, 0.0, False, False, "third_party"),
        Candidate("A", "Club1", Position.MID, 5.0, 9.0, False, True, "third_party"),
        Candidate("B", "Club1", Position.MID, 5.0, 9.0, False, True, "third_party"),
        Candidate("C", "Club1", Position.MID, 5.0, 9.0, False, True, "third_party"),
    ]
    cands = owned + market
    result = optimise(cands, state_for(cands, free=1), 5, rules, S)
    for plan in result["plans"]:
        assert plan.status == "valid", plan.messages
        assert "TooDear" not in plan.transfers_in and "Unknown" not in plan.transfers_in
        chosen = [c for c in cands if c.name in plan.starters + plan.bench]
        assert len(chosen) == 15
        assert max(sum(c.club == k for c in chosen) for k in {c.club for c in chosen}) <= 3
    two = next(p for p in result["plans"] if p.label == "2 transfer(s)")
    assert two.hit_points == 4 and two.net_points == pytest.approx(two.expected_points - 4)


def test_wildcard_is_recommended_only_past_the_margin(rules):
    owned = owned_candidates()
    cands = owned + [
        Candidate(f"New{k}", f"N{k}", Position(p), 4.0, 12.0, False, True, "third_party")
        for k, p in enumerate(["DEF", "DEF", "MID", "MID", "FWD"])
    ]
    result = optimise(cands, state_for(cands), 5, rules, S)
    wildcard = next(p for p in result["plans"] if p.label == "Wildcard")
    assert wildcard.hit_points == 0 and wildcard.status == "valid"
    assert result["recommended"] == "Wildcard"
    strict = OptimizerSettings(bench_weight=0.0, max_transfers=2, wildcard_margin=1000)
    assert optimise(cands, state_for(cands), 5, rules, strict)["recommended"] != "Wildcard"


def test_sales_block_without_the_selling_value_rule():
    """[selling_value] An unconfirmed rule blocks a plan; it is never assumed."""
    from uclfa.rules import load_rules

    unconfirmed = load_rules(confirmations_path=None)
    owned = owned_candidates()
    cands = owned + [Candidate("X", "N", Position.FWD, 4.0, 12.0, False, True, "third_party")]
    result = optimise(cands, state_for(cands), 5, unconfirmed, S)
    one = next(p for p in result["plans"] if p.label == "1 transfer(s)")
    assert one.status == "blocked" and result["recommended"] == "0 transfer(s)"
