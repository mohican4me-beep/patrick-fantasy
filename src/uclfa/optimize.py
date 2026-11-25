"""Squad optimizer (Release 2 Phase D): best squad, lineup and captain for one matchday.

Integer programme (scipy's HiGHS) over the player pool: maximise expected points of the
starting eleven, the captain's extra share, a small weight on the bench, minus points for
paid transfers. Game constraints come from the rules file; every plan is then passed
through the rules engine before it is returned. All numbers are analyst estimates.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict
from scipy.optimize import Bounds, LinearConstraint, milp

from uclfa.model.match import DEFAULT_SETTINGS_PATH
from uclfa.rules import validators as v
from uclfa.rules.domain import Player, Role, Squad, SquadSlot
from uclfa.rules.model import Chip, Position, RuleSet

POSITIONS = (Position.GK, Position.DEF, Position.MID, Position.FWD)


class OptimizerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bench_weight: float
    max_transfers: int
    wildcard_margin: float
    verdict_margin: float = 2.0


def load_optimizer_settings(path=DEFAULT_SETTINGS_PATH) -> OptimizerSettings:  # noqa: ANN001
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return OptimizerSettings.model_validate(data["optimizer"])


@dataclass(frozen=True)
class Candidate:
    name: str
    club: str  # canonical club name, for the club limit
    position: Position
    price: float  # buy price, or sale value if owned
    xp: float  # expected points; 0 when unknown (owned players only)
    owned: bool
    known: bool  # False when the model has no number for him
    price_tag: str


@dataclass
class Plan:
    label: str
    chip: Chip | None
    transfers_out: list[str]
    transfers_in: list[str]
    starters: list[str]
    bench: list[str]  # goalkeeper first, then outfield in order
    captain: str
    expected_points: float  # starters + captain extra, before hits
    hit_points: int
    net_points: float
    bank_after: float
    status: str  # valid / invalid / blocked, from the rules engine
    messages: list[str] = field(default_factory=list)
    unknown_starters: list[str] = field(default_factory=list)


def _solve(
    cands: list[Candidate],
    rules: RuleSet,
    matchday: int,
    budget: float,
    s: OptimizerSettings,
    exact_transfers: int | None,
    force_out: frozenset[str] = frozenset(),
) -> tuple[list[int], list[int], int] | None:
    """Return (squad indices, starter indices, captain index), or None if infeasible."""
    xp = np.array([c.xp for c in cands])
    sol = _solve_multi(cands, [xp], rules, matchday, budget, s, exact_transfers, force_out)
    if sol is None:
        return None
    squad, starters, captains = sol
    return squad, starters[0], captains[0]


def _solve_multi(
    cands: list[Candidate],
    xp_cols: list[np.ndarray],
    rules: RuleSet,
    matchday: int,
    budget: float,
    s: OptimizerSettings,
    exact_transfers: int | None,
    force_out: frozenset[str] = frozenset(),
) -> tuple[list[int], list[list[int]], list[int]] | None:
    """One squad for several matchdays, with its own lineup and captain in each.

    Variables: x (squad), then for each matchday y (starters) and c (captain). Returns
    (squad indices, starters per matchday, captain per matchday) or None if infeasible."""
    n, h = len(cands), len(xp_cols)
    size = n * (1 + 2 * h)

    def y(m: int, i: int) -> int:
        return n + 2 * m * n + i

    def c(m: int, i: int) -> int:
        return n + (2 * m + 1) * n + i

    obj = np.zeros(size)
    for m, xp in enumerate(xp_cols):
        obj[:n] -= s.bench_weight * xp
        obj[y(m, 0) : y(m, 0) + n] -= (1 - s.bench_weight) * xp
        obj[c(m, 0) : c(m, 0) + n] -= xp
    rows, lo, hi = [], [], []

    def add(coefs: dict[int, float], low: float, high: float) -> None:
        row = np.zeros(size)
        for k, val in coefs.items():
            row[k] = val
        rows.append(row)
        lo.append(low)
        hi.append(high)

    for pos in POSITIONS:
        idx = [i for i, cand in enumerate(cands) if cand.position is pos]
        add({i: 1 for i in idx}, rules.squad.positions[pos], rules.squad.positions[pos])
        for m in range(h):
            starters = {y(m, i): 1 for i in idx}
            if pos in rules.lineup.exact:
                add(starters, rules.lineup.exact[pos], rules.lineup.exact[pos])
            else:
                add(starters, rules.lineup.minimum.get(pos, 0), np.inf)
    for m in range(h):
        for i in range(n):
            add({y(m, i): 1, i: -1}, -np.inf, 0)  # starter only if in squad
            add({c(m, i): 1, y(m, i): -1}, -np.inf, 0)  # captain only if starter
        add({y(m, i): 1 for i in range(n)}, rules.lineup.size, rules.lineup.size)
        add({c(m, i): 1 for i in range(n)}, 1, 1)
    add({i: cand.price for i, cand in enumerate(cands)}, -np.inf, budget + 1e-6)
    limit = rules.stages[rules.matchday(matchday).stage].club_limit
    for club in {cand.club for cand in cands}:
        add({i: 1 for i, cand in enumerate(cands) if cand.club == club}, -np.inf, limit)
    if exact_transfers is not None:
        add(
            {i: 1 for i, cand in enumerate(cands) if not cand.owned},
            exact_transfers,
            exact_transfers,
        )
    # Never buy a player the model cannot value; never keep a forced sale.
    upper = np.ones(size)
    for i, cand in enumerate(cands):
        if (not cand.known and not cand.owned) or cand.name in force_out:
            upper[i] = 0
            for m in range(h):
                upper[y(m, i)] = upper[c(m, i)] = 0
    res = milp(
        obj,
        constraints=LinearConstraint(np.array(rows), lo, hi),
        integrality=np.ones(size),
        bounds=Bounds(np.zeros(size), upper),
    )
    if not res.success:
        return None
    x = res.x.round().astype(int)
    squad = [i for i in range(n) if x[i]]
    starters = [[i for i in range(n) if x[y(m, i)]] for m in range(h)]
    captains = [next(i for i in range(n) if x[c(m, i)]) for m in range(h)]
    return squad, starters, captains


def optimise_horizon(
    cands: list[Candidate],
    xp_by_md: dict[int, dict[str, float | None]],
    state: Any,
    rules: RuleSet,
    s: OptimizerSettings,
    free_transfers: int | None,
    force_out: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Best transfers at the first matchday of `xp_by_md`, held to its last, judged on the
    sum of each matchday's best lineup. One plan per number of transfers, each checked by
    the rules engine. Transfers in later matchdays are not planned here."""
    mds = sorted(xp_by_md)
    first = mds[0]
    cols = [np.array([xp_by_md[md].get(c.name) or 0.0 for c in cands]) for md in mds]
    known = {c.name for c in cands if all(xp_by_md[md].get(c.name) is not None for md in mds)}
    cands = [dataclasses.replace(c, known=c.name in known) for c in cands]
    budget = state.bank + sum(c.price for c in cands if c.owned)
    plans = []
    for k in range(0, s.max_transfers + 1):
        sol = _solve_multi(cands, cols, rules, first, budget, s, k, force_out)
        if sol is None:
            continue
        squad_idx, starters, captains = sol
        chosen = {cands[i].name for i in squad_idx}
        owned = {sl.player.name: sl for sl in state.squad.slots}
        outs = sorted(set(owned) - chosen)
        ins = [cands[i] for i in squad_idx if not cands[i].owned]
        pool = {p: [c for c in ins if c.position is p] for p in POSITIONS}
        transfers = []
        for name in outs:
            incoming = pool[owned[name].player.position].pop(0)
            transfers.append(
                v.Transfer(
                    out_id=owned[name].player.id,
                    incoming=Player(
                        id=f"new:{incoming.name}",
                        name=incoming.name,
                        club=incoming.club,
                        position=incoming.position,
                        price=incoming.price,
                    ),
                )
            )
        outcome = v.validate_transfers(
            state.squad,
            transfers,
            matchday=first,
            bank=state.bank,
            free_transfers=free_transfers,
            rules=rules,
            chip=None,
            chips_used=state.chips_used,
        )
        by_md = []
        for m in range(len(mds)):
            pts = sum(cols[m][i] for i in starters[m]) + cols[m][captains[m]] * (
                rules.scoring.captain_multiplier - 1
            )
            by_md.append(round(float(pts), 2))
        plans.append(
            {
                "label": f"{k} transfer(s)",
                "transfers_out": outs,
                "transfers_in": [t.incoming.name for t in transfers],
                "points_by_matchday": by_md,
                "expected_points": round(sum(by_md), 2),
                "hit_points": outcome.points_cost,
                "net_points": round(sum(by_md) - outcome.points_cost, 2),
                "bank_after": outcome.bank_after,
                "status": str(outcome.result.status),
                "messages": [m.message for m in outcome.result.violations]
                + [b.message for b in outcome.result.blocks],
            }
        )
    valid = [p for p in plans if p["status"] == "valid"]
    best = max(valid, key=lambda p: p["net_points"], default=None)
    return {
        "tag": "analyst_estimate",
        "matchdays": mds,
        "free_transfers": free_transfers,
        "plans": plans,
        "best": best["label"] if best else None,
    }


