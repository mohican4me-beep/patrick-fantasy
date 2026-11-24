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


# -- match outlook (Release 2 Phase B) ------------------------------------------------


def rating_evidence(data_dir: Any = None, settings: Any = None) -> tuple[list[Any], int]:
    """Played results and market-implied goal rates, for fitting team ratings.

    Returns (evidence, latest matchday with evidence). For each match the most recent odds
    snapshot that priced it is used.
    """
    import json

    from uclfa.ingest.clubs import make_resolver
    from uclfa.ingest.run import DATA_DIR, latest_snapshot
    from uclfa.model.match import MarketInput, fit_match, load_settings, main_half_line
    from uclfa.model.ratings import Evidence

    data_dir = DATA_DIR if data_dir is None else data_dir
    settings = load_settings() if settings is None else settings
    fixtures = latest_snapshot("fixtures", data_dir)
    if fixtures is None:
        return [], 0
    resolve, _ = make_resolver(fixtures, data_dir)
    md_of = {(f["home"], f["away"]): f["matchday"] for f in fixtures["records"]}
    evidence: list[Any] = []
    for f in fixtures["records"]:
        if f.get("status") == "FINISHED" and f.get("home_goals") is not None:
            evidence.append(
                Evidence(
                    f["home"], f["away"], f["home_goals"], f["away_goals"], "result", f["matchday"]
                )
            )
    seen: set[tuple[str, str]] = set()
    for path in sorted((data_dir / "snapshots" / "odds").glob("*.json"), reverse=True):
        for o in json.loads(path.read_text(encoding="utf-8"))["records"]:
            pair = (resolve(o["home"]), resolve(o["away"]))
            if pair in seen or pair not in md_of:
                continue
            seen.add(pair)  # newest snapshot first, so this is the latest price
            line, over, under, books, _note = main_half_line(o)
            try:
                fit = fit_match(
                    MarketInput(
                        o["home_price"],
                        o["draw_price"],
                        o["away_price"],
                        o["bookmakers"],
                        line,
                        over,
                        under,
                        books,
                    ),
                    settings,
                )
            except (TypeError, ValueError):
                continue
            evidence.append(
                Evidence(pair[0], pair[1], fit.home_rate, fit.away_rate, "odds", md_of[pair])
            )
    latest = max((e.matchday for e in evidence), default=0)
    return evidence, latest


def team_ratings(data_dir: Any = None) -> Any:
    """Fitted team ratings, or None when there is no evidence."""
    from uclfa.model.ratings import fit_ratings, load_rating_settings

    evidence, latest = rating_evidence(data_dir)
    if not evidence:
        return None
    return fit_ratings(evidence, load_rating_settings(), latest)


