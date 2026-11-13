"""Transfers, banking, hits, selling values and chips."""

from dataclasses import replace

import pytest

from uclfa.rules import (
    Chip,
    Position,
    Transfer,
    free_transfer_allowance,
    next_free_transfers,
    validate_chip,
    validate_transfers,
)

from .conftest import change, make_player, move_to_club


def tr(out_id: str, pid: str, position: Position, club: str = "Yankee", price: float = 5.0):
    return Transfer(out_id=out_id, incoming=make_player(pid, position, club, price))


def check(
    squad, transfers, rules, *, matchday=5, bank=1.0, free=2, chip=None, chips_used=frozenset()
):
    return validate_transfers(
        squad,
        transfers,
        matchday=matchday,
        bank=bank,
        free_transfers=free,
        rules=rules,
        chip=chip,
        chips_used=chips_used,
    )


# -- banking -------------------------------------------------------------------------


def test_scenario_b_use_one_of_two_then_hold_three(rules):
    """[transfer_carry] Scenario B: two available, one used, three next matchday."""
    assert next_free_transfers(5, available=2, used=1, rules=rules) == 3


def test_unused_transfers_never_exceed_three(rules):
    """[transfer_carry] Only one transfer carries: no stockpiling."""
    assert next_free_transfers(5, available=2, used=0, rules=rules) == 3
    assert next_free_transfers(6, available=3, used=0, rules=rules) == 3
    assert free_transfer_allowance(6, rules) == 3


def test_using_everything_leaves_two(rules):
    assert next_free_transfers(5, available=2, used=2, rules=rules) == 2
    assert next_free_transfers(5, available=3, used=5, rules=rules) == 2


def test_no_carry_after_a_chip(rules):
    """[transfer_carry] Nothing carries forward after Wildcard or Limitless."""
    assert next_free_transfers(5, available=2, used=0, rules=rules, chip_played=True) == 2


def test_no_carry_in_the_knockouts(rules):
    """[transfer_carry] Nothing carries once the knockout stage starts."""
    assert next_free_transfers(8, available=3, used=0, rules=rules) == "unlimited"
    assert next_free_transfers(9, available=None, used=4, rules=rules) == 2
    assert next_free_transfers(10, available=2, used=0, rules=rules) == "unlimited"
    assert next_free_transfers(12, available=3, used=0, rules=rules) == 5
    assert next_free_transfers(13, available=5, used=0, rules=rules) == 3
    assert next_free_transfers(17, available=5, used=0, rules=rules) is None


def test_knockout_allowance_has_no_carry(rules):
    assert free_transfer_allowance(10, rules) == 2
    assert free_transfer_allowance(12, rules) == 3
    assert free_transfer_allowance(9, rules) is None


# -- cost ----------------------------------------------------------------------------


def test_no_transfer_is_always_valid(rules, squad):
    """Scenario A baseline: zero transfers is legal and free."""
    outcome = check(squad, [], rules)
    assert outcome.result.ok
    assert outcome.transfers_made == 0 and outcome.points_cost == 0
    assert outcome.free_transfers_next_matchday == 3
    assert outcome.bank_after == 1.0


def test_free_transfers_cost_nothing(rules, squad):
    outcome = check(squad, [tr("m1", "n1", Position.MID), tr("f2", "n2", Position.FWD)], rules)
    assert outcome.result.ok
    assert outcome.paid_transfers == 0 and outcome.points_cost == 0
    assert outcome.free_transfers_next_matchday == 2


def test_each_extra_transfer_costs_four_points(rules, squad):
    """[transfer_hit] Three transfers with two free: one hit of four points."""
    transfers = [
        tr("m1", "n1", Position.MID),
        tr("f2", "n2", Position.FWD, club="Xray"),
        tr("d1", "n3", Position.DEF, club="Whiskey"),
    ]
    outcome = check(squad, transfers, rules)
    assert outcome.result.ok
    assert outcome.paid_transfers == 1 and outcome.points_cost == 4


def test_unlimited_matchday_has_no_hits(rules, squad):
    """[free_transfers_table] Unlimited before the play-offs first leg."""
    transfers = [
        tr(pid, f"n{i}", pos, club=f"Club{i}")
        for i, (pid, pos) in enumerate(
            [("m1", Position.MID), ("m2", Position.MID), ("f1", Position.FWD), ("d1", Position.DEF)]
        )
    ]
    outcome = check(squad, transfers, rules, matchday=9, free=None)
    assert outcome.result.ok and outcome.points_cost == 0
    assert outcome.free_transfers_next_matchday == 2


