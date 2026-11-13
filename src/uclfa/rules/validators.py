"""Validators for squads, lineups, transfers, chips and between-days changes.

Every check reads its limits from the RuleSet. A rule the official page leaves open is
never assumed: the validator returns a Block naming the rule, and the action stays
blocked until the rule is confirmed in rules/confirmations.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from uclfa.rules.domain import Collector, Player, Result, Role, Squad, SquadSlot
from uclfa.rules.model import Chip, Position, RuleSet

# --------------------------------------------------------------------------------------
# Squad and lineup
# --------------------------------------------------------------------------------------


def validate_squad(
    squad: Squad, matchday: int, rules: RuleSet, *, enforce_club_limit: bool = True
) -> Result:
    """Check squad size, position quotas, duplicates and the club limit for the stage."""
    out = Collector()
    if len(squad.slots) != rules.squad.size:
        out.violate(
            "squad_size",
            f"A squad has {rules.squad.size} players; this one has {len(squad.slots)}.",
            "squad_composition",
        )
    ids = [p.id for p in squad.players]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        names = ", ".join(squad.slot(i).player.name for i in duplicates)  # type: ignore[union-attr]
        out.violate(
            "duplicate_player", f"Player listed more than once: {names}.", "squad_composition"
        )

    counts = squad.position_counts()
    for position, quota in rules.squad.positions.items():
        if counts.get(position, 0) != quota:
            out.violate(
                "position_quota",
                f"A squad needs exactly {quota} {position.value}; this one has "
                f"{counts.get(position, 0)}.",
                "squad_composition",
            )

    limit = rules.stage_for(matchday).club_limit
    over = {club: n for club, n in squad.club_counts().items() if n > limit}
    if over:
        detail = ", ".join(f"{club} ({n})" for club, n in sorted(over.items()))
        message = (
            f"At most {limit} players per club on matchday {matchday}; over the limit: {detail}."
        )
        if enforce_club_limit:
            out.violate("club_limit", message, "club_limit_by_stage")
        else:
            out.note(
                message + " This is allowed only while you make no transfers; the next transfer "
                "must bring the squad back within the limit."
            )
    return out.result()


def validate_lineup(squad: Squad, rules: RuleSet) -> Result:
    """Check the starting eleven, formation, bench order and captain."""
    out = Collector()
    starters, bench = squad.starters, squad.bench
    if len(starters) != rules.lineup.size:
        out.violate(
            "lineup_size",
            f"A lineup has {rules.lineup.size} starters; this one has {len(starters)}.",
            "lineup_formation",
        )
    counts = squad.position_counts(starters)
    for position, exact in rules.lineup.exact.items():
        if counts.get(position, 0) != exact:
            out.violate(
                "formation",
                f"The lineup needs exactly {exact} {position.value}; it has "
                f"{counts.get(position, 0)}.",
                "lineup_formation",
            )
    for position, minimum in rules.lineup.minimum.items():
        if counts.get(position, 0) < minimum:
            out.violate(
                "formation",
                f"The lineup needs at least {minimum} {position.value}; it has "
                f"{counts.get(position, 0)}.",
                "lineup_formation",
            )

    orders = [s.bench_order for s in bench]
    expected = list(range(1, len(bench) + 1))
    if any(o is None for o in orders) or sorted(o for o in orders if o is not None) != expected:
        out.violate(
            "bench_order",
            f"Bench players need distinct orders {expected}; got {orders}.",
            "automatic_substitutions",
        )

    captains = [s for s in squad.slots if s.is_captain]
    if len(captains) != 1:
        out.violate(
            "captain_count",
            f"Exactly one captain is required; found {len(captains)}.",
            "captain_double",
        )
    elif captains[0].role is not Role.STARTER:
        out.violate(
            "captain_not_starter",
            f"The captain ({captains[0].player.name}) must be in the starting eleven.",
            "captain_double",
        )
    return out.result()


# --------------------------------------------------------------------------------------
# Chips
# --------------------------------------------------------------------------------------


def validate_chip(
    chip: Chip,
    matchday: int,
    rules: RuleSet,
    *,
    chips_used: frozenset[Chip] | set[Chip] = frozenset(),
    chip_active_this_matchday: Chip | None = None,
) -> Result:
    """Check that a chip may be played on this matchday."""
    out = Collector()
    rules.matchday(matchday)
    if matchday in rules.chips.blocked_matchdays:
        out.violate(
            "chip_blocked_matchday",
            f"{chip.value.title()} cannot be played on matchday {matchday}.",
            "chips",
        )
    if chip in chips_used:
        out.violate(
            "chip_already_used", f"{chip.value.title()} has already been used this season.", "chips"
        )
    if chip_active_this_matchday is not None and chip_active_this_matchday is not chip:
        value = rules.confirmed_value("two_chips_same_matchday")
        if value is None:
            out.block(
                "two_chips_same_matchday",
                "Whether two chips can be played on one matchday is unverified. Confirm it in "
                "the game before combining them.",
            )
        elif value == "not_allowed":
            out.violate(
                "two_chips_same_matchday",
                "Two chips cannot be played on the same matchday.",
                "two_chips_same_matchday",
            )
    return out.result()


# --------------------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Transfer:
    out_id: str
    incoming: Player
    buy_price: float | None = None  # defaults to the incoming player's current price


@dataclass(frozen=True)
class TransferOutcome:
    result: Result
    squad_after: Squad | None
    transfers_made: int
    free_transfers_available: int | None  # None means unlimited
    paid_transfers: int
    points_cost: int
    bank_after: float | None
    free_transfers_next_matchday: int | str | None


def free_transfer_allowance(matchday: int, rules: RuleSet) -> int | None:
    """Largest number of free transfers anyone can hold for this matchday; None if unlimited."""
    md = rules.matchday(matchday)
    if md.unlimited:
        return None
    assert isinstance(md.free_transfers, int)
    return md.free_transfers + (rules.transfers.league_phase_carry if md.carry_in else 0)


def next_free_transfers(
    matchday: int,
    available: int | None,
    used: int,
    rules: RuleSet,
    *,
    chip_played: bool = False,
) -> int | str | None:
    """Free transfers for the following matchday; None after the last matchday."""
    following = rules.matchdays.get(matchday + 1)
    if following is None:
        return None
    if following.unlimited:
        return "unlimited"
    assert isinstance(following.free_transfers, int)
    base = following.free_transfers
    if following.carry_in and not chip_played and available is not None:
        unused = max(0, available - used)
        base += min(rules.transfers.league_phase_carry, unused)
    return base


def _sale_value(slot: SquadSlot, rules: RuleSet) -> float | None:
    if slot.sale_value is not None:
        return slot.sale_value
    method = rules.confirmed_value("selling_value")
    if method == "current_price":
        return slot.player.price
    if method == "purchase_price":
        return slot.purchase_price
    return None


def validate_transfers(
    squad: Squad,
    transfers: list[Transfer],
    *,
    matchday: int,
    bank: float,
    free_transfers: int | None,
    rules: RuleSet,
    chip: Chip | None = None,
    chips_used: frozenset[Chip] | set[Chip] = frozenset(),
) -> TransferOutcome:
    """Validate a set of transfers and report their cost.

    `free_transfers` is what the game shows you hold now; pass None when the game shows
    unlimited. `bank` is the money remaining, in EUR millions, as the game shows it.
    """
    out = Collector()
    md = rules.matchday(matchday)
    allowance = free_transfer_allowance(matchday, rules)

    if md.unlimited and free_transfers is not None:
        out.note(f"Matchday {matchday} has unlimited free transfers; the number given is ignored.")
        free_transfers = None
    if not md.unlimited:
        if free_transfers is None:
            out.violate(
                "free_transfers_missing",
                f"Matchday {matchday} does not have unlimited transfers; enter how many you hold.",
                "free_transfers_table",
            )
            free_transfers = 0
        elif allowance is not None and not 0 <= free_transfers <= allowance:
            out.violate(
                "free_transfers_out_of_range",
                f"You can hold between 0 and {allowance} free transfers for matchday {matchday}; "
                f"got {free_transfers}.",
                "transfer_carry",
            )

    if chip is not None:
        out.extend(validate_chip(chip, matchday, rules, chips_used=chips_used))
    effect = rules.chips.effect(chip) if chip is not None else None

    working = squad
    bank_after = bank
    seen_out: set[str] = set()
    seen_in: set[str] = set()
    for t in transfers:
        slot = working.slot(t.out_id)
        if slot is None or t.out_id in seen_out:
            out.violate(
                "transfer_out_not_in_squad",
                f"Player {t.out_id!r} is not in the squad, or is transferred out twice.",
                "squad_composition",
            )
            continue
        if squad.slot(t.incoming.id) is not None or t.incoming.id in seen_in:
            out.violate(
                "transfer_in_already_owned",
                f"{t.incoming.name} is already in the squad or bought twice.",
                "squad_composition",
            )
            continue
        seen_out.add(t.out_id)
        seen_in.add(t.incoming.id)

        buy = t.buy_price if t.buy_price is not None else t.incoming.price
        sale = _sale_value(slot, rules)
        if buy is None:
            out.violate(
                "price_missing",
                f"No price entered for {t.incoming.name}; enter it from the game.",
                "budget_by_stage",
            )
        if sale is None:
            out.block(
                "selling_value",
                f"The sale value of {slot.player.name} is not known. Enter the value the game "
                "shows, or confirm the selling-value rule.",
            )
        if buy is not None and sale is not None:
            bank_after = round(bank_after + sale - buy, 2)

        incoming_slot = SquadSlot(
            player=t.incoming,
            role=slot.role,
            bench_order=slot.bench_order,
            is_captain=slot.is_captain,
            purchase_price=buy,
            sale_value=None,
        )
        working = working.replacing(t.out_id, incoming_slot)

    made = len(seen_out)
    out.extend(validate_squad(working, matchday, rules, enforce_club_limit=made > 0))

    budget_applies = effect.budget_applies if effect is not None else True
    money_known = not any(b.rule_id == "selling_value" for b in out.blocks) and not any(
        v.code == "price_missing" for v in out.violations
    )
    if not budget_applies:
        bank_after = bank  # Limitless: the pre-chip squad and bank return afterwards
        out.note(
            "Limitless: no budget applies for this matchday. Re-confirm your squad and bank "
            "from the game once it has reverted."
        )
    elif money_known and bank_after < 0:
        out.violate(
            "over_budget",
            f"These transfers leave the bank at {bank_after:.1f}m; it cannot be negative.",
            "budget_by_stage",
        )

    free_now = None if (md.unlimited or chip is not None) else free_transfers
    paid = 0 if free_now is None else max(0, made - free_now)
    cost = paid * rules.transfers.hit_cost
    if paid:
        out.note(
            f"{paid} transfer(s) beyond your free allowance: {cost} points are deducted from "
            "your overall total."
        )
    if made == 0:
        out.note("No transfers: the squad is unchanged and no points are deducted.")

    nxt = next_free_transfers(
        matchday,
        None if md.unlimited else free_transfers,
        made,
        rules,
        chip_played=chip is not None,
    )
    result = out.result()
    return TransferOutcome(
        result=result,
        squad_after=working if not result.violations else None,
        transfers_made=made,
        free_transfers_available=free_now,
        paid_transfers=paid,
        points_cost=cost,
        bank_after=bank_after if money_known else None,
        free_transfers_next_matchday=nxt,
    )


# --------------------------------------------------------------------------------------
# Between playing days
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BreakContext:
    """What is known in the break between two playing days of one matchday."""

    matchday: int
    played_ids: frozenset[str]  # squad players whose team has already played
    sent_off_ids: frozenset[str] = frozenset()
    previous_captain_ids: frozenset[str] = frozenset()  # captains given up earlier this matchday
    next_day_started: bool = False  # the next playing day's first match has kicked off


@dataclass(frozen=True)
class Substitution:
    out_id: str
    in_id: str


@dataclass(frozen=True)
class BreakOutcome:
    result: Result
    squad_after: Squad | None
    automatic_substitutions_disabled: bool


def validate_between_days(
    squad: Squad,
    substitutions: list[Substitution],
    new_captain_id: str | None,
    ctx: BreakContext,
    rules: RuleSet,
) -> BreakOutcome:
    """Validate manual substitutions and a captain switch made between playing days."""
    out = Collector()
    md = rules.matchday(ctx.matchday)
    changing = bool(substitutions) or new_captain_id is not None

    if changing and not md.mid_matchday_changes:
        out.violate(
            "no_mid_matchday_changes",
            f"Matchday {ctx.matchday} allows no substitutions or captain changes once it starts.",
            "mid_matchday_changes_excluded",
        )
    if changing and ctx.next_day_started:
        value = rules.confirmed_value("late_changes_after_kickoff")
        if value is None:
            out.block(
                "late_changes_after_kickoff",
                "The next playing day has started. Whether changes are still accepted is "
                "unverified; confirm it in the game.",
            )
        elif value == "not_allowed":
            out.violate(
                "window_closed",
                "The next playing day has started; changes are no longer accepted.",
                "late_changes_after_kickoff",
            )

    limit = rules.manual_changes.max_substitutions_per_break
    if len(substitutions) > limit:
        out.violate(
            "too_many_substitutions",
            f"At most {limit} manual substitutions per break; {len(substitutions)} proposed.",
            "manual_substitutions",
        )

    working = squad
    brought_on: set[str] = set()
    touched: set[str] = set()
    for sub in substitutions:
        leaving, entering = working.slot(sub.out_id), working.slot(sub.in_id)
        if leaving is None or entering is None:
            out.violate(
                "substitution_unknown_player",
                "Both players of a substitution must be in the squad "
                f"({sub.out_id} for {sub.in_id}).",
                "manual_substitutions",
            )
            continue
        if sub.out_id in touched or sub.in_id in touched:
            out.violate(
                "substitution_repeated_player",
                f"{leaving.player.name} or {entering.player.name} appears in two substitutions.",
                "manual_substitutions",
            )
            continue
        touched.update((sub.out_id, sub.in_id))
        if leaving.role is not Role.STARTER:
            out.violate(
                "substitution_out_not_starter",
                f"{leaving.player.name} is not in the starting eleven.",
                "manual_substitutions",
            )
            continue
        if entering.role is not Role.BENCH:
            out.violate(
                "substitution_in_not_bench",
                f"{entering.player.name} is not on the bench.",
                "manual_substitutions",
            )
            continue
        if sub.out_id in ctx.sent_off_ids:
            out.violate(
                "substitution_out_sent_off",
                f"{leaving.player.name} was sent off and cannot be substituted out.",
                "manual_substitutions",
            )
        if sub.in_id in ctx.played_ids:
            out.violate(
                "substitution_in_already_played",
                f"{entering.player.name}'s team has already played; he cannot be brought on.",
                "manual_substitutions",
            )
        if Position.GK in (leaving.player.position, entering.player.position):
            value = rules.confirmed_value("goalkeeper_manual_substitution")
            if value is None:
                out.block(
                    "goalkeeper_manual_substitution",
                    "Whether the goalkeeper can be substituted between playing days is "
                    "unverified; confirm it in the game.",
                )
            elif value == "not_allowed":
                out.violate(
                    "goalkeeper_substitution",
                    "The goalkeeper cannot be substituted between playing days.",
                    "goalkeeper_manual_substitution",
                )
        if sub.out_id in ctx.played_ids:
            out.note(f"{leaving.player.name} has played: his points for this matchday become 0.")

        working = working.with_slot(
            replace(leaving, role=Role.BENCH, bench_order=entering.bench_order, is_captain=False)
        ).with_slot(replace(entering, role=Role.STARTER, bench_order=None, is_captain=False))
        if leaving.is_captain and new_captain_id is None:
            out.violate(
                "captain_substituted_out",
                f"{leaving.player.name} is the captain; choose a new captain when taking him off.",
                "captain_double",
            )
        brought_on.add(sub.in_id)

    if new_captain_id is not None:
        candidate = working.slot(new_captain_id)
        current = squad.captain
        if candidate is None or candidate.role is not Role.STARTER:
            out.violate(
                "captain_not_starter",
                "The new captain must be in the starting eleven.",
                "captain_switch",
            )
        else:
            if current is not None and current.player.id == new_captain_id:
                out.violate(
                    "captain_unchanged",
                    f"{candidate.player.name} is already the captain.",
                    "captain_switch",
                )
            if new_captain_id in ctx.played_ids:
                out.violate(
                    "captain_already_played",
                    f"{candidate.player.name}'s team has already played; "
                    "he cannot be made captain.",
                    "captain_switch",
                )
            if new_captain_id in ctx.previous_captain_ids:
                out.violate(
                    "captain_switch_back",
                    f"{candidate.player.name} was captain earlier this matchday; the armband "
                    "cannot move back.",
                    "captain_switch",
                )
            if new_captain_id in brought_on:
                value = rules.confirmed_value("captain_on_substituted_in")
                if value is None:
                    out.block(
                        "captain_on_substituted_in",
                        "Whether a player you have just brought on can be made captain is "
                        "unverified; confirm it in the game.",
                    )
                elif value == "not_allowed":
                    out.violate(
                        "captain_on_substituted_in",
                        "A player brought on in this break cannot be made captain.",
                        "captain_on_substituted_in",
                    )
            working = Squad(
                tuple(replace(s, is_captain=s.player.id == new_captain_id) for s in working.slots)
            )

    if changing:
        formation = validate_lineup(working, rules)
        out.violations.extend(v for v in formation.violations if v.code != "captain_count")
        if working.captain is None and not any(
            v.code == "captain_substituted_out" for v in out.violations
        ):
            out.violate(
                "captain_count",
                "Exactly one captain is required after the changes.",
                "captain_double",
            )
        out.note(
            "Any manual change disables automatic substitutions for the rest of this matchday, "
            "even if you reverse it."
        )

    result = out.result()
    return BreakOutcome(
        result=result,
        squad_after=working if not result.violations else None,
        automatic_substitutions_disabled=changing,
    )
