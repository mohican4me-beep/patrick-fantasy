"""Manual substitutions and captain switches between playing days."""

from uclfa.rules import BreakContext, Role, Substitution, validate_between_days

from .conftest import change

# In the reference squad the starters are gk1, d1-d4, m1-m4, f1 (captain), f2 and the
# bench is gk2 (unnumbered), d5 (1), m5 (2), f3 (3).
DAY_ONE = frozenset({"gk1", "d1", "d2", "m1", "m2", "f1"})


def ctx(matchday=5, played=DAY_ONE, **kwargs) -> BreakContext:
    return BreakContext(matchday=matchday, played_ids=frozenset(played), **kwargs)


def test_no_change_keeps_automatic_substitutions(rules, squad):
    """[automatic_substitutions] Doing nothing leaves automatic substitutions on."""
    outcome = validate_between_days(squad, [], None, ctx(), rules)
    assert outcome.result.ok and not outcome.automatic_substitutions_disabled


def test_scenario_d_legal_substitution(rules, squad):
    """[manual_substitutions] Scenario D: a starter who has played makes way for a bench
    player still to play. Legal, his points become 0, automatic substitutions go off."""
    outcome = validate_between_days(squad, [Substitution("m1", "m5")], None, ctx(), rules)
    assert outcome.result.ok
    assert outcome.automatic_substitutions_disabled
    assert outcome.squad_after.slot("m5").role is Role.STARTER
    assert outcome.squad_after.slot("m1").role is Role.BENCH
    assert outcome.squad_after.slot("m1").bench_order == 2
    assert any("become 0" in n for n in outcome.result.notes)
    assert any("automatic substitutions" in n for n in outcome.result.notes)


def test_incoming_player_must_be_still_to_play(rules, squad):
    """[manual_substitutions] A bench player whose team has played cannot come on."""
    outcome = validate_between_days(
        squad, [Substitution("m3", "m5")], None, ctx(played=DAY_ONE | {"m5"}), rules
    )
    assert outcome.result.codes() == {"substitution_in_already_played"}


def test_at_most_four_substitutions(rules, squad):
    """[manual_substitutions] Four per break."""
    bench_heavy = change(squad, "m4", role=Role.BENCH, bench_order=4)
    subs = [
        Substitution("d1", "d5"),
        Substitution("m1", "m5"),
        Substitution("f2", "f3"),
        Substitution("m2", "m4"),
        Substitution("gk1", "gk2"),
    ]
    outcome = validate_between_days(bench_heavy, subs, None, ctx(), rules)
    assert "too_many_substitutions" in outcome.result.codes()


def test_four_substitutions_are_allowed(rules, squad, confirm):
    subs = [
        Substitution("d1", "d5"),
        Substitution("m1", "m5"),
        Substitution("f2", "f3"),
        Substitution("gk1", "gk2"),
    ]
    allowed = confirm(goalkeeper_manual_substitution="allowed")
    assert validate_between_days(squad, subs, None, ctx(), allowed).result.ok


def test_sent_off_player_cannot_be_removed(rules, squad):
    """[manual_substitutions] A sent-off player stays in the eleven."""
    outcome = validate_between_days(
        squad, [Substitution("m1", "m5")], None, ctx(sent_off_ids=frozenset({"m1"})), rules
    )
    assert outcome.result.codes() == {"substitution_out_sent_off"}


def test_substitution_must_keep_a_legal_formation(rules, squad):
    """[lineup_formation] Swapping the last forward pair for a defender is fine; dropping
    below three defenders is not."""
    lineup = change(squad, "d4", role=Role.BENCH, bench_order=4)
    lineup = change(lineup, "f3", role=Role.STARTER, bench_order=None)
    lineup = change(lineup, "d4", bench_order=3)
    outcome = validate_between_days(lineup, [Substitution("d3", "m5")], None, ctx(), rules)
    assert "formation" in outcome.result.codes()


def test_goalkeeper_substitution_is_blocked_until_confirmed(rules, squad, confirm):
    """[goalkeeper_manual_substitution] Unverified: blocked, no default either way."""
    subs = [Substitution("gk1", "gk2")]
    blocked = validate_between_days(squad, subs, None, ctx(), rules)
    assert blocked.result.status == "blocked"
    assert blocked.result.blocked_rules() == {"goalkeeper_manual_substitution"}
    refused = validate_between_days(
        squad, subs, None, ctx(), confirm(goalkeeper_manual_substitution="not_allowed")
    )
    assert refused.result.codes() == {"goalkeeper_substitution"}