def test_holding_more_than_the_allowance_is_refused(rules, squad):
    outcome = check(squad, [], rules, free=4)
    assert "free_transfers_out_of_range" in outcome.result.codes()


# -- budget and selling value --------------------------------------------------------


def test_bank_updates_with_sale_and_purchase(rules, squad):
    outcome = check(squad, [tr("m1", "n1", Position.MID, price=5.5)], rules, bank=1.0)
    assert outcome.result.ok and outcome.bank_after == 0.5


def test_over_budget_is_refused(rules, squad):
    """[budget_by_stage] The bank cannot go negative."""
    outcome = check(squad, [tr("m1", "n1", Position.MID, price=7.0)], rules, bank=1.0)
    assert outcome.result.codes() == {"over_budget"}
    assert outcome.squad_after is None


def test_unconfirmed_sale_value_blocks_the_transfer(rules, squad):
    """[selling_value] Unverified rule: no default is applied, the transfer is blocked."""
    unknown = change(squad, "m1", sale_value=None)
    outcome = check(unknown, [tr("m1", "n1", Position.MID)], rules)
    assert outcome.result.status == "blocked"
    assert outcome.result.blocked_rules() == {"selling_value"}
    assert outcome.bank_after is None  # no guessed figure


def test_confirmed_selling_rule_supplies_the_value(confirm, squad):
    """[selling_value] Once you confirm the rule, the value follows from it."""
    slot = squad.slot("m1")
    risen = squad.with_slot(
        replace(slot, sale_value=None, purchase_price=5.0, player=replace(slot.player, price=5.6))
    )
    at_current = check(
        risen, [tr("m1", "n1", Position.MID, price=5.0)], confirm(selling_value="current_price")
    )
    at_purchase = check(
        risen, [tr("m1", "n1", Position.MID, price=5.0)], confirm(selling_value="purchase_price")
    )
    assert at_current.result.ok and at_current.bank_after == 1.6
    assert at_purchase.result.ok and at_purchase.bank_after == 1.0


def test_entered_sale_value_wins_over_the_rule(confirm, squad):
    slot = squad.slot("m1")
    entered = squad.with_slot(replace(slot, sale_value=5.3, player=replace(slot.player, price=5.6)))
    outcome = check(
        entered, [tr("m1", "n1", Position.MID, price=5.0)], confirm(selling_value="current_price")
    )
    assert outcome.bank_after == 1.3


def test_missing_purchase_price_is_refused(rules, squad):
    transfer = Transfer(
        out_id="m1", incoming=replace(make_player("n1", Position.MID, "Yankee"), price=None)
    )
    assert "price_missing" in check(squad, [transfer], rules).result.codes()


# -- squad legality after transfers --------------------------------------------------


def test_transfer_breaking_position_quota_is_refused(rules, squad):
    outcome = check(squad, [tr("m1", "n1", Position.FWD)], rules)
    assert "position_quota" in outcome.result.codes()


def test_transfer_breaking_club_limit_is_refused(rules, squad):
    """[club_limit_by_stage] A fourth player from Alpha."""
    outcome = check(squad, [tr("m2", "n1", Position.MID, club="Alpha")], rules)
    assert outcome.result.codes() == {"club_limit"}


def test_inherited_over_limit_squad(rules, squad):
    """[club_limit_inherited] Legal with zero transfers; any transfer must fix it."""
    crowded = squad
    for pid in ("d1", "m1", "f2", "gk2"):
        crowded = move_to_club(crowded, pid, "Zulu")
    assert check(crowded, [], rules).result.ok
    unrelated = check(crowded, [tr("m3", "n1", Position.MID)], rules)
    assert unrelated.result.codes() == {"club_limit"}
    fixing = check(crowded, [tr("m1", "n1", Position.MID)], rules)
    assert fixing.result.ok


def test_transfer_out_must_be_owned_and_in_must_be_new(rules, squad):
    not_owned = check(squad, [tr("zzz", "n1", Position.MID)], rules)
    assert "transfer_out_not_in_squad" in not_owned.result.codes()
    already = Transfer(out_id="m1", incoming=squad.slot("m2").player)
    assert "transfer_in_already_owned" in check(squad, [already], rules).result.codes()


