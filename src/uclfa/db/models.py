"""Database schema.

Fantasy facts are stored in a provider-neutral table: one row per player, fact and
observation time, each with its source and a tag saying whether the value is official,
entered by the user or an analyst estimate. No table mirrors any external feed.
Rows that record observations are append-only: a new observation is a new row.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

POSITIONS = ("GK", "DEF", "MID", "FWD")
SOURCES = ("manual", "file", "derived")
TAGS = ("official", "entered", "analyst_estimate")
ROLES = ("starter", "bench")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


class Club(Base):
    __tablename__ = "club"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    short_code: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    players: Mapped[list[PlayerRow]] = relationship(back_populates="club")


class PlayerRow(Base):
    __tablename__ = "player"
    __table_args__ = (
        UniqueConstraint("name", "club_id", name="uq_player_name_club"),
        CheckConstraint(_in("position", POSITIONS), name="ck_player_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("club.id"))
    position: Mapped[str] = mapped_column(String(3))
    role_tag: Mapped[str | None] = mapped_column(String(30))  # analyst tag, e.g. holding midfielder
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    club: Mapped[Club] = relationship(back_populates="players")


class Fixture(Base):
    __tablename__ = "fixture"
    __table_args__ = (
        UniqueConstraint("matchday", "home_club_id", "away_club_id", name="uq_fixture"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    matchday: Mapped[int] = mapped_column(Integer, index=True)
    playing_date: Mapped[date | None] = mapped_column(Date)
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    home_club_id: Mapped[int] = mapped_column(ForeignKey("club.id"))
    away_club_id: Mapped[int] = mapped_column(ForeignKey("club.id"))
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10), default="manual")


class FantasyFact(Base):
    """One observed fact about a player: price, ownership, points, sale value and so on."""

    __tablename__ = "fantasy_fact"
    __table_args__ = (
        CheckConstraint(_in("source", SOURCES), name="ck_fact_source"),
        CheckConstraint(_in("tag", TAGS), name="ck_fact_tag"),
        Index("ix_fact_player_type_time", "player_id", "fact_type", "observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    fact_type: Mapped[str] = mapped_column(String(30))  # price, ownership, matchday_points ...
    matchday: Mapped[int | None] = mapped_column(Integer)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10))
    tag: Mapped[str] = mapped_column(String(20))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)


class ShortlistEntry(Base):
    __tablename__ = "shortlist_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    player: Mapped[PlayerRow] = relationship()


class SquadSnapshot(Base):
    """The state of the user's team at one moment of one matchday. Never updated."""

    __tablename__ = "squad_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    matchday: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(String(30))  # pre_deadline, after_day_1, pre_limitless ...
    bank: Mapped[float] = mapped_column(Float)
    free_transfers: Mapped[int | None] = mapped_column(Integer)  # null means unlimited
    wildcard_used: Mapped[bool] = mapped_column(Boolean, default=False)
    limitless_used: Mapped[bool] = mapped_column(Boolean, default=False)
    overall_rank: Mapped[int | None] = mapped_column(Integer)
    overall_points: Mapped[int | None] = mapped_column(Integer)
    mini_league_rank: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    players: Mapped[list[SquadPlayerRow]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class SquadPlayerRow(Base):
    __tablename__ = "squad_player"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "player_id", name="uq_squad_player"),
        CheckConstraint(_in("role", ROLES), name="ck_squad_player_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("squad_snapshot.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    role: Mapped[str] = mapped_column(String(8))
    bench_order: Mapped[int | None] = mapped_column(Integer)
    is_captain: Mapped[bool] = mapped_column(Boolean, default=False)
    current_price: Mapped[float | None] = mapped_column(Float)
    purchase_price: Mapped[float | None] = mapped_column(Float)
    sale_value: Mapped[float | None] = mapped_column(Float)

    snapshot: Mapped[SquadSnapshot] = relationship(back_populates="players")
    player: Mapped[PlayerRow] = relationship()


class TransferRow(Base):
    __tablename__ = "transfer"

    id: Mapped[int] = mapped_column(primary_key=True)
    matchday: Mapped[int] = mapped_column(Integer, index=True)
    out_player_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    in_player_id: Mapped[int] = mapped_column(ForeignKey("player.id"))
    sale_value: Mapped[float | None] = mapped_column(Float)
    buy_price: Mapped[float | None] = mapped_column(Float)
    points_cost: Mapped[int] = mapped_column(Integer, default=0)
    chip: Mapped[str | None] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JournalEntry(Base):
    """A decision, the estimate behind it and, later, what happened."""

    __tablename__ = "journal_entry"
    __table_args__ = (CheckConstraint(_in("estimate_tag", TAGS), name="ck_journal_tag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    matchday: Mapped[int | None] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(30))  # transfer, captain, substitution, chip, note
    summary: Mapped[str] = mapped_column(Text)
    estimate: Mapped[str | None] = mapped_column(Text)  # the numbers the decision rested on
    estimate_author: Mapped[str | None] = mapped_column(String(40))  # you, Claude, model version
    estimate_tag: Mapped[str] = mapped_column(String(20), default="analyst_estimate")
    decision: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
