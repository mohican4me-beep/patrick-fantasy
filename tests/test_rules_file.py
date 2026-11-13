"""The rules file: values traced to UEFA's 2026/27 rules page, and the verification register."""

from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from uclfa.rules import Position, Status, save_confirmation, validate_squad
from uclfa.rules.model import CONFIRMABLE_VALUES

from .conftest import make_squad, move_to_club


def test_squad_composition(rules):
    """[squad_composition] 15 players: 2 GK, 5 DEF, 5 MID, 3 FWD."""
    assert rules.squad.size == 15
    assert rules.squad.positions == {
        Position.GK: 2,
        Position.DEF: 5,
        Position.MID: 5,
        Position.FWD: 3,
    }


def test_budget_by_stage(rules):
    """[budget_by_stage] EUR 100m, rising to EUR 105m after the league phase."""
    assert rules.stage_for(8).budget == 100.0
    assert rules.stage_for(9).budget == 105.0
    assert rules.stage_for(17).budget == 105.0


@pytest.mark.parametrize(
    ("matchday", "limit"),
    [
        (1, 3),
        (8, 3),
        (9, 4),
        (10, 4),
        (11, 4),
        (12, 4),
        (13, 5),
        (14, 5),
        (15, 6),
        (16, 6),
        (17, 8),
    ],
)
def test_club_limit_by_stage(rules, matchday, limit):
    """[club_limit_by_stage] 3 in the league phase, then 4, 4, 5, 6 and 8 in the final."""
    assert rules.stage_for(matchday).club_limit == limit


@pytest.mark.parametrize(
    ("matchday", "free"),
    [
        (1, "unlimited"),
        (2, 2),
        (5, 2),
        (8, 2),
        (9, "unlimited"),
        (10, 2),
        (11, "unlimited"),
        (12, 3),
        (13, 5),
        (14, 3),
        (15, 5),
        (16, 3),
        (17, 5),
    ],
)
def test_free_transfers_table(rules, matchday, free):
    """[free_transfers_table] The allowance before each matchday."""
    assert rules.matchday(matchday).free_transfers == free


def test_all_seventeen_matchdays_defined(rules):
    assert sorted(rules.matchdays) == list(range(1, 18))


def test_carry_only_inside_league_phase(rules):
    """[transfer_carry] Carry applies between league-phase matchdays only."""
    assert [n for n, md in rules.matchdays.items() if md.carry_in] == [3, 4, 5, 6, 7, 8]


def test_mid_matchday_changes_excluded(rules):
    """[mid_matchday_changes_excluded] Matchday 8 and the final allow none."""
    assert [n for n, md in rules.matchdays.items() if not md.mid_matchday_changes] == [8, 17]


def test_chip_blocked_matchdays(rules):
    """[chips] Not usable on matchdays 1, 9 and 11."""
    assert rules.chips.blocked_matchdays == [1, 9, 11]
    assert rules.chips.limitless.budget_applies is False
    assert rules.chips.limitless.club_limit_applies is True
    assert rules.chips.wildcard.permanent is True


def test_remaining_deadline_dates(rules):
    """[deadline_times] Dates are published; clock times stay unconfirmed."""
    assert rules.matchday(5).deadline_date.isoformat() == "2026-11-24"
    assert rules.matchday(8).deadline_date.isoformat() == "2027-01-27"
    assert rules.matchday(5).deadline_utc.isoformat() == "2026-11-24T17:45:00+00:00"
    athens = rules.matchday(5).deadline_utc.astimezone(ZoneInfo("Europe/Athens"))
    assert athens.strftime("%d %B, %H:%M") == "24 November, 19:45"  # as the game shows it
    assert all(md.deadline_utc is None for n, md in rules.matchdays.items() if n != 5)
    assert rules.status("deadline_times") is Status.PARTLY_CONFIRMED


def test_open_rules_are_unverified_until_confirmed(rules):
    expected_open = {
        "selling_value",
        "goalkeeper_manual_substitution",
        "captain_on_substituted_in",
        "late_changes_after_kickoff",
        "two_chips_same_matchday",
    }
    unverified = {r for r in rules.rule_register if rules.status(r) is Status.UNVERIFIED}
    assert unverified == expected_open == set(CONFIRMABLE_VALUES)
    for rule_id in expected_open:
        assert rules.confirmed_value(rule_id) is None
        assert rules.rule_register[rule_id].blocks


def test_confirmation_upgrades_status(confirm):
    rules = confirm(selling_value="current_price")
    assert rules.status("selling_value") is Status.CONFIRMED
    assert rules.confirmed_value("selling_value") == "current_price"


def test_confirmation_rejects_unknown_value(confirm):
    with pytest.raises(ValidationError):
        confirm(selling_value="half_the_profit")


def test_confirmation_rejects_rule_that_is_not_open(confirm):
    with pytest.raises(ValidationError):
        confirm(transfer_hit="allowed")


def test_save_confirmation_round_trip(tmp_path):
    path = tmp_path / "confirmations.yaml"
    rules = save_confirmation(
        "goalkeeper_manual_substitution", "allowed", "checked", confirmations_path=path
    )
    assert rules.confirmed_value("goalkeeper_manual_substitution") == "allowed"
    with pytest.raises(ValueError):
        save_confirmation("selling_value", "guess", confirmations_path=path)


def test_changing_the_rules_file_changes_behaviour(rules, rules_copy):
    """Acceptance: a value changed in the file changes the engine with no code change."""
    squad = move_to_club(move_to_club(make_squad(), "d1", "Zulu"), "m1", "Zulu")
    squad = move_to_club(squad, "f2", "Zulu")
    assert validate_squad(squad, 5, rules).ok  # three from one club is legal at limit 3

    def tighten(data):
        data["stages"]["league_phase"]["club_limit"] = 2

    stricter = rules_copy(tighten)
    assert "club_limit" in validate_squad(squad, 5, stricter).codes()


def test_rules_file_rejects_inconsistent_quotas(rules_copy):
    def break_quota(data):
        data["squad"]["positions"]["FWD"] = 4

    with pytest.raises(ValidationError):
        rules_copy(break_quota)