def test_incoming_player_takes_the_outgoing_role(rules, squad):
    outcome = check(squad, [tr("f1", "n1", Position.FWD)], rules)
    new = outcome.squad_after.slot("n1")
    assert new.is_captain and new.role.value == "starter" and new.purchase_price == 5.0


# -- chips ---------------------------------------------------------------------------


@pytest.mark.parametrize("matchday", [1, 9, 11])
def test_chips_blocked_on_unlimited_matchdays(rules, matchday):
    """[chips] Neither chip on matchdays 1, 9 or 11."""
    for chip in Chip:
        assert validate_chip(chip, matchday, rules).codes() == {"chip_blocked_matchday"}


def test_chip_can_be_used_once(rules):
    """[chips] One use each."""
    assert validate_chip(Chip.WILDCARD, 6, rules).ok
    used = validate_chip(Chip.WILDCARD, 6, rules, chips_used={Chip.WILDCARD})
    assert used.codes() == {"chip_already_used"}
    assert validate_chip(Chip.LIMITLESS, 6, rules, chips_used={Chip.WILDCARD}).ok


def test_two_chips_on_one_matchday_is_blocked_until_confirmed(rules, confirm):
    """[two_chips_same_matchday] Unverified: blocked, not assumed either way."""
    result = validate_chip(Chip.LIMITLESS, 6, rules, chip_active_this_matchday=Chip.WILDCARD)
    assert result.status == "blocked" and result.blocked_rules() == {"two_chips_same_matchday"}
    refused = validate_chip(
        Chip.LIMITLESS,
        6,
        confirm(two_chips_same_matchday="not_allowed"),
        chip_active_this_matchday=Chip.WILDCARD,
    )
    assert refused.status == "invalid"
    assert validate_chip(
        Chip.LIMITLESS,
        6,
        confirm(two_chips_same_matchday="allowed"),
        chip_active_this_matchday=Chip.WILDCARD,
    ).ok


def test_wildcard_removes_hits_and_the_carry(rules, squad):
    """Scenario F: Wildcard makes every transfer free and nothing carries forward."""
    transfers = [
        tr("m1", "n1", Position.MID),
        tr("m2", "n2", Position.MID, club="Xray"),
        tr("f2", "n3", Position.FWD, club="Whiskey"),
        tr("d1", "n4", Position.DEF, club="Victor"),
    ]
    outcome = check(squad, transfers, rules, chip=Chip.WILDCARD)
    assert outcome.result.ok and outcome.points_cost == 0
    assert outcome.free_transfers_next_matchday == 2


def test_wildcard_still_respects_budget_and_club_limit(rules, squad):
    """[chips] Wildcard keeps the budget and club limits."""
    rich = check(squad, [tr("m1", "n1", Position.MID, price=9.0)], rules, chip=Chip.WILDCARD)
    assert "over_budget" in rich.result.codes()
    crowded = check(squad, [tr("m2", "n1", Position.MID, club="Alpha")], rules, chip=Chip.WILDCARD)
    assert "club_limit" in crowded.result.codes()


def test_limitless_ignores_budget_but_not_the_club_limit(rules, squad):
    """[chips] Limitless: no budget for one matchday, club limit kept, bank unchanged after."""
    transfers = [tr("m1", "n1", Position.MID, price=11.0), tr("f2", "n2", Position.FWD, price=11.0)]
    outcome = check(squad, transfers, rules, chip=Chip.LIMITLESS)
    assert outcome.result.ok and outcome.points_cost == 0
    assert outcome.bank_after == 1.0
    assert any("Re-confirm" in n for n in outcome.result.notes)
    crowded = check(
        squad, [tr("m2", "n1", Position.MID, club="Alpha", price=11.0)], rules, chip=Chip.LIMITLESS
    )
    assert "club_limit" in crowded.result.codes()


def test_used_chip_cannot_be_played_with_transfers(rules, squad):
    outcome = check(
        squad,
        [tr("m1", "n1", Position.MID)],
        rules,
        chip=Chip.WILDCARD,
        chips_used=frozenset({Chip.WILDCARD}),
    )
    assert "chip_already_used" in outcome.result.codes()
