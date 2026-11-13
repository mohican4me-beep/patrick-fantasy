"""Squad and lineup validation."""

import random
from dataclasses import replace

from uclfa.rules import Position, Role, Squad, validate_lineup, validate_squad

from .conftest import change, make_squad, move_to_club


def test_reference_squad_is_legal(rules, squad):
    assert validate_squad(squad, 5, rules).ok
    assert validate_lineup(squad, rules).ok


def test_squad_size(rules, squad):
    """[squad_composition] Fourteen players is not a squad."""
    short = Squad(squad.slots[:-1])
    assert "squad_size" in validate_squad(short, 5, rules).codes()


def test_position_quota_names_the_rule(rules, squad):
    """[squad_composition] A sixth midfielder in place of a forward breaks two quotas."""
    slot = squad.slot("f3")
    wrong = squad.with_slot(replace(slot, player=replace(slot.player, position=Position.MID)))
    result = validate_squad(wrong, 5, rules)
    assert result.status == "invalid"
    assert {v.rule_id for v in result.violations} == {"squad_composition"}
    assert any("MID" in v.message for v in result.violations)
    assert any("FWD" in v.message for v in result.violations)


def test_duplicate_player(rules, squad):
    duplicated = Squad(
        squad.slots[:-1] + (replace(squad.slots[-1], player=squad.slot("f2").player),)
    )
    assert "duplicate_player" in validate_squad(duplicated, 5, rules).codes()


def test_club_limit_league_phase(rules, squad):
    """[club_limit_by_stage] A fourth player from one club is illegal in the league phase."""
    crowded = squad
    for pid in ("d1", "m1", "f2", "gk2"):
        crowded = move_to_club(crowded, pid, "Zulu")
    result = validate_squad(crowded, 5, rules)
    assert result.codes() == {"club_limit"}
    assert "Zulu (4)" in result.violations[0].message


def test_club_limit_rises_in_knockouts(rules, squad):
    """[club_limit_by_stage] The same four are legal from the play-offs."""
    crowded = squad
    for pid in ("d1", "m1", "f2", "gk2"):
        crowded = move_to_club(crowded, pid, "Zulu")
    assert validate_squad(crowded, 9, rules).ok


def test_inherited_club_limit_is_reported_not_refused(rules, squad):
    """[club_limit_inherited] Over the limit without transfers is a note, not a violation."""
    crowded = squad
    for pid in ("d1", "m1", "f2", "gk2"):
        crowded = move_to_club(crowded, pid, "Zulu")
    result = validate_squad(crowded, 5, rules, enforce_club_limit=False)
    assert result.ok
    assert any("next transfer" in n for n in result.notes)


def test_lineup_needs_eleven(rules, squad):
    """[lineup_formation] Ten starters is not a lineup."""
    fewer = change(squad, "m4", role=Role.BENCH, bench_order=5)
    assert "lineup_size" in validate_lineup(fewer, rules).codes()


def test_formation_minimum_defenders(rules, squad):
    """[lineup_formation] At least three defenders must start."""
    lineup = change(squad, "d3", role=Role.BENCH, bench_order=3)
    lineup = change(lineup, "d4", role=Role.BENCH, bench_order=4)
    lineup = change(lineup, "m5", role=Role.STARTER, bench_order=None)
    lineup = change(lineup, "f3", role=Role.STARTER, bench_order=None)
    result = validate_lineup(lineup, rules)
    assert result.codes() == {"formation"}
    assert "at least 3 DEF" in result.violations[0].message


def test_formation_exactly_one_goalkeeper(rules, squad):
    """[lineup_formation] Two goalkeepers cannot start."""
    lineup = change(squad, "gk2", role=Role.STARTER, bench_order=None)
    lineup = change(lineup, "m4", role=Role.BENCH, bench_order=1)
    assert any("exactly 1 GK" in v.message for v in validate_lineup(lineup, rules).violations)


def test_captain_must_be_a_starter(rules, squad):
    """[captain_double] The captain is chosen from the starting eleven."""
    lineup = change(change(squad, "f1", is_captain=False), "f3", is_captain=True)
    assert "captain_not_starter" in validate_lineup(lineup, rules).codes()


def test_exactly_one_captain(rules, squad):
    none = change(squad, "f1", is_captain=False)
    two = change(squad, "m1", is_captain=True)
    assert "captain_count" in validate_lineup(none, rules).codes()
    assert "captain_count" in validate_lineup(two, rules).codes()


def test_bench_order_must_be_distinct(rules, squad):
    """[automatic_substitutions] Bench order decides automatic substitutions, so it must be set."""
    clash = change(squad, "f3", bench_order=3)
    assert "bench_order" in validate_lineup(clash, rules).codes()


def test_every_legal_formation_validates(rules):
    """Property check: any lineup meeting the formation rule is accepted, others refused."""
    rng = random.Random(20261113)
    base = make_squad()
    outfield = [s for s in base.slots if s.player.position is not Position.GK]
    for _ in range(300):
        chosen = {s.player.id for s in rng.sample(outfield, 10)} | {"gk1"}
        bench_order = iter(range(1, 5))
        slots = []
        for s in base.slots:
            starting = s.player.id in chosen
            slots.append(
                replace(
                    s,
                    role=Role.STARTER if starting else Role.BENCH,
                    bench_order=None if starting else next(bench_order),
                    is_captain=False,
                )
            )
        lineup = Squad(tuple(slots))
        first_starter = next(s for s in lineup.slots if s.role is Role.STARTER)
        lineup = lineup.with_slot(replace(first_starter, is_captain=True))
        counts = lineup.position_counts(lineup.starters)
        legal = (
            counts[Position.DEF] >= 3 and counts[Position.MID] >= 2 and counts[Position.FWD] >= 1
        )
        assert validate_lineup(lineup, rules).ok is legal
