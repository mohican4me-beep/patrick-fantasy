"""Acceptance criterion 7: the scoring engine must reproduce real points from the game.

Each case is a points breakdown Patrick read from the UEFA Fantasy app. The events are
what the breakdown lists; the expected total is the total the game shows. Ten cases
covering all four positions are required. Cases present so far: 9 of 10.
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
    (
        "Joan Garcia, Barcelona 3-0 Aston Villa",
        Position.GK,
        MatchEvents(minutes_played=90, saves=1),
        {"appearance": 1, "sixty_minutes": 1, "clean_sheet": 4},  # "1 shot saved, 0 pts"
        6,
    ),
    (
        "Gregor Kobel, B. Dortmund 2-1 Real Betis",
        Position.GK,
        MatchEvents(minutes_played=90, saves=3, goals_conceded_on_pitch=1),
        {"appearance": 1, "sixty_minutes": 1, "saves": 1},  # "1 goal conceded, 0 pts"
        3,
    ),
    (
        "Joane Gadou, B. Dortmund 2-1 Real Betis",
        Position.DEF,
        MatchEvents(minutes_played=15, balls_recovered=1),
        {"appearance": 1},  # "1 ball recovered, 0 pts"
        1,
    ),
    (
        "Carlos Augusto, Feyenoord 0-3 Inter",
        Position.DEF,
        MatchEvents(minutes_played=90, balls_recovered=10),
        {"appearance": 1, "sixty_minutes": 1, "clean_sheet": 4, "balls_recovered": 3},
        9,
    ),
    (
        "Harry Kane, Atleti 0-2 Bayern Munchen",
        Position.FWD,
        MatchEvents(minutes_played=90, assists=1),
        {"appearance": 1, "sixty_minutes": 1, "assists": 3},
        5,
    ),
    (
        "Kylian Mbappe, AEK Athens 2-3 Real Madrid",
        Position.FWD,
        MatchEvents(minutes_played=90, goals=1, balls_recovered=1, goals_conceded_on_pitch=2),
        {"appearance": 1, "sixty_minutes": 1, "goals": 4},  # "1 ball recovered, 0 pts"
        6,
    ),
    (
        "Bryan Mbeumo, Man Utd 3-2 Roma",
        Position.FWD,
        MatchEvents(minutes_played=90, balls_recovered=3, goals_conceded_on_pitch=2),
        {"appearance": 1, "sixty_minutes": 1, "balls_recovered": 1},
        3,
    ),
    (
        "Joao Neves, Villarreal 0-6 Paris",
        Position.MID,
        MatchEvents(minutes_played=90, goals=1, assists=2, balls_recovered=5),
        {
            "appearance": 1,
            "sixty_minutes": 1,
            "goals": 5,
            "assists": 6,
            "clean_sheet": 1,
            "balls_recovered": 1,
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
