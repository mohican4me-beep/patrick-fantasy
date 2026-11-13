"""Acceptance criterion 7: the scoring engine must reproduce real points from the game.

Each case is a points breakdown Patrick read from the UEFA Fantasy app. The events are
what the breakdown lists; the expected total is the total the game shows. Ten cases
covering all four positions are required. Cases present so far: 1 of 10.
"""

import pytest

from uclfa.rules import MatchEvents, Position, score_player

# (label, position, events, components the game listed, total the game showed)
REAL_PERFORMANCES = [
    (
        "Raphinha, Barcelona 3-0 Aston Villa (screenshot of 13 Nov 2026)",
        Position.MID,
        MatchEvents(minutes_played=70, goals=2, yellow_cards=1, player_of_the_match=True),
        {
            "appearance": 1,
            "sixty_minutes": 1,  # the game shows these two as "70 minutes played, 2 pts"
            "clean_sheet": 1,
            "goals": 10,
            "yellow_cards": -1,
            "player_of_the_match": 3,
        },
        15,
    ),
]

REQUIRED_CASES = 10


@pytest.mark.parametrize(
    ("label", "position", "events", "components", "expected_total"),
    REAL_PERFORMANCES,
    ids=[case[0] for case in REAL_PERFORMANCES],
)
def test_engine_reproduces_real_points(rules, label, position, events, components, expected_total):
    """[scoring_table] The engine's breakdown and total equal the game's."""
    breakdown = score_player(position, events, rules)
    assert breakdown.components == components
    assert breakdown.total == expected_total


@pytest.mark.xfail(strict=True, reason="criterion 7 open: ten real cases over four positions")
def test_ten_real_cases_cover_all_positions():
    assert len(REAL_PERFORMANCES) >= REQUIRED_CASES
    assert {case[1] for case in REAL_PERFORMANCES} == set(Position)
