"""Typed view of the versioned rules file and the user's rule confirmations.

The rules engine reads all of its behaviour from a RuleSet. Nothing about the game is
hard-coded elsewhere in the package.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RULES_PATH = REPO_ROOT / "rules" / "2026-27.yaml"
DEFAULT_CONFIRMATIONS_PATH = REPO_ROOT / "rules" / "confirmations.yaml"


class Position(StrEnum):
    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


class Chip(StrEnum):
    WILDCARD = "wildcard"
    LIMITLESS = "limitless"


class Status(StrEnum):
    CONFIRMED = "confirmed"
    PARTLY_CONFIRMED = "partly_confirmed"
    UNVERIFIED = "unverified"


# Values a user may record for each rule that the official page leaves open.
CONFIRMABLE_VALUES: dict[str, tuple[str, ...]] = {
    "selling_value": ("current_price", "purchase_price"),
    "goalkeeper_manual_substitution": ("allowed", "not_allowed"),
    "captain_on_substituted_in": ("allowed", "not_allowed"),
    "late_changes_after_kickoff": ("allowed", "not_allowed"),
    "two_chips_same_matchday": ("allowed", "not_allowed"),
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SquadRules(_Strict):
    size: int
    positions: dict[Position, int]

    @model_validator(mode="after")
    def _positions_sum_to_size(self) -> SquadRules:
        if sum(self.positions.values()) != self.size:
            raise ValueError("squad position quotas do not sum to the squad size")
        return self


class LineupRules(_Strict):
    size: int
    exact: dict[Position, int]
    minimum: dict[Position, int]


class StageRules(_Strict):
    budget: float
    club_limit: int


class TransferRules(_Strict):
    hit_cost: int
    league_phase_carry: int


class ChipEffect(_Strict):
    permanent: bool
    budget_applies: bool
    club_limit_applies: bool


class ChipRules(_Strict):
    names: list[Chip]
    uses_each: int
    blocked_matchdays: list[int]
    wildcard: ChipEffect
    limitless: ChipEffect

    def effect(self, chip: Chip) -> ChipEffect:
        return self.wildcard if chip is Chip.WILDCARD else self.limitless


class ManualChangeRules(_Strict):
    max_substitutions_per_break: int


class MatchdayRules(_Strict):
    stage: str
    free_transfers: int | Literal["unlimited"]
    carry_in: bool
    mid_matchday_changes: bool
    deadline_date: date | None
    deadline_utc: datetime | None

    @property
    def unlimited(self) -> bool:
        return self.free_transfers == "unlimited"


class ScoringRules(_Strict):
    appearance: int
    sixty_minutes: int
    sixty_minutes_threshold: int
    goal: dict[Position, int]
    goal_outside_box_bonus: int
    assist: int
    clean_sheet: dict[Position, int]
    balls_recovered_block: int
    balls_recovered_points: int
    saves_block: int
    saves_points: int
    penalty_save: int
    goals_conceded_block: int
    goals_conceded_points: int
    goals_conceded_positions: list[Position]
    player_of_the_match: int
    penalty_won: int
    penalty_conceded: int
    penalty_missed: int
    yellow_card: int
    red_card: int
    own_goal: int
    captain_multiplier: int


class RegisterEntry(_Strict):
    status: Status
    summary: str
    blocks: str | None = None


class Confirmation(_Strict):
    value: str
    confirmed_on: date
    note: str = ""


class RuleSet(_Strict):
    season: str
    source_url: str
    read_on: date
    squad: SquadRules
    lineup: LineupRules
    stages: dict[str, StageRules]
    transfers: TransferRules
    chips: ChipRules
    manual_changes: ManualChangeRules
    matchdays: dict[int, MatchdayRules]
    scoring: ScoringRules
    rule_register: dict[str, RegisterEntry] = Field(alias="register")
    confirmations: dict[str, Confirmation] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistency(self) -> RuleSet:
        for number, md in self.matchdays.items():
            if md.stage not in self.stages:
                raise ValueError(f"matchday {number} refers to unknown stage {md.stage!r}")
        for rule_id, conf in self.confirmations.items():
            if rule_id not in self.rule_register:
                raise ValueError(f"confirmation for unknown rule {rule_id!r}")
            allowed = CONFIRMABLE_VALUES.get(rule_id)
            if allowed is None:
                raise ValueError(f"rule {rule_id!r} does not take a confirmation value")
            if conf.value not in allowed:
                raise ValueError(
                    f"confirmation for {rule_id!r} must be one of {allowed}, got {conf.value!r}"
                )
        return self

    # -- lookups ---------------------------------------------------------------------

    def matchday(self, number: int) -> MatchdayRules:
        try:
            return self.matchdays[number]
        except KeyError:
            raise ValueError(f"matchday {number} is not defined for season {self.season}") from None

    def stage_for(self, matchday: int) -> StageRules:
        return self.stages[self.matchday(matchday).stage]

    def is_league_phase(self, matchday: int) -> bool:
        return self.matchday(matchday).stage == "league_phase"

    def status(self, rule_id: str) -> Status:
        """Effective status: a user confirmation upgrades an open rule to confirmed."""
        entry = self.rule_register[rule_id]
        if rule_id in self.confirmations:
            return Status.CONFIRMED
        return entry.status

    def confirmed_value(self, rule_id: str) -> str | None:
        """The value the user recorded for an open rule, or None if still unverified."""
        if rule_id not in self.rule_register:
            raise KeyError(rule_id)
        conf = self.confirmations.get(rule_id)
        return conf.value if conf else None


def load_rules(
    rules_path: Path | str = DEFAULT_RULES_PATH,
    confirmations_path: Path | str | None = DEFAULT_CONFIRMATIONS_PATH,
) -> RuleSet:
    """Load the rules file and, if present, the user's confirmations."""
    data = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8"))
    confirmations: dict = {}
    if confirmations_path is not None and Path(confirmations_path).exists():
        loaded = yaml.safe_load(Path(confirmations_path).read_text(encoding="utf-8")) or {}
        confirmations = loaded.get("confirmations") or {}
    data["confirmations"] = confirmations
    return RuleSet.model_validate(data)


def save_confirmation(
    rule_id: str,
    value: str,
    note: str = "",
    *,
    confirmed_on: date | None = None,
    rules_path: Path | str = DEFAULT_RULES_PATH,
    confirmations_path: Path | str = DEFAULT_CONFIRMATIONS_PATH,
) -> RuleSet:
    """Record a rule the user checked in the game, then return the reloaded rule set."""
    allowed = CONFIRMABLE_VALUES.get(rule_id)
    if allowed is None:
        raise ValueError(
            f"{rule_id!r} is not an open rule. Open rules: {', '.join(sorted(CONFIRMABLE_VALUES))}"
        )
    if value not in allowed:
        raise ValueError(f"value for {rule_id!r} must be one of: {', '.join(allowed)}")
    path = Path(confirmations_path)
    existing: dict = {}
    if path.exists():
        existing = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(
            "confirmations"
        ) or {}
    existing[rule_id] = {
        "value": value,
        "confirmed_on": (confirmed_on or date.today()).isoformat(),
        "note": note,
    }
    header = (
        "# Rule confirmations you have made in the game.\n"
        "# Managed by `uclfa rules confirm`. See rules/2026-27.yaml for each rule's summary.\n"
    )
    path.write_text(
        header + yaml.safe_dump({"confirmations": existing}, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    return load_rules(rules_path, path)
