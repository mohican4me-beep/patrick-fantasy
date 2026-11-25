"""Choices judged over the coming matchdays (Release 2 Phase E).

Each matchday uses the odds when bookmakers have priced it, otherwise a projection from
team ratings (service.match_outlook_view). A squad's value in a matchday is its best
lineup plus captain from the players' expected points. A move is judged against keeping
the squad as it is, over every matchday up to the end of the stretch, with the transfer
cost from the rules engine. Everything here is an analyst estimate; the decision is
Patrick's.
"""

from __future__ import annotations

import dataclasses
import itertools
from dataclasses import dataclass, field
from typing import Any

from uclfa.rules import validators as v
from uclfa.rules.domain import Player, Squad
from uclfa.rules.model import Position, RuleSet

OUTFIELD = (Position.DEF, Position.MID, Position.FWD)


@dataclass
class Lineup:
    points: float  # starters plus the captain's extra
    starters: list[str]
    captain: str | None
    unknown: list[str] = field(default_factory=list)  # players with no estimate (counted as 0)


def best_lineup(
    players: list[tuple[str, Position]], xp: dict[str, float | None], rules: RuleSet
) -> Lineup:
    """Best legal eleven and captain, by enumerating formations. Unknown players count 0."""
    value = {name: (xp.get(name) or 0.0) for name, _ in players}
    by_pos = {
        pos: sorted((n for n, p in players if p is pos), key=lambda n: -value[n])
        for pos in Position
    }
    outfield = rules.lineup.size - rules.lineup.exact.get(Position.GK, 1)
    ranges = [
        range(rules.lineup.minimum.get(pos, 0), rules.squad.positions[pos] + 1) for pos in OUTFIELD
    ]
    best: Lineup | None = None
    for counts in itertools.product(*ranges):
        if sum(counts) != outfield:
            continue
        chosen = by_pos[Position.GK][: rules.lineup.exact.get(Position.GK, 1)]
        for pos, k in zip(OUTFIELD, counts, strict=True):
            if len(by_pos[pos]) < k:
                break
            chosen = chosen + by_pos[pos][:k]
        else:
            captain = max(chosen, key=lambda n: value[n])
            total = sum(value[n] for n in chosen) + value[captain] * (
                rules.scoring.captain_multiplier - 1
            )
            if best is None or total > best.points:
                best = Lineup(round(total, 2), chosen, captain)
    if best is None:
        raise ValueError("No legal lineup from this squad")
    best.unknown = [n for n, _ in players if xp.get(n) is None]
    return best


def free_transfers_at(state: Any, matchday: int, rules: RuleSet) -> int | str | None:
    """Free transfers at `matchday` if none are used before it (rules engine).

    A saved state labelled with a chip (e.g. md05-2-wildcard) played that chip on its own
    matchday, so nothing carries into the next one."""
    available: int | str | None = state.free_transfers
    if state.matchday >= matchday:
        return available
    chip = any(c.value in state.label for c in state.chips_used)
    for md in range(state.matchday, matchday):
        current = None if available in (None, "unlimited") else int(available)
        available = v.next_free_transfers(md, current, 0, rules, chip_played=chip)
        chip = False
    return available


@dataclass
class Evaluation:
    matchdays: list[int]
    keep: list[Lineup]
    move: list[Lineup]
    gain_by_matchday: list[float]
    hit_points: int
    net_gain: float
    status: str
    messages: list[str]
    bank_after: float | None
    free_transfers: int | str | None
    sources: dict[int, str]
    player_rows: dict[str, list[float | None]]


def evaluate_move(
    state: Any,
    outs: list[str],
    ins: list[dict[str, Any]],
    matchday: int,
    xp_by_md: dict[int, dict[str, float | None]],
    sources: dict[int, str],
    rules: RuleSet,
) -> Evaluation:
    """Compare keeping the squad with making the transfers at `matchday`, over every
    matchday in `xp_by_md`. `ins` are dicts with name, club, position, price."""
    slots = {sl.player.name: sl for sl in state.squad.slots}
    missing = [n for n in outs if n not in slots]
    if missing:
        raise ValueError(f"Not in the squad: {missing}")
    if len(outs) != len(ins):
        raise ValueError("Give one player in for each player out")
    free = free_transfers_at(state, matchday, rules)
    if free is None:
        free = "unlimited"
    transfers = [
        v.Transfer(
            out_id=slots[o].player.id,
            incoming=Player(
                id=f"new:{i['name']}",
                name=i["name"],
                club=i["club"],
                position=Position(i["position"]),
                price=float(i["price"]),
            ),
        )
        for o, i in zip(outs, ins, strict=True)
    ]
    outcome = v.validate_transfers(
        state.squad,
        transfers,
        matchday=matchday,
        bank=state.bank,
        free_transfers=None if free == "unlimited" else free,
        rules=rules,
        chip=None,
        chips_used=state.chips_used,
    )
    messages = [m.message for m in outcome.result.violations] + [
        b.message for b in outcome.result.blocks
    ]
    keep_players = [(sl.player.name, sl.player.position) for sl in state.squad.slots]
    move_players = [p for p in keep_players if p[0] not in outs] + [
        (i["name"], Position(i["position"])) for i in ins
    ]
    mds = sorted(xp_by_md)
    keep = [best_lineup(keep_players, xp_by_md[md], rules) for md in mds]
    move = [best_lineup(move_players, xp_by_md[md], rules) for md in mds]
    gains = [round(b.points - a.points, 2) for a, b in zip(keep, move, strict=True)]
    names = outs + [i["name"] for i in ins]
    return Evaluation(
        matchdays=mds,
        keep=keep,
        move=move,
        gain_by_matchday=gains,
        hit_points=outcome.points_cost,
        net_gain=round(sum(gains) - outcome.points_cost, 2),
        status=str(outcome.result.status),
        messages=messages,
        bank_after=outcome.bank_after,
        free_transfers=free,
        sources=sources,
        player_rows={n: [xp_by_md[md].get(n) for md in mds] for n in names},
    )


def canonical_state(state: Any, resolve: Any) -> Any:
    """The state with club names in one spelling, so the club limit compares like with like."""
    slots = tuple(
        dataclasses.replace(
            sl,
            player=dataclasses.replace(sl.player, club=resolve(sl.player.club) or sl.player.club),
        )
        for sl in state.squad.slots
    )
    return dataclasses.replace(state, squad=Squad(slots))
