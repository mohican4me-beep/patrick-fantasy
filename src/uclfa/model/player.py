"""Player expected points for one match (Release 2 Phase C).

Combines a player's inputs (chance of starting, minutes, share of his team's goals and
assists, recoveries, saves, cards) with the match model's team numbers and the scoring
table in the rules file. Every result is an analyst estimate.

A player with a missing required input gets no number: the missing fields are listed.
No database, file or network access here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from uclfa.model.match import DEFAULT_SETTINGS_PATH
from uclfa.rules.model import Position, RuleSet

NOT_MODELLED = (
    "player of the match",
    "goals from outside the box",
    "penalties won, conceded, missed or saved",
    "own goals",
    "red cards",
)


class PlayerModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minutes_if_under_sixty: int = Field(ge=1, le=59)
    max_events: int = Field(ge=20, le=100)


def load_player_settings(path: Path = DEFAULT_SETTINGS_PATH) -> PlayerModelSettings:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return PlayerModelSettings.model_validate(data["player_model"])


class PlayerInputs(BaseModel):
    """One player's inputs. None means not known; nothing is filled in."""

    model_config = ConfigDict(extra="forbid")

    name: str
    club: str
    position: Position
    price: float | None = None
    price_tag: Literal["entered", "third_party"] | None = None
    price_source: str | None = None
    price_date: str | None = None
    # Required for a number:
    start_prob: float | None = Field(default=None, ge=0, le=1)
    p60_if_start: float | None = Field(default=None, ge=0, le=1)
    minutes_if_start: float | None = Field(default=None, ge=1, le=90)
    goal_share: float | None = Field(default=None, ge=0, le=1)  # of team goals, per 90
    assist_share: float | None = Field(default=None, ge=0, le=1)  # assists per team goal
    recoveries_p90: float | None = Field(default=None, ge=0)
    saves_p90: float | None = Field(default=None, ge=0)  # goalkeepers only
    # Optional; left out of the total, and said so, when missing:
    cards_p90: float | None = Field(default=None, ge=0)
    sub_prob: float = Field(default=0.0, ge=0, le=1)  # chance of coming on if not starting
    minutes_if_sub: float = Field(default=20.0, ge=1, le=59)
    sources: list[str] = Field(default_factory=list)
    note: str = ""

    def missing(self) -> list[str]:
        required = [
            "start_prob",
            "p60_if_start",
            "minutes_if_start",
            "goal_share",
            "assist_share",
            "recoveries_p90",
        ]
        if self.position is Position.GK:
            required.append("saves_p90")
        return [f for f in required if getattr(self, f) is None]


@dataclass(frozen=True)
class TeamContext:
    """Team numbers from the match model for the player's side."""

    goals_for: float  # team expected goals
    goals_against: float  # opponent expected goals
    clean_sheet: float  # chance the opponent scores 0 over 90 minutes


@dataclass
class PlayerPoints:
    expected: float
    if_starts: float
    plays_prob: float
    components: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _expected_blocks(rate: float, block: int, max_events: int) -> float:
    """E[floor(N / block)] for N ~ Poisson(rate)."""
    if rate <= 0:
        return 0.0
    p, total = math.exp(-rate), 0.0
    for n in range(1, max_events + 1):
        p *= rate / n
        total += (n // block) * p
    return total


def _scenario(
    p: PlayerInputs,
    team: TeamContext,
    rules: RuleSet,
    s: PlayerModelSettings,
    minutes: float,
    sixty_prob: float,
    minutes_when_sixty: float,
) -> dict[str, float]:
    """Expected points by component, given the player is on the pitch for `minutes`
    on average, reaching 60 with `sixty_prob` and then averaging `minutes_when_sixty`."""
    sc, pos, f = rules.scoring, p.position, minutes / 90
    out = {
        "appearance": float(sc.appearance),
        "sixty_minutes": sc.sixty_minutes * sixty_prob,
        "goals": team.goals_for * (p.goal_share or 0) * f * sc.goal[pos],
        "assists": team.goals_for * (p.assist_share or 0) * f * sc.assist,
        "balls_recovered": sc.balls_recovered_points
        * _expected_blocks((p.recoveries_p90 or 0) * f, sc.balls_recovered_block, s.max_events),
    }
    if sc.clean_sheet[pos] and sixty_prob > 0:
        # No goal conceded while on the pitch: the 90-minute chance scaled to his minutes.
        out["clean_sheet"] = (
            sc.clean_sheet[pos] * sixty_prob * team.clean_sheet ** (minutes_when_sixty / 90)
        )
    if pos in sc.goals_conceded_positions:
        out["goals_conceded"] = sc.goals_conceded_points * _expected_blocks(
            team.goals_against * f, sc.goals_conceded_block, s.max_events
        )
    if pos is Position.GK:
        out["saves"] = sc.saves_points * _expected_blocks(
            (p.saves_p90 or 0) * f, sc.saves_block, s.max_events
        )
    if p.cards_p90 is not None:
        out["yellow_cards"] = sc.yellow_card * min(1.0, p.cards_p90 * f)
    return out


def expected_points(
    p: PlayerInputs, team: TeamContext, rules: RuleSet, s: PlayerModelSettings
) -> PlayerPoints:
    """Raises ValueError if a required input is missing."""
    missing = p.missing()
    if missing:
        raise ValueError(f"missing inputs: {', '.join(missing)}")
    p60, m_start = p.p60_if_start, p.minutes_if_start
    low = s.minutes_if_under_sixty
    # Average minutes in the games where he reaches 60, implied by his average as a starter.
    m_sixty = min(90.0, max(60.0, (m_start - (1 - p60) * low) / p60)) if p60 > 0 else 0.0
    start = _scenario(p, team, rules, s, m_start, p60, m_sixty)
    sub = _scenario(p, team, rules, s, p.minutes_if_sub, 0.0, 0.0)
    w_start, w_sub = p.start_prob, (1 - p.start_prob) * p.sub_prob
    keys = sorted(set(start) | set(sub))
    components = {k: w_start * start.get(k, 0.0) + w_sub * sub.get(k, 0.0) for k in keys}
    notes = [f"not modelled: {', '.join(NOT_MODELLED)}"]
    if p.cards_p90 is None:
        notes.append("yellow cards left out: no card rate entered")
    return PlayerPoints(
        expected=sum(components.values()),
        if_starts=sum(start.values()),
        plays_prob=w_start + w_sub,
        components=components,
        notes=notes,
    )