def match_outlook_view(
    matchday: int,
    data_dir: Any = None,
    settings: Any = None,
    now: Any = None,
    ratings: Any = None,
) -> dict[str, Any]:
    """Team goal expectations for one matchday, from the latest fixtures and odds snapshots.

    Every number is an `analyst_estimate`. A match with odds is fitted to them (`source`
    odds). Without odds, and if `ratings` are given, it is projected from team ratings
    (`source` projection, lower confidence); otherwise it is `unavailable` with the reason.
    """
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from uclfa.ingest.clubs import make_resolver
    from uclfa.ingest.run import DATA_DIR, latest_snapshot
    from uclfa.model.match import (
        MarketInput,
        fit_match,
        load_settings,
        main_half_line,
        scoreline_grid,
    )

    data_dir = DATA_DIR if data_dir is None else data_dir
    settings = load_settings() if settings is None else settings
    now = datetime.now(UTC) if now is None else now
    athens = ZoneInfo("Europe/Athens")

    fixtures = latest_snapshot("fixtures", data_dir)
    if fixtures is None:
        return {"matchday": matchday, "tag": "unavailable", "note": "No fixtures snapshot."}
    rows = sorted(
        (r for r in fixtures["records"] if r["matchday"] == matchday),
        key=lambda r: (r["kickoff_utc"], r["home"]),
    )
    if not rows:
        return {
            "matchday": matchday,
            "tag": "unavailable",
            "note": f"No fixtures for matchday {matchday} in the latest snapshot.",
        }
    odds = latest_snapshot("odds", data_dir)
    resolve, _ = make_resolver(fixtures, data_dir)
    odds_records = odds["records"] if odds else []
    by_pair: dict[tuple[str | None, str | None], dict[str, Any]] = {
        (resolve(o["home"]), resolve(o["away"])): o for o in odds_records
    }
    used: set[str] = set()

    def r3(x: float) -> float:
        return round(x, 3)

    matches: list[dict[str, Any]] = []
    for f in rows:
        kickoff = datetime.fromisoformat(f["kickoff_utc"])
        entry: dict[str, Any] = {
            "kickoff_utc": f["kickoff_utc"],
            "kickoff_athens": kickoff.astimezone(athens).strftime("%a %d %b %H:%M"),
            "home": f["home"],
            "away": f["away"],
        }
        o = by_pair.get((f["home"], f["away"]))
        if o is None:
            reason = "no odds listed for this match"
            if (f["away"], f["home"]) in by_pair:
                reason = "odds list the teams the other way round; not used"
            elif f.get("status") == "FINISHED":
                reason = "match already played"
            elif ratings is not None:
                try:
                    lh, la = ratings.rates(f["home"], f["away"])
                except KeyError:
                    reason = "no odds, and a club has no rating evidence"
                else:
                    g = scoreline_grid(lh, la, settings.low_score_correction, settings.max_goals)
                    matches.append(
                        {
                            **entry,
                            "status": "projected",
                            "source": "projection",
                            "tag": "analyst_estimate",
                            "expected_goals": {"home": round(lh, 2), "away": round(la, 2)},
                            "clean_sheet": {
                                "home": r3(g.home_clean_sheet),
                                "away": r3(g.away_clean_sheet),
                            },
                            "scores": {
                                "home": r3(1 - g.away_clean_sheet),
                                "away": r3(1 - g.home_clean_sheet),
                            },
                            "result": {
                                "home_win": r3(g.home_win),
                                "draw": r3(g.draw),
                                "away_win": r3(g.away_win),
                            },
                            "confidence": "projection",
                            "reasons": ["no odds yet: projected from team ratings"],
                        }
                    )
                    continue
            matches.append(
                {**entry, "status": "unavailable", "tag": "unavailable", "reason": reason}
            )
            continue
        used.add(o["source_id"])
        line, over, under, goals_books, note = main_half_line(o)
        try:
            fit = fit_match(
                MarketInput(
                    home_price=o["home_price"],
                    draw_price=o["draw_price"],
                    away_price=o["away_price"],
                    result_bookmakers=o["bookmakers"],
                    total_line=line,
                    over_price=over,
                    under_price=under,
                    goals_bookmakers=goals_books,
                ),
                settings,
            )
        except (TypeError, ValueError) as exc:
            matches.append(
                {
                    **entry,
                    "status": "unavailable",
                    "tag": "unavailable",
                    "reason": f"odds unusable: {exc}",
                }
            )
            continue
        reasons = list(fit.reasons)
        if note:
            reasons.append(note)
        if o["kickoff_utc"] != f["kickoff_utc"]:
            reasons.append(f"odds kick-off {o['kickoff_utc']} differs from the fixture's")
        g = fit.grid
        matches.append(
            {
                **entry,
                "status": "fitted",
                "source": "odds",
                "tag": "analyst_estimate",
                "expected_goals": {
                    "home": round(fit.home_rate, 2),
                    "away": round(fit.away_rate, 2),
                },
                "clean_sheet": {"home": r3(g.home_clean_sheet), "away": r3(g.away_clean_sheet)},
                "scores": {"home": r3(1 - g.away_clean_sheet), "away": r3(1 - g.home_clean_sheet)},
                "result": {k: r3(fit.model[k]) for k in ("home_win", "draw", "away_win")},
                "market": {k: r3(v) for k, v in fit.market.items()},
                "model": {k: r3(v) for k, v in fit.model.items()},
                "max_error_points": round(fit.max_error * 100, 2),
                "goals_line": fit.goals_line,
                "bookmakers": {"result": o["bookmakers"], "goals": goals_books},
                "margins": {k: round(v, 4) for k, v in fit.margins.items()},
                "top_scorelines": [(s, r3(p)) for s, p in g.top_scorelines(3)],
                "confidence": "low" if reasons else "normal",
                "reasons": reasons,
            }
        )

    kickoffs = {f["kickoff_utc"][:10] for f in rows}
    stray = [
        f"{o['home']} v {o['away']}"
        for o in odds_records
        if o["source_id"] not in used and o["kickoff_utc"][:10] in kickoffs
    ]
    fetched = datetime.fromisoformat(odds["fetched_at"]) if odds else None
    fitted = sum(m["status"] == "fitted" for m in matches)
    projected = sum(m["status"] == "projected" for m in matches)
    return {
        "matchday": matchday,
        "tag": "analyst_estimate" if fitted or projected else "unavailable",
        "projected": projected,
        "author": "Claude's match model (docs/model.md)",
        "odds_fetched_at": odds["fetched_at"] if odds else None,
        "odds_age_hours": round((now - fetched).total_seconds() / 3600, 1) if fetched else None,
        "fixtures_fetched_at": fixtures["fetched_at"],
        "fitted": fitted,
        "unavailable": len(matches) - fitted - projected,
        "odds_not_matched_to_a_fixture": stray,
        "settings": settings.model_dump(),
        "matches": matches,
        "note": (
            "Estimates from bookmaker odds, not official data. Clean sheet = chance the "
            "opponent scores 0; it does not account for a player's minutes."
        ),
    }