def _to_plan(
    label: str,
    chip: Chip | None,
    solution: tuple[list[int], list[int], int],
    cands: list[Candidate],
    state: Any,
    matchday: int,
    rules: RuleSet,
) -> Plan:
    squad_idx, starter_idx, cap = solution
    owned_names = {sl.player.name for sl in state.squad.slots}
    chosen = {cands[i].name for i in squad_idx}
    outs = sorted(owned_names - chosen)
    ins = [cands[i] for i in squad_idx if not cands[i].owned]
    # Pair each sale with a purchase in the same position, as the game requires.
    by_pos: dict[Position, list[Candidate]] = {}
    for c in ins:
        by_pos.setdefault(c.position, []).append(c)
    slot_of = {sl.player.name: sl for sl in state.squad.slots}
    transfers = []
    for name in outs:
        incoming = by_pos[slot_of[name].player.position].pop(0)
        transfers.append(
            v.Transfer(
                out_id=slot_of[name].player.id,
                incoming=Player(
                    id=f"new:{incoming.name}",
                    name=incoming.name,
                    club=incoming.club,
                    position=incoming.position,
                    price=incoming.price,
                ),
            )
        )
    outcome = v.validate_transfers(
        state.squad,
        transfers,
        matchday=matchday,
        bank=state.bank,
        free_transfers=state.free_transfers,
        rules=rules,
        chip=chip,
        chips_used=state.chips_used,
    )
    messages = [m.message for m in outcome.result.violations] + [
        b.message for b in outcome.result.blocks
    ]
    starters = {cands[i].name for i in starter_idx}
    bench = sorted(
        (cands[i] for i in squad_idx if cands[i].name not in starters),
        key=lambda c: (c.position is not Position.GK, -c.xp),
    )
    status = outcome.result.status
    if outcome.squad_after is not None:
        order = {c.name: k for k, c in enumerate(bench)}
        captain_name = cands[cap].name
        slots = tuple(
            SquadSlot(
                player=sl.player,
                role=Role.STARTER if sl.player.name in starters else Role.BENCH,
                bench_order=(
                    None
                    if sl.player.name in starters or sl.player.position is Position.GK
                    else order[sl.player.name]
                ),
                is_captain=sl.player.name == captain_name,
            )
            for sl in outcome.squad_after.slots
        )
        lineup = v.validate_lineup(Squad(slots), rules)
        messages += [m.message for m in lineup.violations]
        if lineup.status != "valid":
            status = lineup.status
    expected = sum(cands[i].xp for i in starter_idx) + cands[cap].xp * (
        rules.scoring.captain_multiplier - 1
    )
    return Plan(
        label=label,
        chip=chip,
        transfers_out=[t for t in outs],
        transfers_in=[t.incoming.name for t in transfers],
        starters=[cands[i].name for i in starter_idx],
        bench=[c.name for c in bench],
        captain=cands[cap].name,
        expected_points=round(expected, 2),
        hit_points=outcome.points_cost,
        net_points=round(expected - outcome.points_cost, 2),
        bank_after=round(outcome.bank_after, 2) if outcome.bank_after is not None else 0.0,
        status=str(status),
        messages=messages,
        unknown_starters=[cands[i].name for i in starter_idx if not cands[i].known],
    )


