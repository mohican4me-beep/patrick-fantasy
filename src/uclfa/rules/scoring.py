"""Official scoring: turn one player's match events into Fantasy points.

Points values and thresholds come from the RuleSet. The function scores a single match;
the captain multiplier is applied separately with `captain_points`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from uclfa.rules.model import Position, RuleSet


@dataclass(frozen=True)
class MatchEvents:
    """What one player did in one match.

    minutes_played excludes added time, as UEFA counts it for the 60-minute point. Extra
    time counts, so the value may exceed 90.

    goals_conceded_on_pitch counts goals his team conceded while he was on the pitch.
    goals_conceded_after_red counts goals conceded after he was sent off; UEFA keeps
    deducting for those.

    penalties_won must exclude penalties awarded for handball, which score nothing.
    Shoot-out events are never entered: they score nothing.
    """

    minutes_played: int = 0
    appeared: bool | None = None  # set True for a cameo recorded as 0 minutes
    goals: int = 0
    goals_outside_box: int = 0
    assists: int = 0
    balls_recovered: int = 0
    saves: int = 0
    penalties_saved: int = 0
    goals_conceded_on_pitch: int = 0
    goals_conceded_after_red: int = 0
    player_of_the_match: bool = False
    penalties_won: int = 0
    penalties_conceded: int = 0
    penalties_missed: int = 0
    yellow_cards: int = 0
    red_card: bool = False
    own_goals: int = 0

    def __post_init__(self) -> None:
        for name in (
            "minutes_played",
            "goals",
            "goals_outside_box",
            "assists",
            "balls_recovered",
            "saves",
            "penalties_saved",
            "goals_conceded_on_pitch",
            "goals_conceded_after_red",
            "penalties_won",
            "penalties_conceded",
            "penalties_missed",
            "yellow_cards",
            "own_goals",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.goals_outside_box > self.goals:
            raise ValueError("goals_outside_box cannot exceed goals")
        if self.yellow_cards > 2:
            raise ValueError("a player cannot receive more than two yellow cards")
        if self.yellow_cards == 2 and not self.red_card:
            raise ValueError("two yellow cards are a sending-off: set red_card")
        if self.goals_conceded_after_red and not self.red_card:
            raise ValueError("goals_conceded_after_red requires red_card")

    @property
    def did_appear(self) -> bool:
        return self.minutes_played > 0 if self.appeared is None else self.appeared


@dataclass(frozen=True)
class ScoreBreakdown:
    position: Position
    components: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.components.values())


def score_player(position: Position, events: MatchEvents, rules: RuleSet) -> ScoreBreakdown:
    """Score one player's match. A player who did not appear scores nothing."""
    s = rules.scoring
    c: dict[str, int] = {}
    if not events.did_appear:
        return ScoreBreakdown(position, c)

    def add(name: str, value: int) -> None:
        if value:
            c[name] = value

    add("appearance", s.appearance)
    reached_sixty = events.minutes_played >= s.sixty_minutes_threshold
    if reached_sixty:
        add("sixty_minutes", s.sixty_minutes)

    add("goals", events.goals * s.goal[position])
    add("goals_outside_box", events.goals_outside_box * s.goal_outside_box_bonus)
    add("assists", events.assists * s.assist)

    # One award per match however long it lasts, so 120 minutes cannot double it.
    if reached_sixty and events.goals_conceded_on_pitch == 0:
        add("clean_sheet", s.clean_sheet[position])

    add(
        "balls_recovered",
        (events.balls_recovered // s.balls_recovered_block) * s.balls_recovered_points,
    )

    if position is Position.GK:
        add("saves", (events.saves // s.saves_block) * s.saves_points)
        add("penalty_saves", events.penalties_saved * s.penalty_save)

    if position in s.goals_conceded_positions:
        conceded = events.goals_conceded_on_pitch + events.goals_conceded_after_red
        add("goals_conceded", (conceded // s.goals_conceded_block) * s.goals_conceded_points)

    if events.player_of_the_match:
        add("player_of_the_match", s.player_of_the_match)
    add("penalties_won", events.penalties_won * s.penalty_won)
    add("penalties_conceded", events.penalties_conceded * s.penalty_conceded)
    add("penalties_missed", events.penalties_missed * s.penalty_missed)

    # A yellow followed by a red counts as the red only.
    if events.red_card:
        add("red_card", s.red_card)
    else:
        add("yellow_cards", events.yellow_cards * s.yellow_card)
    add("own_goals", events.own_goals * s.own_goal)
    return ScoreBreakdown(position, c)


def captain_points(points: int, rules: RuleSet) -> int:
    """Points a captain contributes: his match points times the captain multiplier."""
    return points * rules.scoring.captain_multiplier