# -- player expected points (Release 2 Phase C) ---------------------------------------


def load_player_pool(data_dir: Any = None) -> tuple[list[Any], str | None]:
    import yaml

    from uclfa.ingest.run import DATA_DIR
    from uclfa.model.player import PlayerInputs

    path = (DATA_DIR if data_dir is None else data_dir) / "players" / "pool.yaml"
    if not path.exists():
        return [], None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [PlayerInputs.model_validate(p) for p in data.get("players") or []], data.get("as_of")


def player_points_view(
    matchday: int,
    rules: RuleSet,
    data_dir: Any = None,
    now: Any = None,
    squad_names: set[str] | None = None,
    ratings: Any = None,
) -> dict[str, Any]:
    """Expected points for every pool player in one matchday. All `analyst_estimate`.

    With `ratings`, matches without odds are projected from team ratings; each player row
    says which (`match_source`)."""
    from uclfa.ingest.clubs import make_resolver
    from uclfa.ingest.run import DATA_DIR, latest_snapshot
    from uclfa.model.player import TeamContext, expected_points, load_player_settings

    data_dir = DATA_DIR if data_dir is None else data_dir
    outlook = match_outlook_view(matchday, data_dir=data_dir, now=now, ratings=ratings)
    pool, as_of = load_player_pool(data_dir)
    if not pool:
        return {"matchday": matchday, "tag": "unavailable", "note": "No player pool file."}
    if not outlook.get("matches"):
        return {"matchday": matchday, "tag": "unavailable", "note": outlook.get("note")}
    resolve, _ = make_resolver(latest_snapshot("fixtures", data_dir), data_dir)
    settings = load_player_settings()
    side: dict[str, tuple[dict[str, Any], str]] = {}
    for m in outlook["matches"]:
        side[m["home"]] = (m, "home")
        side[m["away"]] = (m, "away")

    players: list[dict[str, Any]] = []
    for p in pool:
        row: dict[str, Any] = {
            "name": p.name,
            "club": p.club,
            "position": p.position.value,
            "price": tagged(p.price, p.price_tag) if p.price is not None else dict(UNAVAILABLE),
            "price_date": p.price_date,
            "in_squad": squad_names is not None and p.name in squad_names,
        }

        def unavailable(reason: str, row: dict[str, Any] = row) -> None:
            players.append({**row, "tag": "unavailable", "expected_points": None, "reason": reason})

        club = resolve(p.club)
        if club is None or club not in side:
            unavailable(
                f"club '{p.club}' not matched to a fixture"
                if club is None
                else "club has no match this matchday"
            )
            continue
        m, where = side[club]
        other = "away" if where == "home" else "home"
        row["opponent"] = f"{m[other]} ({'H' if where == 'home' else 'A'})"
        row["kickoff_athens"] = m["kickoff_athens"]
        if m["status"] not in ("fitted", "projected"):
            unavailable(f"no match estimate: {m['reason']}")
            continue
        team = TeamContext(
            goals_for=m["expected_goals"][where],
            goals_against=m["expected_goals"][other],
            clean_sheet=m["clean_sheet"][where],
        )
        try:
            pts = expected_points(p.for_matchday(matchday), team, rules, settings)
        except ValueError as exc:
            unavailable(str(exc))
            continue
        notes = list(pts.notes)
        row["match_source"] = m["source"]
        if m["status"] == "projected":
            notes.append("match projected from team ratings (no odds yet)")
        if m["confidence"] == "low":
            notes.append("match estimate is low confidence")
        players.append(
            {
                **row,
                "tag": "analyst_estimate",
                "expected_points": round(pts.expected, 2),
                "if_starts": round(pts.if_starts, 2),
                "plays_prob": round(pts.plays_prob, 3),
                "components": {k: round(v, 2) for k, v in pts.components.items()},
                "sources": p.sources,
                "notes": notes,
            }
        )
    players.sort(key=lambda r: -(r["expected_points"] or -1))
    done = sum(r["expected_points"] is not None for r in players)
    return {
        "matchday": matchday,
        "tag": "analyst_estimate" if done else "unavailable",
        "author": "Claude's player model (docs/model.md)",
        "pool_as_of": as_of,
        "odds_fetched_at": outlook["odds_fetched_at"],
        "odds_age_hours": outlook["odds_age_hours"],
        "estimated": done,
        "unavailable": len(players) - done,
        "players": players,
        "note": "Estimates, not official data. Inputs are Claude's, with sources per player.",
    }