def test_bench_and_starter_roles_are_checked(rules, squad):
    wrong_out = validate_between_days(squad, [Substitution("d5", "m5")], None, ctx(), rules)
    assert "substitution_out_not_starter" in wrong_out.result.codes()
    wrong_in = validate_between_days(squad, [Substitution("m3", "m4")], None, ctx(), rules)
    assert "substitution_in_not_bench" in wrong_in.result.codes()


# -- captain -------------------------------------------------------------------------


def test_scenario_c_captain_switch_is_legal(rules, squad):
    """[captain_switch] Scenario C: the day-one captain has played; the armband may move
    to a starter still to play."""
    outcome = validate_between_days(squad, [], "f2", ctx(), rules)
    assert outcome.result.ok
    assert outcome.squad_after.captain.player.id == "f2"
    assert outcome.automatic_substitutions_disabled


def test_captain_cannot_go_to_a_player_who_has_played(rules, squad):
    """[captain_switch] Not to a player whose team has already played."""
    outcome = validate_between_days(squad, [], "m1", ctx(), rules)
    assert outcome.result.codes() == {"captain_already_played"}


def test_captain_cannot_switch_back(rules, squad):
    """[captain_switch] The armband cannot return to an earlier captain."""
    moved = change(change(squad, "f1", is_captain=False), "m3", is_captain=True)
    outcome = validate_between_days(
        moved,
        [],
        "f2",
        ctx(played={"gk1"}, previous_captain_ids=frozenset({"f2"})),
        rules,
    )
    assert outcome.result.codes() == {"captain_switch_back"}


def test_captain_must_be_a_starter(rules, squad):
    outcome = validate_between_days(squad, [], "f3", ctx(), rules)
    assert outcome.result.codes() == {"captain_not_starter"}


def test_removing_the_captain_requires_a_new_one(rules, squad):
    outcome = validate_between_days(squad, [Substitution("f1", "f3")], None, ctx(), rules)
    assert "captain_substituted_out" in outcome.result.codes()
    with_new = validate_between_days(squad, [Substitution("f1", "f3")], "f2", ctx(), rules)
    assert with_new.result.ok and with_new.squad_after.captain.player.id == "f2"


def test_captain_on_substituted_in_player_is_blocked_until_confirmed(rules, squad, confirm):
    """[captain_on_substituted_in] Unverified: blocked, no default either way."""
    subs = [Substitution("m1", "m5")]
    blocked = validate_between_days(squad, subs, "m5", ctx(), rules)
    assert blocked.result.status == "blocked"
    assert blocked.result.blocked_rules() == {"captain_on_substituted_in"}
    allowed = validate_between_days(
        squad, subs, "m5", ctx(), confirm(captain_on_substituted_in="allowed")
    )
    assert allowed.result.ok and allowed.squad_after.captain.player.id == "m5"


# -- windows -------------------------------------------------------------------------


def test_matchday_eight_and_final_allow_no_changes(rules, squad):
    """[mid_matchday_changes_excluded] MD8 is simultaneous; the final is one match."""
    for matchday in (8, 17):
        outcome = validate_between_days(squad, [], "f2", ctx(matchday=matchday), rules)
        assert "no_mid_matchday_changes" in outcome.result.codes()


def test_changes_after_next_day_kickoff_are_blocked_until_confirmed(rules, squad, confirm):
    """[late_changes_after_kickoff] Unverified: blocked, no default either way."""
    late = ctx(next_day_started=True)
    blocked = validate_between_days(squad, [], "f2", late, rules)
    assert blocked.result.status == "blocked"
    assert blocked.result.blocked_rules() == {"late_changes_after_kickoff"}
    refused = validate_between_days(
        squad, [], "f2", late, confirm(late_changes_after_kickoff="not_allowed")
    )
    assert refused.result.codes() == {"window_closed"}
    assert validate_between_days(
        squad, [], "f2", late, confirm(late_changes_after_kickoff="allowed")
    ).result.ok
