"""Captain and substitution calculators."""

import pytest

from uclfa import cli
from uclfa.decisions import (
    ESTIMATE,
    AutoSubRisk,
    CaptainCandidate,
    Swap,
    automatic_substitution_cost,
    captain_switch_value,
    substitution_value,
)


def test_scenario_c_keep_the_captain_on_seven(rules):
    """Scenario C from the brief: captain on 7, day-two alternative expected 6.4.
    Switching is worth 6.4 - 7 = -0.6, so keep."""
    decision = captain_switch_value(
        7, [CaptainCandidate("Day-two option", 6.4)], rules, estimate_author="Patrick"
    )
    assert decision.gains == {"Day-two option": -0.6}
    assert decision.recommendation == "keep"
    assert decision.break_even_expected_points == 7.0
    assert decision.tag == ESTIMATE and decision.estimate_author == "Patrick"
    assert any("analyst estimates" in a for a in decision.assumptions)


def test_captain_switch_when_alternative_is_higher(rules):
    decision = captain_switch_value(
        2, [CaptainCandidate("A", 6.4), CaptainCandidate("B", 5.0)], rules
    )
    assert decision.recommendation == "switch" and decision.best_candidate == "A"
    assert decision.best_gain == 4.4 and decision.gains["B"] == 3.0


def test_captain_tie_is_a_keep(rules):
    """The switch is irreversible, so an expected gain of zero is not worth taking."""
    assert captain_switch_value(6, [CaptainCandidate("A", 6.0)], rules).recommendation == "keep"


def test_captain_gain_uses_the_multiplier_from_the_rules_file(rules_copy):
    def triple(data):
        data["scoring"]["captain_multiplier"] = 3

    decision = captain_switch_value(2, [CaptainCandidate("A", 5.0)], rules_copy(triple))
    assert decision.best_gain == 6.0  # (3 - 1) x (5 - 2)


def test_automatic_substitution_cost_moves_the_break_even(rules):
    """[automatic_substitutions] Switching costs the cover the bench would have given."""
    risks = [AutoSubRisk("Later starter", 0.25, 4.0)]
    assert automatic_substitution_cost(risks) == 1.0
    decision = captain_switch_value(6, [CaptainCandidate("A", 6.8)], rules, auto_sub_risks=risks)
    assert decision.automatic_substitution_cost == 1.0
    assert decision.break_even_expected_points == 7.0
    assert decision.gains["A"] == pytest.approx(-0.2) and decision.recommendation == "keep"


def test_no_cost_when_automatic_substitutions_are_already_off(rules):
    risks = [AutoSubRisk("Later starter", 0.25, 4.0)]
    decision = captain_switch_value(
        6,
        [CaptainCandidate("A", 6.8)],
        rules,
        auto_sub_risks=risks,
        automatic_substitutions_already_disabled=True,
    )
    assert decision.automatic_substitution_cost == 0.0 and decision.recommendation == "switch"


def test_negative_captain_score(rules):
    decision = captain_switch_value(-2, [CaptainCandidate("A", 3.0)], rules)
    assert decision.best_gain == 5.0 and decision.recommendation == "switch"


def test_no_candidates_means_keep(rules):
    decision = captain_switch_value(4, [], rules)
    assert decision.recommendation == "keep" and decision.best_candidate is None
    assert "keep" in decision.summary().lower()


def test_scenario_d_secured_points_are_lost(rules):
    """Scenario D from the brief: a starter with points banked makes way for a bench
    player still to play. The banked points are given up in full."""
    decision = substitution_value(
        [Swap("Starter", "Bench", in_expected_points=6.4, out_realised_points=7)],
        rules,
        estimate_author="Patrick",
    )
    value = decision.swaps[0]
    assert value.points_given_up == 7 and value.points_given_up_tag == "entered"
    assert value.gain == pytest.approx(-0.6)
    assert decision.recommendation == "none" and decision.recommended == ()
    assert decision.tag == ESTIMATE
    assert any("scores 0" in a for a in decision.assumptions)


def test_substitution_worth_making(rules):
    decision = substitution_value(
        [
            Swap("Low scorer", "Bench A", in_expected_points=4.5, out_realised_points=1),
            Swap("High scorer", "Bench B", in_expected_points=4.0, out_realised_points=9),
        ],
        rules,
    )
    assert decision.recommendation == "make"
    assert decision.recommended == ("Low scorer -> Bench A",)
    assert decision.net_gain_if_recommended == 3.5


def test_substitution_cost_is_charged_once(rules):
    risks = [AutoSubRisk("Later starter", 0.5, 3.0)]  # cost 1.5
    swaps = [
        Swap("A", "X", in_expected_points=4.0, out_realised_points=2),  # +2
        Swap("B", "Y", in_expected_points=3.0, out_realised_points=2),  # +1
    ]
    decision = substitution_value(swaps, rules, auto_sub_risks=risks)
    assert decision.net_gain_if_recommended == 1.5  # 2 + 1 - 1.5, not minus 3
    marginal = substitution_value(swaps[1:], rules, auto_sub_risks=risks)
    assert marginal.recommendation == "none"  # +1 does not cover the 1.5 cost


def test_swap_for_a_player_still_to_play_uses_his_expectation(rules):
    decision = substitution_value(
        [Swap("Doubtful starter", "Bench", in_expected_points=5.0, out_expected_points=2.0)], rules
    )
    assert decision.swaps[0].points_given_up_tag == ESTIMATE
    assert decision.net_gain_if_recommended == 3.0


def test_at_most_four_substitutions_are_recommended(rules):
    """[manual_substitutions] Only the four best swaps can be made."""
    swaps = [
        Swap(f"Out{i}", f"In{i}", in_expected_points=5.0 + i, out_realised_points=1)
        for i in range(5)
    ]
    decision = substitution_value(swaps, rules)
    assert len(decision.recommended) == 4
    assert "Out0 -> In0" not in decision.recommended


def test_captain_taken_off_loses_doubled_points(rules):
    decision = substitution_value(
        [
            Swap(
                "Captain",
                "Bench",
                in_expected_points=6.0,
                out_realised_points=4,
                out_is_captain=True,
            )
        ],
        rules,
    )
    assert decision.swaps[0].points_given_up == 8
    assert any("captain calculator" in a for a in decision.assumptions)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"out_realised_points": None, "out_expected_points": None},
        {"out_realised_points": 3, "out_expected_points": 2},
    ],
)
def test_swap_needs_exactly_one_outgoing_value(kwargs):
    with pytest.raises(ValueError):
        Swap("A", "B", in_expected_points=4.0, **kwargs)


def test_risk_probability_is_validated():
    with pytest.raises(ValueError):
        AutoSubRisk("A", 1.5, 3.0)


def test_command_line_calculators(capsys):
    assert (
        cli.main(
            [
                "decide",
                "captain",
                "--points",
                "7",
                "--candidate",
                "Day-two option=6.4",
                "--author",
                "Patrick",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "gain -0.60" in out and "Keep the captain" in out and "analyst_estimate" in out
    assert (
        cli.main(
            [
                "decide",
                "sub",
                "--swap",
                "Starter|7|Bench|6.4",
                "--author",
                "Patrick",
                "--risk",
                "Later starter|0.2|3.0",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "gives up 7.00 (entered)" in out and "Make no substitution" in out
    assert "automatic-substitution cost: 0.60" in out
