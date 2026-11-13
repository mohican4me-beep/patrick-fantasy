"""Plain data types shared by the validators, the database layer and the command line."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from enum import StrEnum

from uclfa.rules.model import Position


class Role(StrEnum):
    STARTER = "starter"
    BENCH = "bench"


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    club: str
    position: Position
    price: float | None = None  # current price in EUR millions, as entered from the game


@dataclass(frozen=True)
class SquadSlot:
    player: Player
    role: Role
    bench_order: int | None = None
    is_captain: bool = False
    purchase_price: float | None = None
    sale_value: float | None = None  # value the game shows for selling, if you have entered it


@dataclass(frozen=True)
class Squad:
    slots: tuple[SquadSlot, ...]

    @property
    def players(self) -> list[Player]:
        return [s.player for s in self.slots]

    @property
    def starters(self) -> list[SquadSlot]:
        return [s for s in self.slots if s.role is Role.STARTER]

    @property
    def bench(self) -> list[SquadSlot]:
        return sorted(
            (s for s in self.slots if s.role is Role.BENCH), key=lambda s: s.bench_order or 99
        )

    @property
    def captain(self) -> SquadSlot | None:
        captains = [s for s in self.slots if s.is_captain]
        return captains[0] if len(captains) == 1 else None

    def slot(self, player_id: str) -> SquadSlot | None:
        for s in self.slots:
            if s.player.id == player_id:
                return s
        return None

    def position_counts(self, slots: list[SquadSlot] | None = None) -> Counter[Position]:
        return Counter(s.player.position for s in (self.slots if slots is None else slots))

    def club_counts(self) -> Counter[str]:
        return Counter(s.player.club for s in self.slots)

    def replacing(self, out_id: str, incoming: SquadSlot) -> Squad:
        return Squad(tuple(incoming if s.player.id == out_id else s for s in self.slots))

    def with_slot(self, updated: SquadSlot) -> Squad:
        return self.replacing(updated.player.id, updated)


@dataclass(frozen=True)
class Violation:
    """A rule that the proposed squad, lineup or action breaks."""

    code: str
    message: str
    rule_id: str


@dataclass(frozen=True)
class Block:
    """An action that cannot be assessed because a rule it depends on is unverified."""

    rule_id: str
    message: str


@dataclass(frozen=True)
class Result:
    violations: tuple[Violation, ...] = ()
    blocks: tuple[Block, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if self.violations:
            return "invalid"
        if self.blocks:
            return "blocked"
        return "valid"

    @property
    def ok(self) -> bool:
        return self.status == "valid"

    def codes(self) -> set[str]:
        return {v.code for v in self.violations}

    def blocked_rules(self) -> set[str]:
        return {b.rule_id for b in self.blocks}

    def merged(self, other: Result) -> Result:
        return Result(
            self.violations + other.violations, self.blocks + other.blocks, self.notes + other.notes
        )


@dataclass
class Collector:
    """Accumulates findings while a validator runs."""

    violations: list[Violation] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def violate(self, code: str, message: str, rule_id: str) -> None:
        self.violations.append(Violation(code, message, rule_id))

    def block(self, rule_id: str, message: str) -> None:
        self.blocks.append(Block(rule_id, message))

    def note(self, message: str) -> None:
        self.notes.append(message)

    def extend(self, result: Result) -> None:
        self.violations.extend(result.violations)
        self.blocks.extend(result.blocks)
        self.notes.extend(result.notes)

    def result(self) -> Result:
        return Result(tuple(self.violations), tuple(self.blocks), tuple(self.notes))


__all__ = [
    "Block",
    "Collector",
    "Player",
    "Result",
    "Role",
    "Squad",
    "SquadSlot",
    "Violation",
    "replace",
]
