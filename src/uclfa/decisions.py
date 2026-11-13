"""Between-days decision calculators: captain switch and manual substitutions.

These are calculators, not predictions. Every expected-points figure is supplied by the
caller (Patrick or Claude) and is an analyst estimate; so is every result built on one.
Realised points are whatever the game shows after a playing day.

The arithmetic follows the rules file:

* A captain scores his points times the captain multiplier. Moving the armband leaves the
  old captain his single points and doubles the new one, so the gain from switching is
  (multiplier - 1) x (new captain's expected points - old captain's points).
* A player substituted out scores 0 for the matchday, so a swap gains the incoming
  player's expected points minus the points given up.
* Any manual change switches automatic substitutions off. That cost is charged once,
  however many changes are made.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from uclfa.rules.model import RuleSet

ESTIMATE = "analyst_estimate"
ENTERED = "entered"

COMMON_ASSUMPTIONS = (
    "Expected points are analyst estimates supplied by the caller, not model output.",
    "The decision is judged on expected points only; variance and mini-league position "
    "are not considered.",
    "Legality is not checked here: confirm the change with the between-days validator.",
)


@dataclass(frozen=True)
class AutoSubRisk:
    """A later starter who might not play, and what the bench would have covered."""

    player: str
    probability_not_playing: float
    replacement_expected_points: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability_not_playing <= 1.0:
            raise ValueError("probability_not_playing must be between 0 and 1")

    @property
    def expected_loss(self) -> float:
        return self.probability_not_playing * self.replacement_expected_points


def automatic_substitution_cost(
    risks: list[AutoSubRisk] | tuple[AutoSubRisk, ...], *, already_disabled: bool = False
) -> float:
    """Expected points lost by switching automatic substitutions off.

    Approximation: each risk is treated separately, so two absent starters competing for
    the same bench player, and formation limits, are ignored. If automatic substitutions
    are already off this matchday, nothing more is lost.
    """
    if already_disabled:
        return 0.0
    return round(sum(r.expected_loss for r in risks), 4)


# -- captain -------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptainCandidate:
    name: str
    expected_points: float


@dataclass(frozen=True)
class CaptainDecision:
    current_captain_points: float
    automatic_substitution_cost: float
    break_even_expected_points: float
    gains: dict[str, float]
    best_candidate: str | None
    best_gain: float | None
    recommendation: str  # "keep" or "switch"
    tag: str = ESTIMATE
    estimate_author: str = "unknown"
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        if self.best_candidate is None:
            return "No candidate supplied: keep the current captain."
        verb = (
            "Switch to" if self.recommendation == "switch" else "Keep the captain; best alternative"
        )
        return (
            f"{verb} {self.best_candidate}: expected gain from switching "
            f"{self.best_gain:+.2f} points. Break-even: a candidate must be expected to "
            f"score more than {self.break_even_expected_points:.2f}."
        )


def captain_switch_value(
    current_captain_points: float,
    candidates: list[CaptainCandidate],
    rules: RuleSet,
    *,
    auto_sub_risks: list[AutoSubRisk] | tuple[AutoSubRisk, ...] = (),
    automatic_substitutions_already_disabled: bool = False,
    estimate_author: str = "unknown",
) -> CaptainDecision:
    """Value of moving the armband from a captain who has played to a later starter."""
    bonus = rules.scoring.captain_multiplier - 1
    cost = automatic_substitution_cost(
        auto_sub_risks, already_disabled=automatic_substitutions_already_disabled
    )
    gains = {
        c.name: round(bonus * (c.expected_points - current_captain_points) - cost, 4)
        for c in candidates
    }
    break_even = round(current_captain_points + (cost / bonus if bonus else 0.0), 4)
    best = max(gains, key=lambda name: gains[name]) if gains else None
    best_gain = gains[best] if best is not None else None
    # A tie is a keep: the switch cannot be undone and gains nothing.
    recommendation = "switch" if best_gain is not None and best_gain > 0 else "keep"
    assumptions = COMMON_ASSUMPTIONS + (
        "The current captain's points are final for this matchday.",
        "The switch cannot be reversed once made.",
        (
            "Automatic substitutions are already off, so no further cost is charged."
            if automatic_substitutions_already_disabled
            else f"Switching turns automatic substitutions off; estimated cost {cost:.2f} points."
        ),
    )
    return CaptainDecision(
        current_captain_points=current_captain_points,
        automatic_substitution_cost=cost,
        break_even_expected_points=break_even,
        gains=gains,
        best_candidate=best,
        best_gain=best_gain,
        recommendation=recommendation,
        estimate_author=estimate_author,
        assumptions=assumptions,
    )


# -- substitutions -------------------------------------------------------------------


@dataclass(frozen=True)
class Swap:
    """One proposed substitution.

    Give out_realised_points if the outgoing player has played (those points are lost),
    or out_expected_points if he is still to play. Exactly one of the two.
    """

    out_name: str
    in_name: str
    in_expected_points: float
    out_realised_points: float | None = None
    out_expected_points: float | None = None
    out_is_captain: bool = False

    def __post_init__(self) -> None:
        if (self.out_realised_points is None) == (self.out_expected_points is None):
            raise ValueError(
                f"{self.out_name}: give exactly one of out_realised_points or out_expected_points"
            )

    @property
    def out_has_played(self) -> bool:
        return self.out_realised_points is not None

    @property
    def out_value(self) -> float:
        value = self.out_realised_points if self.out_has_played else self.out_expected_points
        assert value is not None
        return value


@dataclass(frozen=True)
class SwapValue:
    out_name: str
    in_name: str
    points_given_up: float
    points_given_up_tag: str
    in_expected_points: float
    gain: float


@dataclass(frozen=True)
class SubstitutionDecision:
    swaps: tuple[SwapValue, ...]
    automatic_substitution_cost: float
    recommended: tuple[str, ...]  # "Out -> In" for each swap worth making
    net_gain_if_recommended: float
    recommendation: str  # "make" or "none"
    tag: str = ESTIMATE
    estimate_author: str = "unknown"
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        if self.recommendation == "none":
            return (
                "Make no substitution: no combination is expected to gain after the "
                f"automatic-substitution cost of {self.automatic_substitution_cost:.2f}."
            )
        return (
            f"Make {len(self.recommended)} substitution(s): {'; '.join(self.recommended)}. "
            f"Expected net gain {self.net_gain_if_recommended:+.2f} points."
        )


def substitution_value(
    swaps: list[Swap],
    rules: RuleSet,
    *,
    auto_sub_risks: list[AutoSubRisk] | tuple[AutoSubRisk, ...] = (),
    automatic_substitutions_already_disabled: bool = False,
    estimate_author: str = "unknown",
) -> SubstitutionDecision:
    """Value of manual substitutions between playing days."""
    multiplier = rules.scoring.captain_multiplier
    limit = rules.manual_changes.max_substitutions_per_break
    cost = automatic_substitution_cost(
        auto_sub_risks, already_disabled=automatic_substitutions_already_disabled
    )
    values = []
    captain_out = False
    for s in swaps:
        given_up = s.out_value * (multiplier if s.out_is_captain else 1)
        captain_out = captain_out or s.out_is_captain
        values.append(
            SwapValue(
                out_name=s.out_name,
                in_name=s.in_name,
                points_given_up=round(given_up, 4),
                points_given_up_tag=ENTERED if s.out_has_played else ESTIMATE,
                in_expected_points=s.in_expected_points,
                gain=round(s.in_expected_points - given_up, 4),
            )
        )
    worthwhile = sorted((v for v in values if v.gain > 0), key=lambda v: v.gain, reverse=True)
    chosen = worthwhile[:limit]
    net = round(sum(v.gain for v in chosen) - cost, 4) if chosen else 0.0
    make = bool(chosen) and net > 0
    assumptions = COMMON_ASSUMPTIONS + (
        "A player substituted out scores 0 for the matchday; his realised points are lost.",
        f"At most {limit} substitutions can be made in one break.",
        (
            "Automatic substitutions are already off, so no further cost is charged."
            if automatic_substitutions_already_disabled
            else f"Any substitution turns automatic substitutions off; estimated cost {cost:.2f} "
            "points, charged once."
        ),
    )
    if captain_out:
        assumptions += (
            "A captain taken off loses his doubled points; the new captain's bonus is not "
            "included here. Value it with the captain calculator.",
        )
    return SubstitutionDecision(
        swaps=tuple(values),
        automatic_substitution_cost=cost,
        recommended=tuple(f"{v.out_name} -> {v.in_name}" for v in chosen) if make else (),
        net_gain_if_recommended=net if make else 0.0,
        recommendation="make" if make else "none",
        estimate_author=estimate_author,
        assumptions=assumptions,
    )