# -- choices over the coming matchdays (Release 2 Phase E) ----------------------------


def horizon_end(start: int, rules: RuleSet) -> int:
    """Last matchday before the next one with unlimited transfers (a free rebuild)."""
    md = start
    while md + 1 in rules.matchdays and not rules.matchdays[md + 1].unlimited:
        md += 1
    return md


def horizon_views(
    first: int, last: int, rules: RuleSet, data_dir: Any = None, squad_names: Any = None
) -> dict[int, dict[str, Any]]:
    """Player points views for each matchday, odds where priced, projections otherwise."""
    ratings = team_ratings(data_dir)
    return {
        md: player_points_view(
            md, rules, data_dir=data_dir, squad_names=squad_names, ratings=ratings
        )
        for md in range(first, last + 1)
    }


def horizon_table(views: dict[int, dict[str, Any]]) -> dict[str, dict[int, dict[str, Any]]]:
    """name -> matchday -> player row."""
    out: dict[str, dict[int, dict[str, Any]]] = {}
    for md, view in views.items():
        for row in view.get("players") or []:
            out.setdefault(row["name"], {})[md] = row
    return out


def team_outlook_view(first: int, last: int, data_dir: Any = None) -> dict[str, Any]:
    """Every club's matches from `first` to `last`: opponent, expected goals, clean-sheet
    chance and whether the numbers come from odds or a projection."""
    ratings = team_ratings(data_dir)
    clubs: dict[str, dict[int, dict[str, Any]]] = {}
    for md in range(first, last + 1):
        view = match_outlook_view(md, data_dir=data_dir, ratings=ratings)
        for m in view.get("matches") or []:
            for side, other, venue in (("home", "away", "H"), ("away", "home", "A")):
                entry: dict[str, Any] = {
                    "opponent": m[other],
                    "venue": venue,
                    "kickoff_athens": m["kickoff_athens"],
                }
                if m["status"] in ("fitted", "projected"):
                    entry.update(
                        tag="analyst_estimate",
                        source=m["source"],
                        goals_for=m["expected_goals"][side],
                        goals_against=m["expected_goals"][other],
                        clean_sheet=m["clean_sheet"][side],
                    )
                else:
                    entry.update(tag="unavailable", reason=m["reason"])
                clubs.setdefault(m[side], {})[md] = entry
    return {
        "first": first,
        "last": last,
        "tag": "analyst_estimate",
        "ratings_from_matches": ratings.matches_used if ratings else 0,
        "clubs": clubs,
        "note": (
            "Matches with odds use them; others are projected from team ratings fitted to "
            "results and past odds, which are rougher (docs/model.md)."
        ),
    }


