"""Database access: engine, migrations and the few operations Phase 1 needs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session

from uclfa.db.models import (
    Club,
    FantasyFact,
    JournalEntry,
    PlayerRow,
    ShortlistEntry,
    SquadPlayerRow,
    SquadSnapshot,
)
from uclfa.rules.domain import Player, Role, Squad, SquadSlot
from uclfa.rules.model import REPO_ROOT, Chip, Position

DEFAULT_DB_PATH = REPO_ROOT / "data" / "uclfa.db"


def db_path() -> Path:
    return Path(os.environ.get("UCLFA_DB", DEFAULT_DB_PATH))


def make_engine(path: Path | str | None = None) -> Engine:
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{target}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def migrate(path: Path | str | None = None) -> Path:
    """Create or upgrade the database to the latest schema."""
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{target}")
    command.upgrade(cfg, "head")
    return target


# -- players and shortlist -----------------------------------------------------------


def get_or_create_club(session: Session, name: str) -> Club:
    club = session.scalar(select(Club).where(Club.name == name))
    if club is None:
        club = Club(name=name)
        session.add(club)
        session.flush()
    return club


def get_or_create_player(session: Session, name: str, club: str, position: Position) -> PlayerRow:
    club_row = get_or_create_club(session, club)
    row = session.scalar(
        select(PlayerRow).where(PlayerRow.name == name, PlayerRow.club_id == club_row.id)
    )
    if row is None:
        row = PlayerRow(name=name, club_id=club_row.id, position=position.value)
        session.add(row)
        session.flush()
    elif row.position != position.value:
        raise ValueError(
            f"{name} ({club}) is stored as {row.position}; got {position.value}. "
            "Fix the entry before continuing."
        )
    return row


def record_fact(
    session: Session,
    player: PlayerRow,
    fact_type: str,
    *,
    value_num: float | None = None,
    value_text: str | None = None,
    matchday: int | None = None,
    source: str = "manual",
    tag: str = "entered",
    note: str | None = None,
) -> FantasyFact:
    fact = FantasyFact(
        player_id=player.id,
        fact_type=fact_type,
        value_num=value_num,
        value_text=value_text,
        matchday=matchday,
        source=source,
        tag=tag,
        note=note,
    )
    session.add(fact)
    return fact


def latest_fact(session: Session, player_id: int, fact_type: str) -> FantasyFact | None:
    return session.scalar(
        select(FantasyFact)
        .where(FantasyFact.player_id == player_id, FantasyFact.fact_type == fact_type)
        .order_by(FantasyFact.observed_at.desc(), FantasyFact.id.desc())
        .limit(1)
    )


def add_to_shortlist(session: Session, player: PlayerRow, note: str | None = None) -> None:
    entry = session.scalar(select(ShortlistEntry).where(ShortlistEntry.player_id == player.id))
    if entry is None:
        session.add(ShortlistEntry(player_id=player.id, note=note))
    else:
        entry.active = True
        if note:
            entry.note = note


def shortlist(session: Session) -> list[tuple[PlayerRow, float | None, float | None]]:
    """Active shortlist with each player's latest entered price and ownership."""
    rows = session.scalars(
        select(ShortlistEntry).where(ShortlistEntry.active.is_(True)).order_by(ShortlistEntry.id)
    ).all()
    out = []
    for entry in rows:
        price = latest_fact(session, entry.player_id, "price")
        owned = latest_fact(session, entry.player_id, "ownership")
        out.append(
            (entry.player, price.value_num if price else None, owned.value_num if owned else None)
        )
    return out


def to_domain_player(row: PlayerRow, price: float | None) -> Player:
    return Player(
        id=str(row.id),
        name=row.name,
        club=row.club.name,
        position=Position(row.position),
        price=price,
    )


# -- squad ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamState:
    snapshot_id: int
    matchday: int
    label: str
    bank: float
    free_transfers: int | None
    chips_used: frozenset[Chip]
    squad: Squad


def save_squad_snapshot(
    session: Session,
    *,
    matchday: int,
    label: str,
    bank: float,
    free_transfers: int | None,
    chips_used: frozenset[Chip] | set[Chip],
    squad: Squad,
    note: str | None = None,
    overall_rank: int | None = None,
    overall_points: int | None = None,
    mini_league_rank: int | None = None,
) -> SquadSnapshot:
    snap = SquadSnapshot(
        matchday=matchday,
        label=label,
        bank=bank,
        free_transfers=free_transfers,
        wildcard_used=Chip.WILDCARD in chips_used,
        limitless_used=Chip.LIMITLESS in chips_used,
        note=note,
        overall_rank=overall_rank,
        overall_points=overall_points,
        mini_league_rank=mini_league_rank,
    )
    for slot in squad.slots:
        snap.players.append(
            SquadPlayerRow(
                player_id=int(slot.player.id),
                role=slot.role.value,
                bench_order=slot.bench_order,
                is_captain=slot.is_captain,
                current_price=slot.player.price,
                purchase_price=slot.purchase_price,
                sale_value=slot.sale_value,
            )
        )
    session.add(snap)
    session.flush()
    return snap


def latest_team_state(session: Session, matchday: int | None = None) -> TeamState | None:
    query = select(SquadSnapshot).order_by(SquadSnapshot.created_at.desc(), SquadSnapshot.id.desc())
    if matchday is not None:
        query = query.where(SquadSnapshot.matchday == matchday)
    snap = session.scalar(query.limit(1))
    if snap is None:
        return None
    slots = tuple(
        SquadSlot(
            player=to_domain_player(row.player, row.current_price),
            role=Role(row.role),
            bench_order=row.bench_order,
            is_captain=row.is_captain,
            purchase_price=row.purchase_price,
            sale_value=row.sale_value,
        )
        for row in sorted(snap.players, key=lambda r: r.id)
    )
    chips = set()
    if snap.wildcard_used:
        chips.add(Chip.WILDCARD)
    if snap.limitless_used:
        chips.add(Chip.LIMITLESS)
    return TeamState(
        snapshot_id=snap.id,
        matchday=snap.matchday,
        label=snap.label,
        bank=snap.bank,
        free_transfers=snap.free_transfers,
        chips_used=frozenset(chips),
        squad=Squad(slots),
    )


# -- journal -------------------------------------------------------------------------


def add_journal(
    session: Session,
    *,
    kind: str,
    summary: str,
    matchday: int | None = None,
    estimate: str | None = None,
    estimate_author: str | None = None,
    estimate_tag: str = "analyst_estimate",
    decision: str | None = None,
) -> JournalEntry:
    entry = JournalEntry(
        kind=kind,
        summary=summary,
        matchday=matchday,
        estimate=estimate,
        estimate_author=estimate_author,
        estimate_tag=estimate_tag,
        decision=decision,
    )
    session.add(entry)
    session.flush()
    return entry