def candidates_from_view(view: dict[str, Any], state: Any, resolve: Any) -> list[Candidate]:
    owned = {sl.player.name: sl for sl in state.squad.slots}
    out: list[Candidate] = []
    seen: set[str] = set()
    for r in view["players"]:
        name, is_owned = r["name"], r["name"] in owned
        price = r["price"]["value"]
        if is_owned:
            # Sale value equals the current price (confirmed rule); use the price he entered.
            price = owned[name].player.price
        if price is None:
            continue
        club = resolve(r["club"]) or r["club"]
        out.append(
            Candidate(
                name=name,
                club=club,
                position=Position(r["position"]),
                price=float(price),
                xp=float(r["expected_points"] or 0.0),
                owned=is_owned,
                known=r["expected_points"] is not None,
                price_tag=r["price"]["tag"],
            )
        )
        seen.add(name)
    missing = sorted(set(owned) - seen)
    if missing:
        raise ValueError(f"Squad players not in the pool: {missing}")
    return out


def optimise(
    cands: list[Candidate],
    state: Any,
    matchday: int,
    rules: RuleSet,
    s: OptimizerSettings,
    force_out: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """`force_out` names owned players every plan must sell, such as a long-term injury
    the one-matchday view cannot see."""
    owned = [c for c in cands if c.owned]
    unknown = force_out - {c.name for c in owned}
    if unknown:
        raise ValueError(f"Cannot force out players not in the squad: {sorted(unknown)}")
    budget = state.bank + sum(c.price for c in owned)
    plans: list[Plan] = []
    for k in range(0, s.max_transfers + 1):
        sol = _solve(cands, rules, matchday, budget, s, k, force_out)
        if sol is not None:
            plans.append(_to_plan(f"{k} transfer(s)", None, sol, cands, state, matchday, rules))
    wildcard_ok = v.validate_chip(
        Chip.WILDCARD, matchday, rules, chips_used=state.chips_used
    ).status
    if str(wildcard_ok) == "valid":
        sol = _solve(cands, rules, matchday, budget, s, None, force_out)
        if sol is not None:
            plans.append(_to_plan("Wildcard", Chip.WILDCARD, sol, cands, state, matchday, rules))
    valid = [p for p in plans if p.status == "valid"]
    normal = [p for p in valid if p.chip is None]
    best_normal = max(normal, key=lambda p: p.net_points, default=None)
    wildcard = next((p for p in valid if p.chip is Chip.WILDCARD), None)
    pick = best_normal
    if (
        wildcard
        and best_normal
        and wildcard.net_points - best_normal.net_points >= s.wildcard_margin
    ):
        pick = wildcard
    return {
        "tag": "analyst_estimate",
        "matchday": matchday,
        "budget": round(budget, 2),
        "plans": plans,
        "recommended": pick.label if pick else None,
        "wildcard_status": str(wildcard_ok),
        "force_out": sorted(force_out),
    }