def player_outlook_view(
    first: int,
    last: int,
    rules: RuleSet,
    names: list[str],
    data_dir: Any = None,
    squad_names: Any = None,
) -> dict[str, Any]:
    """Named players' expected points per matchday and in total. Analyst estimates."""
    table = horizon_table(horizon_views(first, last, rules, data_dir, squad_names))
    players = []
    for name in names:
        rows = table.get(name)
        if not rows:
            players.append({"name": name, "tag": "unavailable", "reason": "not in the pool"})
            continue
        per_md = []
        for md in range(first, last + 1):
            r = rows.get(md)
            per_md.append(
                {
                    "matchday": md,
                    "opponent": (r or {}).get("opponent"),
                    "expected_points": (r or {}).get("expected_points"),
                    "source": (r or {}).get("match_source"),
                    "reason": None
                    if r and r["expected_points"] is not None
                    else (r or {}).get("reason", "no data"),
                }
            )
        any_row = next(iter(rows.values()))
        players.append(
            {
                "name": name,
                "club": any_row["club"],
                "position": any_row["position"],
                "price": any_row["price"],
                "tag": "analyst_estimate",
                "matchdays": per_md,
                "total": round(sum(m["expected_points"] or 0 for m in per_md), 2),
                "complete": all(m["expected_points"] is not None for m in per_md),
            }
        )
    return {"first": first, "last": last, "tag": "analyst_estimate", "players": players}


def evaluate_move_view(
    state: Any,
    rules: RuleSet,
    outs: list[str],
    in_names: list[str],
    matchday: int,
    last: int | None = None,
    data_dir: Any = None,
) -> dict[str, Any]:
    """Judge transfers at `matchday` against keeping the squad, over the matchdays up to
    `last` (default: the last before the next free rebuild). Nothing is saved."""
    from uclfa.horizon import canonical_state, evaluate_move
    from uclfa.ingest.clubs import make_resolver
    from uclfa.ingest.run import DATA_DIR, latest_snapshot
    from uclfa.optimize import load_optimizer_settings

    data_dir = DATA_DIR if data_dir is None else data_dir
    last = last or horizon_end(matchday, rules)
    resolve, _ = make_resolver(latest_snapshot("fixtures", data_dir), data_dir)
    state = canonical_state(state, resolve)
    owned = {sl.player.name for sl in state.squad.slots}
    views = horizon_views(matchday, last, rules, data_dir, owned)
    table = horizon_table(views)
    ins, warnings = [], []
    for name in in_names:
        rows = table.get(name)
        if not rows:
            return {"tag": "unavailable", "note": f"Not in the player pool: {name}"}
        row = next(iter(rows.values()))
        if row["price"]["value"] is None:
            return {"tag": "unavailable", "note": f"No price for {name}."}
        if row["price"]["tag"] != "entered":
            warnings.append(
                f"{name}: price {row['price']['value']} is from a third-party site "
                f"({row.get('price_date')}); check the game."
            )
        ins.append(
            {
                "name": name,
                "club": resolve(row["club"]) or row["club"],
                "position": row["position"],
                "price": row["price"]["value"],
            }
        )
    mds = list(range(matchday, last + 1))
    xp_by_md = {
        md: {n: rs[md]["expected_points"] for n, rs in table.items() if md in rs} for md in mds
    }
    sources = {
        md: "odds"
        if any(r.get("match_source") == "odds" for r in views[md]["players"])
        else "projection"
        for md in mds
    }
    try:
        ev = evaluate_move(state, outs, ins, matchday, xp_by_md, sources, rules)
    except ValueError as exc:
        return {"tag": "unavailable", "note": str(exc)}
    margin = load_optimizer_settings().verdict_margin
    if ev.status != "valid":
        verdict = "not possible as it stands"
    elif ev.net_gain > margin:
        verdict = "makes sense"
    elif ev.net_gain > -margin:
        verdict = "too close to call"
    else:
        verdict = "does not make sense"
    unknown = sorted({n for lu in ev.keep + ev.move for n in lu.unknown})
    return {
        "tag": "analyst_estimate",
        "move": [{"out": o, "in": i["name"]} for o, i in zip(outs, ins, strict=True)],
        "matchdays": ev.matchdays,
        "sources": ev.sources,
        "rules_status": ev.status,
        "rules_messages": ev.messages,
        "free_transfers": ev.free_transfers,
        "hit_points": ev.hit_points,
        "bank_after": ev.bank_after,
        "players": ev.player_rows,
        "team_keep": [lu.points for lu in ev.keep],
        "team_with_move": [lu.points for lu in ev.move],
        "gain_by_matchday": ev.gain_by_matchday,
        "net_gain": ev.net_gain,
        "verdict": verdict,
        "verdict_margin": margin,
        "warnings": warnings
        + ([f"No estimate for {', '.join(unknown)} (counted as 0)."] if unknown else []),
        "note": (
            "Team points are the best lineup and captain each matchday, with and without the "
            "move. Projected matchdays (no odds yet) are rougher. The decision is Patrick's."
        ),
    }
