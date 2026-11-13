"""Official scoring, one test per row of UEFA's 2026/27 points table."""

import pytest

from uclfa.rules import MatchEvents, Position, captain_points, score_player

GK, DEF, MID, FWD = Position.GK, Position.DEF, Position.MID, Position.FWD


def total(position, rules, **events) -> int:
    return score_player(position, MatchEvents(**events), rules).total


def test_did_not_play_scores_nothing(rules):
    """[scoring_table] A player who does not appear scores 0, whatever else is recorded."""
    assert total(MID, rules, minutes_played=0, yellow_cards=1) == 0


def test_appearance_and_sixty_minutes(rules):
    """[scoring_table] 1 for appearing, 1 more for 60 minutes excluding added time."""
    assert total(FWD, rules, minutes_played=59) == 1
    assert total(FWD, rules, minutes_played=60) == 2
    assert total(FWD, rules, minutes_played=0, appeared=True) == 1


@pytest.mark.parametrize(("position", "points"), [(GK, 6), (DEF, 6), (MID, 5), (FWD, 4)])
def test_goal_points_by_position(rules, position, points):
    """[scoring_table] Goals: 6 for goalkeepers and defenders, 5 midfielders, 4 forwards."""
    base = total(position, rules, minutes_played=30, goals_conceded_on_pitch=1)
    assert (
        total(position, rules, minutes_played=30, goals=1, goals_conceded_on_pitch=1) - base
        == points
    )


def test_goal_from_outside_the_box_bonus(rules):
    """[scoring_table] One extra point for a goal from outside the box."""
    assert total(FWD, rules, minutes_played=30, goals=1, goals_outside_box=1) == 1 + 4 + 1


def test_assist(rules):
    """[scoring_table] 3 per assist, every position."""
    assert total(FWD, rules, minutes_played=30, assists=2) == 1 + 6


@pytest.mark.parametrize(("position", "points"), [(GK, 4), (DEF, 4), (MID, 1), (FWD, 0)])
def test_clean_sheet_by_position(rules, position, points):
    """[scoring_table] Clean sheet: 4 for goalkeepers and defenders, 1 midfielders, 0 forwards."""
    assert total(position, rules, minutes_played=90) == 2 + points


def test_clean_sheet_needs_sixty_minutes(rules):
    """[clean_sheet_on_pitch] Fewer than 60 minutes earns no clean sheet."""
    assert total(DEF, rules, minutes_played=59) == 1


def test_clean_sheet_survives_a_goal_after_substitution(rules):
    """[clean_sheet_on_pitch] Off at 70 with none conceded: the clean sheet stands even if
    the team concedes later, because that goal was not while he was on the pitch."""
    assert total(DEF, rules, minutes_played=70, goals_conceded_on_pitch=0) == 2 + 4


def test_clean_sheet_lost_when_conceding_on_pitch(rules):
    assert total(DEF, rules, minutes_played=90, goals_conceded_on_pitch=1) == 2


@pytest.mark.parametrize(("recovered", "points"), [(0, 0), (2, 0), (3, 1), (5, 1), (6, 2), (11, 3)])
def test_balls_recovered_in_whole_blocks_of_three(rules, recovered, points):
    """[scoring_table] 1 point per 3 balls recovered: whole blocks only, not a ratio."""
    assert total(FWD, rules, minutes_played=30, balls_recovered=recovered) == 1 + points


def test_balls_recovered_apply_to_goalkeepers(rules):
    """[goalkeeper_ball_recoveries] Listed for all players, so the engine scores them."""
    with_recoveries = total(
        GK, rules, minutes_played=30, balls_recovered=3, goals_conceded_on_pitch=1
    )
    without = total(GK, rules, minutes_played=30, goals_conceded_on_pitch=1)
    assert with_recoveries - without == 1


@pytest.mark.parametrize(("saves", "points"), [(2, 0), (3, 1), (7, 2)])
def test_saves_in_blocks_of_three(rules, saves, points):
    """[scoring_table] Goalkeepers: 1 point per 3 saves."""
    assert total(GK, rules, minutes_played=30, saves=saves, goals_conceded_on_pitch=1) == 1 + points


def test_saves_only_count_for_goalkeepers(rules):
    assert total(DEF, rules, minutes_played=30, saves=6, goals_conceded_on_pitch=1) == 1


