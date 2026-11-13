"""Rules engine: versioned rules, validators and official scoring."""

from uclfa.rules.domain import Block, Player, Result, Role, Squad, SquadSlot, Violation
from uclfa.rules.model import Chip, Position, RuleSet, Status, load_rules, save_confirmation
from uclfa.rules.scoring import MatchEvents, ScoreBreakdown, captain_points, score_player
from uclfa.rules.validators import (
    BreakContext,
    BreakOutcome,
    Substitution,
    Transfer,
    TransferOutcome,
    free_transfer_allowance,
    next_free_transfers,
    validate_between_days,
    validate_chip,
    validate_lineup,
    validate_squad,
    validate_transfers,
)

__all__ = [
    "Block",
    "BreakContext",
    "BreakOutcome",
    "Chip",
    "MatchEvents",
    "Player",
    "Position",
    "Result",
    "Role",
    "RuleSet",
    "ScoreBreakdown",
    "Squad",
    "SquadSlot",
    "Status",
    "Substitution",
    "Transfer",
    "TransferOutcome",
    "Violation",
    "captain_points",
    "free_transfer_allowance",
    "load_rules",
    "next_free_transfers",
    "save_confirmation",
    "score_player",
    "validate_between_days",
    "validate_chip",
    "validate_lineup",
    "validate_squad",
    "validate_transfers",
]
