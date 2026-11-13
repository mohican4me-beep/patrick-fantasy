"""Command line for Release 1a: rules, shortlist, squad, transfers, scoring and journal.

Run `uclfa --help` for the list of commands.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from uclfa.db import store
from uclfa.rules import (
    Chip,
    MatchEvents,
    Player,
    Position,
    Result,
    Role,
    Squad,
    SquadSlot,
    Transfer,
    load_rules,
    save_confirmation,
    score_player,
    validate_lineup,
    validate_squad,
    validate_transfers,
)
from uclfa.rules.model import CONFIRMABLE_VALUES


def _print_result(result: Result, heading: str) -> None:
    print(f"{heading}: {result.status.upper()}")
    for v in result.violations:
        print(f"  RULE BROKEN [{v.rule_id}] {v.message}")
    for b in result.blocks:
        print(f"  BLOCKED [{b.rule_id}] {b.message}")
    for n in result.notes:
        print(f"  note: {n}")


def _session() -> Session:
    path = store.db_path()
    if not path.exists():
        sys.exit(f"No database at {path}. Run `uclfa init-db` first.")
    return Session(store.make_engine(path))


def _money(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


# -- rules ---------------------------------------------------------------------------


def cmd_rules_status(_args: argparse.Namespace) -> int:
    rules = load_rules()
    print(f"Rules for season {rules.season}, read from UEFA on {rules.read_on}")
    for rule_id, entry in rules.rule_register.items():
        status = rules.status(rule_id).value
        confirmed = rules.confirmations.get(rule_id)
        extra = (
            f" (you confirmed: {confirmed.value} on {confirmed.confirmed_on})" if confirmed else ""
        )
        print(f"  {status:<17} {rule_id}{extra}")
        if status != "confirmed":
            print(f"      {entry.summary}")
            if entry.blocks:
                print(f"      Blocks: {entry.blocks}")
    return 0


def cmd_rules_confirm(args: argparse.Namespace) -> int:
    try:
        save_confirmation(args.rule_id, args.value, args.note or "")
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"Recorded: {args.rule_id} = {args.value}")
    return 0


# -- database, players, shortlist ----------------------------------------------------


def cmd_init_db(_args: argparse.Namespace) -> int:
    path = store.migrate()
    print(f"Database ready at {path}")
    return 0


def cmd_player_add(args: argparse.Namespace) -> int:
    with _session() as session:
        row = store.get_or_create_player(session, args.name, args.club, Position(args.position))
        if args.price is not None:
            store.record_fact(session, row, "price", value_num=args.price)
        if args.ownership is not None:
            store.record_fact(session, row, "ownership", value_num=args.ownership)
        store.add_to_shortlist(session, row, args.note)
        session.commit()
        print(f"Shortlisted {row.name} ({args.club}, {row.position}) id={row.id}")
    return 0


def cmd_shortlist(_args: argparse.Namespace) -> int:
    with _session() as session:
        rows = store.shortlist(session)
        if not rows:
            print("The shortlist is empty. Add players with `uclfa player add`.")
            return 0
        print(f"{'id':>4}  {'pos':<4}{'name':<26}{'club':<22}{'price':>6}{'own %':>7}")
        for row, price, owned in rows:
            print(
                f"{row.id:>4}  {row.position:<4}{row.name:<26}{row.club.name:<22}"
                f"{_money(price):>6}{_money(owned):>7}"
            )
    return 0


# -- squad ---------------------------------------------------------------------------


def _load_yaml(path: str) -> dict:
    file = Path(path)
    if not file.exists():
        sys.exit(f"File not found: {file}")
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        sys.exit(f"{file} must contain a YAML mapping.")
    return data


def cmd_squad_import(args: argparse.Namespace) -> int:
    data = _load_yaml(args.file)
    rules = load_rules()
    try:
        matchday = int(data["matchday"])
        bank = float(data["bank"])
        entries = data["players"]
    except (KeyError, TypeError, ValueError) as exc:
        sys.exit(f"Squad file needs matchday, bank and players: {exc}")
    free_raw = data.get("free_transfers")
    free = None if free_raw in (None, "unlimited") else int(free_raw)
    try:
        chips_used = frozenset(Chip(c) for c in data.get("chips_used") or [])
    except ValueError as exc:
        sys.exit(f"Unknown chip in chips_used: {exc}")

    with _session() as session:
        slots = []
        for e in entries:
            try:
                row = store.get_or_create_player(
                    session, e["name"], e["club"], Position(e["position"])
                )
            except (KeyError, ValueError) as exc:
                sys.exit(f"Problem with player entry {e!r}: {exc}")
            price = e.get("price")
            if price is not None:
                store.record_fact(session, row, "price", value_num=float(price), matchday=matchday)
            if e.get("sale_value") is not None:
                store.record_fact(
                    session, row, "sale_value", value_num=float(e["sale_value"]), matchday=matchday
                )
            store.add_to_shortlist(session, row)
            slots.append(
                SquadSlot(
                    player=store.to_domain_player(row, float(price) if price is not None else None),
                    role=Role(e.get("role", "starter")),
                    bench_order=e.get("bench_order"),
                    is_captain=bool(e.get("captain", False)),
                    purchase_price=e.get("purchase_price"),
                    sale_value=e.get("sale_value"),
                )
            )
        squad = Squad(tuple(slots))
        # A squad copied from the game may legitimately sit over a club limit after a
        # real-world move, so the limit is reported here and enforced on the next transfer.
        result = validate_squad(squad, matchday, rules, enforce_club_limit=False).merged(
            validate_lineup(squad, rules)
        )
        _print_result(result, f"Squad for matchday {matchday}")
        if result.violations:
            session.rollback()
            print("Nothing was saved.")
            return 1
        snap = store.save_squad_snapshot(
            session,
            matchday=matchday,
            label=str(data.get("label", "pre_deadline")),
            bank=bank,
            free_transfers=free,
            chips_used=chips_used,
            squad=squad,
            note=data.get("note"),
            overall_rank=data.get("overall_rank"),
            overall_points=data.get("overall_points"),
            mini_league_rank=data.get("mini_league_rank"),
        )
        session.commit()
        print(f"Saved squad snapshot {snap.id}.")
    return 0


def _show_squad(state: store.TeamState) -> None:
    free = "unlimited" if state.free_transfers is None else state.free_transfers
    chips = ", ".join(sorted(c.value for c in state.chips_used)) or "none"
    print(
        f"Matchday {state.matchday} ({state.label})  bank {state.bank:.1f}m  "
        f"free transfers {free}  chips used: {chips}"
    )
    for title, group in (("Starting eleven", state.squad.starters), ("Bench", state.squad.bench)):
        print(title)
        for slot in sorted(
            group, key=lambda s: (list(Position).index(s.player.position), s.bench_order or 0)
        ):
            mark = " (C)" if slot.is_captain else ""
            order = f"{slot.bench_order}. " if slot.bench_order else "   "
            print(
                f"  {order}{slot.player.position.value:<4}{slot.player.name + mark:<28}"
                f"{slot.player.club:<22}price {_money(slot.player.price):>5}  "
                f"sale {_money(slot.sale_value):>5}"
            )


def cmd_squad_show(args: argparse.Namespace) -> int:
    with _session() as session:
        state = store.latest_team_state(session, args.matchday)
        if state is None:
            print("No squad saved yet. Use `uclfa squad import FILE`.")
            return 1
        _show_squad(state)
    return 0


def cmd_squad_validate(args: argparse.Namespace) -> int:
    rules = load_rules()
    with _session() as session:
        state = store.latest_team_state(session, args.matchday)
        if state is None:
            print("No squad saved yet.")
            return 1
        result = validate_squad(
            state.squad, state.matchday, rules, enforce_club_limit=False
        ).merged(validate_lineup(state.squad, rules))
        _print_result(result, f"Squad for matchday {state.matchday}")
        return 0 if not result.violations else 1


# -- transfers -----------------------------------------------------------------------


def cmd_transfers_check(args: argparse.Namespace) -> int:
    data = _load_yaml(args.file)
    rules = load_rules()
    with _session() as session:
        state = store.latest_team_state(session)
        if state is None:
            sys.exit("No squad saved yet. Import your squad first.")
        by_name = {s.player.name.casefold(): s.player for s in state.squad.slots}
        transfers = []
        for item in data.get("transfers") or []:
            out_player = by_name.get(str(item.get("out", "")).casefold())
            if out_player is None:
                sys.exit(f"{item.get('out')!r} is not in the saved squad.")
            inc = item.get("in") or {}
            try:
                incoming = Player(
                    id=f"new:{inc['name']}|{inc['club']}",
                    name=inc["name"],
                    club=inc["club"],
                    position=Position(inc["position"]),
                    price=float(inc["price"]) if inc.get("price") is not None else None,
                )
            except (KeyError, ValueError) as exc:
                sys.exit(f"Incoming player needs name, club, position and price: {exc}")
            transfers.append(Transfer(out_id=out_player.id, incoming=incoming))
        chip = Chip(data["chip"]) if data.get("chip") else None
        matchday = int(data.get("matchday", state.matchday))
        outcome = validate_transfers(
            state.squad,
            transfers,
            matchday=matchday,
            bank=state.bank,
            free_transfers=state.free_transfers,
            rules=rules,
            chip=chip,
            chips_used=state.chips_used,
        )
        _print_result(
            outcome.result, f"{outcome.transfers_made} transfer(s) for matchday {matchday}"
        )
        print(f"  points deducted: {outcome.points_cost}")
        print(f"  bank afterwards: {_money(outcome.bank_after)}")
        print(f"  free transfers next matchday: {outcome.free_transfers_next_matchday}")
        return 0 if outcome.result.ok else 1


# -- scoring -------------------------------------------------------------------------


def cmd_score(args: argparse.Namespace) -> int:
    rules = load_rules()
    try:
        events = MatchEvents(
            minutes_played=args.minutes,
            goals=args.goals,
            goals_outside_box=args.outside_box,
            assists=args.assists,
            balls_recovered=args.recoveries,
            saves=args.saves,
            penalties_saved=args.penalty_saves,
            goals_conceded_on_pitch=args.conceded,
            goals_conceded_after_red=args.conceded_after_red,
            player_of_the_match=args.potm,
            penalties_won=args.penalties_won,
            penalties_conceded=args.penalties_conceded,
            penalties_missed=args.penalties_missed,
            yellow_cards=args.yellow,
            red_card=args.red,
            own_goals=args.own_goals,
        )
    except ValueError as exc:
        sys.exit(str(exc))
    breakdown = score_player(Position(args.position), events, rules)
    for name, value in breakdown.components.items():
        print(f"  {name:<22}{value:>4}")
    print(f"  {'total':<22}{breakdown.total:>4}")
    return 0


# -- journal -------------------------------------------------------------------------


def cmd_journal_add(args: argparse.Namespace) -> int:
    with _session() as session:
        entry = store.add_journal(
            session,
            kind=args.kind,
            summary=args.summary,
            matchday=args.matchday,
            estimate=args.estimate,
            estimate_author=args.author,
            decision=args.decision,
        )
        session.commit()
        print(f"Journal entry {entry.id} saved.")
    return 0


def cmd_journal_list(_args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from uclfa.db.models import JournalEntry

    with _session() as session:
        entries = session.scalars(select(JournalEntry).order_by(JournalEntry.id)).all()
        if not entries:
            print("The journal is empty.")
        for e in entries:
            md = f"MD{e.matchday}" if e.matchday else "-"
            print(f"{e.id:>3} {e.created_at:%Y-%m-%d} {md:<5}{e.kind:<14}{e.summary}")
            if e.estimate:
                print(
                    f"      estimate ({e.estimate_tag}, "
                    f"by {e.estimate_author or 'unknown'}): {e.estimate}"
                )
            if e.decision:
                print(f"      decision: {e.decision}")
            if e.outcome:
                print(f"      outcome: {e.outcome}")
    return 0


# -- parser --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uclfa", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create or upgrade the database").set_defaults(func=cmd_init_db)

    rules = sub.add_parser("rules", help="show rule status or confirm an open rule")
    rules_sub = rules.add_subparsers(dest="rules_command", required=True)
    rules_sub.add_parser("status", help="list every rule and its verification status").set_defaults(
        func=cmd_rules_status
    )
    confirm = rules_sub.add_parser("confirm", help="record a rule you checked in the game")
    confirm.add_argument("rule_id", choices=sorted(CONFIRMABLE_VALUES))
    confirm.add_argument("--value", required=True)
    confirm.add_argument("--note")
    confirm.set_defaults(func=cmd_rules_confirm)

    player = sub.add_parser("player", help="add a player to the shortlist")
    player_sub = player.add_subparsers(dest="player_command", required=True)
    add = player_sub.add_parser("add", help="add or update a shortlisted player")
    add.add_argument("--name", required=True)
    add.add_argument("--club", required=True)
    add.add_argument("--position", required=True, choices=[p.value for p in Position])
    add.add_argument("--price", type=float)
    add.add_argument("--ownership", type=float)
    add.add_argument("--note")
    add.set_defaults(func=cmd_player_add)

    sub.add_parser("shortlist", help="list shortlisted players").set_defaults(func=cmd_shortlist)

    squad = sub.add_parser("squad", help="import, show or validate your squad")
    squad_sub = squad.add_subparsers(dest="squad_command", required=True)
    imp = squad_sub.add_parser("import", help="validate and save a squad from a YAML file")
    imp.add_argument("file")
    imp.set_defaults(func=cmd_squad_import)
    for name, func in (("show", cmd_squad_show), ("validate", cmd_squad_validate)):
        p = squad_sub.add_parser(name)
        p.add_argument("--matchday", type=int)
        p.set_defaults(func=func)

    transfers = sub.add_parser("transfers", help="check transfers against the rules")
    transfers_sub = transfers.add_subparsers(dest="transfers_command", required=True)
    check = transfers_sub.add_parser("check", help="validate transfers listed in a YAML file")
    check.add_argument("file")
    check.set_defaults(func=cmd_transfers_check)

    score = sub.add_parser("score", help="score one player's match with the official rules")
    score.add_argument("--position", required=True, choices=[p.value for p in Position])
    score.add_argument("--minutes", type=int, required=True)
    for flag in (
        "goals",
        "outside-box",
        "assists",
        "recoveries",
        "saves",
        "penalty-saves",
        "conceded",
        "conceded-after-red",
        "penalties-won",
        "penalties-conceded",
        "penalties-missed",
        "yellow",
        "own-goals",
    ):
        score.add_argument(f"--{flag}", type=int, default=0)
    score.add_argument("--potm", action="store_true")
    score.add_argument("--red", action="store_true")
    score.set_defaults(func=cmd_score)

    journal = sub.add_parser("journal", help="record or list decisions")
    journal_sub = journal.add_subparsers(dest="journal_command", required=True)
    jadd = journal_sub.add_parser("add")
    jadd.add_argument("--kind", required=True)
    jadd.add_argument("--summary", required=True)
    jadd.add_argument("--matchday", type=int)
    jadd.add_argument("--estimate")
    jadd.add_argument("--author")
    jadd.add_argument("--decision")
    jadd.set_defaults(func=cmd_journal_add)
    journal_sub.add_parser("list").set_defaults(func=cmd_journal_list)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