def test_penalty_save(rules):
    """[scoring_table] 5 for a penalty save."""
    assert total(GK, rules, minutes_played=30, penalties_saved=1, goals_conceded_on_pitch=1) == 6


@pytest.mark.parametrize(("conceded", "points"), [(1, 0), (2, -1), (3, -1), (4, -2)])
def test_goals_conceded_per_two(rules, conceded, points):
    """[scoring_table] Goalkeepers and defenders lose 1 per 2 goals conceded."""
    for position in (GK, DEF):
        assert (
            total(position, rules, minutes_played=90, goals_conceded_on_pitch=conceded)
            == 2 + points
        )


def test_goals_conceded_do_not_cost_midfielders_or_forwards(rules):
    assert total(MID, rules, minutes_played=90, goals_conceded_on_pitch=4) == 2
    assert total(FWD, rules, minutes_played=90, goals_conceded_on_pitch=4) == 2


def test_player_of_the_match(rules):
    """[scoring_table] 3 for Player of the Match."""
    assert total(FWD, rules, minutes_played=90, player_of_the_match=True) == 2 + 3


def test_penalty_events(rules):
    """[scoring_table] Won +2, conceded -1, missed -2."""
    assert total(FWD, rules, minutes_played=90, penalties_won=1) == 4
    assert total(FWD, rules, minutes_played=90, penalties_conceded=1) == 1
    assert total(FWD, rules, minutes_played=90, penalties_missed=1) == 0


def test_cards_and_own_goal(rules):
    """[scoring_table] Yellow -1, red -3, own goal -2."""
    assert total(FWD, rules, minutes_played=90, yellow_cards=1) == 1
    assert total(FWD, rules, minutes_played=50, red_card=True) == -2
    assert total(FWD, rules, minutes_played=90, own_goals=1) == 0


def test_yellow_then_red_counts_as_the_red_only(rules):
    """[red_card_rules] A second yellow is scored as the red card alone."""
    assert total(FWD, rules, minutes_played=50, yellow_cards=2, red_card=True) == 1 - 3
    assert total(FWD, rules, minutes_played=50, yellow_cards=1, red_card=True) == 1 - 3


def test_sent_off_defender_keeps_losing_points_for_goals(rules):
    """[red_card_rules] Goals conceded after the sending-off still count against him."""
    points = total(
        DEF,
        rules,
        minutes_played=30,
        red_card=True,
        goals_conceded_on_pitch=1,
        goals_conceded_after_red=3,
    )
    assert points == 1 - 3 - 2


def test_extra_time_does_not_double_awards(rules):
    """[extra_time] 120 minutes: one appearance set and one clean sheet, not two."""
    assert total(DEF, rules, minutes_played=120) == 1 + 1 + 4
    assert total(FWD, rules, minutes_played=120, goals=1) == 2 + 4


def test_breakdown_lists_each_component(rules):
    breakdown = score_player(
        MID, MatchEvents(minutes_played=90, goals=1, assists=1, balls_recovered=7), rules
    )
    assert breakdown.components == {
        "appearance": 1,
        "sixty_minutes": 1,
        "goals": 5,
        "assists": 3,
        "clean_sheet": 1,
        "balls_recovered": 2,
    }
    assert breakdown.total == 13


def test_captain_points_are_doubled(rules):
    """[captain_double] The captain's points are doubled."""
    assert captain_points(7, rules) == 14
    assert captain_points(-2, rules) == -4


def test_scoring_reads_values_from_the_rules_file(rules_copy):
    def edit(data):
        data["scoring"]["assist"] = 4
        data["scoring"]["balls_recovered_block"] = 2

    edited = rules_copy(edit)
    assert total(FWD, edited, minutes_played=30, assists=1, balls_recovered=4) == 1 + 4 + 2


@pytest.mark.parametrize(
    "bad",
    [
        {"minutes_played": -1},
        {"minutes_played": 90, "goals": 1, "goals_outside_box": 2},
        {"minutes_played": 90, "yellow_cards": 2},
        {"minutes_played": 90, "goals_conceded_after_red": 1},
    ],
)
def test_impossible_events_are_rejected(bad):
    with pytest.raises(ValueError):
        MatchEvents(**bad)
