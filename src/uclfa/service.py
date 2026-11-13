"""Read-only views over the stored data, shared by the tool server and the command line.

Every value leaves here with a tag: `official` (UEFA's published rules), `entered` (typed
in by Patrick from the game), `analyst_estimate`, or `unavailable`. Nothing is filled in
when it is missing.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from uclfa import decisions
from uclfa.db import store
from uclfa.db.models import Fixture, JournalEntry, PlayerRow
from uclfa.rules import (
    BreakContext,
    Chip,
    Player,
    Position,
    Result,
    RuleSet,
    Substitution,
    Transfer,
    validate_between_days,
    validate_lineup,
    validate_squad,
    validate_transfers,
)
from uclfa.rules.domain import Squad
from uclfa.rules.validators import sale_value

UNAVAILABLE = {"value": None, "tag": "unavailable"}
NO_SQUAD = {"error": "No squad is saved. Import one with `uclfa squad import FILE`."}


def tagged(value: Any, tag: str = "entered") -> dict[str, Any]:
    return dict(UNAVAILABLE) if value is None else {"value": value, "tag": tag}


def result_view(result: Result) -> dict[str, Any]:
    return {
        "status": result.status,
        "rules_broken": [asdict(v) for v in result.violations],
        "blocked_on_unverified_rules": [asdict(b) for b in result.blocks],
        "notes": list(result.notes),
    }


class NameError_(ValueError):
    """A player name that matches nothing, or more than one squad player."""


def find_in_squad(squad: Squad, name: str) -> Player:
    wanted = name.casefold().strip()
    exact = [p for p in squad.players if p.name.casefold() == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [p for p in squad.players if wanted and wanted in p.name.casefold()]
    if len(partial) == 1:
        return partial[0]
    options = ", ".join(p.name for p in (partial or squad.players))
    problem = "matches more than one player" if partial else "is not in the saved squad"
    raise NameError_(f"{name!r} {problem}. Squad players: {options}.")


# -- views ---------------------------------------------------------------------------


def squad_view(session: Session, rules: RuleSet) -> dict[str, Any]:
    state = store.latest_team_state(session)
    if state is None:
        return dict(NO_SQUAD)

    def row(slot) -> dict[str, Any]:
        derived = sale_value(slot, rules)
        sale_tag = "entered" if slot.sale_value is not None else "derived_from_confirmed_rule"
        return {
            "name": slot.player.name,
            "club": slot.player.club,
            "position": slot.player.position.value,
            "captain": slot.is_captain,
            "bench_order": slot.bench_order,
            "price": tagged(slot.player.price),
            "sale_value": tagged(derived, sale_tag),
        }

    return {
        "matchday": state.matchday,
        "label": state.label,
        "source": "entered by Patrick from the game",
        "starting_eleven": [row(s) for s in state.squad.starters],
        "bench": [row(s) for s in state.squad.bench],
    }


def bank_view(session: Session, rules: RuleSet) -> dict[str, Any]:
    state = store.latest_team_state(session)
    if state is None:
        return dict(NO_SQUAD)
    md = rules.matchday(state.matchday)
    stage = rules.stage_for(state.matchday)
    known = [s.player.price for s in state.squad.slots if s.player.price is not None]
    complete = len(known) == len(state.squad.slots)
    return {
        "matchday": state.matchday,
        "bank": tagged(state.bank),
        "squad_value": tagged(round(sum(known), 1) if complete else None, "entered"),
        "free_transfers": tagged(
            "unlimited" if state.free_transfers is None else state.free_transfers
        ),
        "chips_used": sorted(c.value for c in state.chips_used),
        "chips_available": sorted(c.value for c in Chip if c not in state.chips_used),
        "chips_blocked_this_matchday": state.matchday in rules.chips.blocked_matchdays,
        "stage": md.stage,
        "club_limit": {"value": stage.club_limit, "tag": "official"},
        "extra_transfer_cost": {"value": rules.transfers.hit_cost, "tag": "official"},
        "deadline_utc": tagged(md.deadline_utc.isoformat() if md.deadline_utc else None, "entered"),
        "deadline_date": tagged(
            md.deadline_date.isoformat() if md.deadline_date else None, "official"
        ),
    }


def shortlist_view(session: Session) -> dict[str, Any]:
    rows = store.shortlist(session)
    return {
        "source": "entered by Patrick from the game",
        "players": [
            {
                "name": row.name,
                "club": row.club.name,
                "position": row.position,
                "role_tag": tagged(row.role_tag, "analyst_estimate"),
                "price": tagged(price),
                "ownership_percent": tagged(owned),
            }
            for row, price, owned in rows
        ],
    }


def compare_view(session: Session, names: list[str]) -> dict[str, Any]:
    out = []
    for name in names:
        matches = session.scalars(
            select(PlayerRow).where(PlayerRow.name.ilike(f"%{name.strip()}%"))
        ).all()
        if len(matches) != 1:
            out.append(
                {
                    "query": name,
                    "error": "not found in the database"
                    if not matches
                    else "ambiguous: " + ", ".join(m.name for m in matches),
                }
            )
            continue
        row = matches[0]
        facts = {}
        for fact_type in ("price", "ownership", "total_points", "matchday_points"):
            fact = store.latest_fact(session, row.id, fact_type)
            facts[fact_type] = (
                dict(UNAVAILABLE)
                if fact is None
                else {
                    "value": fact.value_num,
                    "tag": fact.tag,
                    "matchday": fact.matchday,
                    "observed_at": fact.observed_at.isoformat(),
                }
            )
        out.append(
            {
                "name": row.name,
                "club": row.club.name,
                "position": row.position,
                **facts,
                "expected_points": dict(UNAVAILABLE),
            }
        )
    return {
        "players": out,
        "note": "No projections exist in this release. Any expected-points figure is an "
        "analyst estimate and must be labelled as one.",
    }


def fixtures_view(session: Session, matchday: int | None = None) -> dict[str, Any]:
    query = select(Fixture)
    if matchday is not None:
        query = query.where(Fixture.matchday == matchday)
    rows = session.scalars(query).all()
    if not rows:
        return {
            "fixtures": [],
            "tag": "unavailable",
            "note": "No fixtures have been entered. Do not state fixtures from memory as fact.",
        }
    return {"fixtures": [{"matchday": f.matchday, "id": f.id} for f in rows], "tag": "entered"}


def rules_view(rules: RuleSet) -> dict[str, Any]:
    return {
        "season": rules.season,
        "source": rules.source_url,
        "read_on": rules.read_on.isoformat(),
        "squad": {p.value: n for p, n in rules.squad.positions.items()},
        "lineup": {
            "exact": {p.value: n for p, n in rules.lineup.exact.items()},
            "minimum": {p.value: n for p, n in rules.lineup.minimum.items()},
        },
        "stages": {k: v.model_dump() for k, v in rules.stages.items()},
        "matchdays": {
            n: {
                "stage": md.stage,
                "free_transfers": md.free_transfers,
                "carry_in": md.carry_in,
                "mid_matchday_changes": md.mid_matchday_changes,
                "deadline_date": md.deadline_date.isoformat() if md.deadline_date else None,
                "deadline_utc": md.deadline_utc.isoformat() if md.deadline_utc else None,
            }
            for n, md in rules.matchdays.items()
        },
        "transfers": rules.transfers.model_dump(),
        "chips": {
            "blocked_matchdays": rules.chips.blocked_matchdays,
            "wildcard": rules.chips.wildcard.model_dump(),
            "limitless": rules.chips.limitless.model_dump(),
        },
        "scoring": rules.scoring.model_dump(mode="json"),
        "register": {
            rule_id: {
                "status": rules.status(rule_id).value,
                "summary": entry.summary,
                "confirmed_value": rules.confirmed_value(rule_id)
                if rule_id in rules.confirmations
                else None,
                "blocks_if_unverified": entry.blocks,
            }
            for rule_id, entry in rules.rule_register.items()
        },
    }


def journal_view(session: Session, limit: int = 20) -> dict[str, Any]:
    entries = session.scalars(
        select(JournalEntry).order_by(JournalEntry.id.desc()).limit(limit)
    ).all()
    return {
        "entries": [
            {
                "id": e.id,
                "created_at": e.created_at.isoformat(),
                "matchday": e.matchday,
                "kind": e.kind,
                "summary": e.summary,
                "estimate": e.estimate,
                "estimate_author": e.estimate_author,
                "estimate_tag": e.estimate_tag,
                "decision": e.decision,
                "outcome": e.outcome,
            }
            for e in entries
        ]
    }


# -- validation ----------------------------------------------------------------------


def validate_saved_squad(session: Session, rules: RuleSet) -> dict[str, Any]:
    state = store.latest_team_state(session)
    if state is None:
        return dict(NO_SQUAD)
    result = validate_squad(state.squad, state.matchday, rules, enforce_club_limit=False).merged(
        validate_lineup(state.squad, rules)
    )
    return {"matchday": state.matchday, **result_view(result)}


def validate_transfers_view(
    session: Session,
    rules: RuleSet,
    transfers: list[dict[str, Any]],
    *,
    chip: str | None = None,
    matchday: int | None = None,
) -> dict[str, Any]:
    """Each transfer: {"out": name, "in": {"name", "club", "position", "price"}}."""
    state = store.latest_team_state(session)
    if state is None:
        return dict(NO_SQUAD)
    try:
        parsed = []
        for item in transfers:
            out_player = find_in_squad(state.squad, str(item["out"]))
            inc = item["in"]
            parsed.append(
                Transfer(
                    out_id=out_player.id,
                    incoming=Player(
                        id=f"new:{inc['name']}|{inc['club']}",
                        name=inc["name"],
                        club=inc["club"],
                        position=Position(inc["position"]),
                        price=float(inc["price"]) if inc.get("price") is not None else None,
                    ),
                )
            )
        chip_value = Chip(chip) if chip else None
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Could not read the transfers: {exc}"}
    outcome = validate_transfers(
        state.squad,
        parsed,
        matchday=matchday or state.matchday,
        bank=state.bank,
        free_transfers=state.free_transfers,
        rules=rules,
        chip=chip_value,
        chips_used=state.chips_used,
    )
    return {
        "matchday": matchday or state.matchday,
        **result_view(outcome.result),
        "transfers_made": outcome.transfers_made,
        "free_transfers_available": outcome.free_transfers_available,
        "paid_transfers": outcome.paid_transfers,
        "points_deducted": {"value": outcome.points_cost, "tag": "official"},
        "bank_after": tagged(outcome.bank_after, "derived_from_entered_prices"),
        "free_transfers_next_matchday": outcome.free_transfers_next_matchday,
        "note": "Incoming prices are the ones supplied in this request; check them in the game.",
    }


def validate_between_days_view(
    session: Session,
    rules: RuleSet,
    *,
    substitutions: list[dict[str, str]] | None = None,
    new_captain: str | None = None,
    played: list[str] | None = None,
    sent_off: list[str] | None = None,
    previous_captains: list[str] | None = None,
    next_day_started: bool = False,
) -> dict[str, Any]:
    """Substitutions are {"out": name, "in": name}; `played` lists squad players whose
    team has already played this matchday."""
    state = store.latest_team_state(session)
    if state is None:
        return dict(NO_SQUAD)
    try:

        def ids(names: list[str] | None) -> frozenset[str]:
            return frozenset(find_in_squad(state.squad, n).id for n in names or [])

        subs = [
            Substitution(
                find_in_squad(state.squad, s["out"]).id, find_in_squad(state.squad, s["in"]).id
            )
            for s in substitutions or []
        ]
        captain_id = find_in_squad(state.squad, new_captain).id if new_captain else None
        ctx = BreakContext(
            matchday=state.matchday,
            played_ids=ids(played),
            sent_off_ids=ids(sent_off),
            previous_captain_ids=ids(previous_captains),
            next_day_started=next_day_started,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Could not read the request: {exc}"}
    outcome = validate_between_days(state.squad, subs, captain_id, ctx, rules)
    view = {
        "matchday": state.matchday,
        **result_view(outcome.result),
        "automatic_substitutions_disabled": outcome.automatic_substitutions_disabled,
    }
    if outcome.squad_after is not None:
        after = outcome.squad_after
        view["lineup_after"] = {
            "starting_eleven": [s.player.name for s in after.starters],
            "bench": [s.player.name for s in after.bench],
            "captain": after.captain.player.name if after.captain else None,
        }
    return view


# -- calculators ---------------------------------------------------------------------


def _risks(items: list[dict[str, Any]] | None) -> list[decisions.AutoSubRisk]:
    return [
        decisions.AutoSubRisk(
            player=str(i["player"]),
            probability_not_playing=float(i["probability_not_playing"]),
            replacement_expected_points=float(i["replacement_expected_points"]),
        )
        for i in items or []
    ]


def captain_view(
    rules: RuleSet,
    current_captain_points: float,
    candidates: list[dict[str, Any]],
    *,
    estimate_author: str,
    auto_sub_risks: list[dict[str, Any]] | None = None,
    automatic_substitutions_already_disabled: bool = False,
) -> dict[str, Any]:
    try:
        decision = decisions.captain_switch_value(
            current_captain_points,
            [
                decisions.CaptainCandidate(str(c["name"]), float(c["expected_points"]))
                for c in candidates
            ],
            rules,
            auto_sub_risks=_risks(auto_sub_risks),
            automatic_substitutions_already_disabled=automatic_substitutions_already_disabled,
            estimate_author=estimate_author,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Could not read the request: {exc}"}
    return {**asdict(decision), "summary": decision.summary()}


def substitution_view(
    rules: RuleSet,
    swaps: list[dict[str, Any]],
    *,
    estimate_author: str,
    auto_sub_risks: list[dict[str, Any]] | None = None,
    automatic_substitutions_already_disabled: bool = False,
) -> dict[str, Any]:
    try:
        decision = decisions.substitution_value(
            [
                decisions.Swap(
                    out_name=str(s["out"]),
                    in_name=str(s["in"]),
                    in_expected_points=float(s["in_expected_points"]),
                    out_realised_points=s.get("out_realised_points"),
                    out_expected_points=s.get("out_expected_points"),
                    out_is_captain=bool(s.get("out_is_captain", False)),
                )
                for s in swaps
            ],
            rules,
            auto_sub_risks=_risks(auto_sub_risks),
            automatic_substitutions_already_disabled=automatic_substitutions_already_disabled,
            estimate_author=estimate_author,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"Could not read the request: {exc}"}
    return {**asdict(decision), "summary": decision.summary()}
