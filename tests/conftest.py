"""Shared fixtures: the real rules file and a legal reference squad."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml

from uclfa.rules import Player, Position, Role, RuleSet, Squad, SquadSlot, load_rules
from uclfa.rules.model import DEFAULT_RULES_PATH

CLUBS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]


@pytest.fixture(scope="session")
def rules() -> RuleSet:
    """The shipped 2026/27 rules with no user confirmations."""
    return load_rules(confirmations_path=None)


@pytest.fixture()
def confirm(tmp_path: Path):
    """Return a loader that applies the given rule confirmations."""

    def _confirm(**values: str) -> RuleSet:
        path = tmp_path / "confirmations.yaml"
        body = {
            "confirmations": {
                rule_id: {"value": value, "confirmed_on": date(2026, 11, 13).isoformat()}
                for rule_id, value in values.items()
            }
        }
        path.write_text(yaml.safe_dump(body), encoding="utf-8")
        return load_rules(confirmations_path=path)

    return _confirm


@pytest.fixture()
def rules_copy(tmp_path: Path):
    """Return a function that loads the rules file after editing its raw content."""

    def _edited(edit) -> RuleSet:
        data = yaml.safe_load(DEFAULT_RULES_PATH.read_text(encoding="utf-8"))
        edit(data)
        path = tmp_path / "rules.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return load_rules(path, confirmations_path=None)

    return _edited


def make_player(pid: str, position: Position, club: str, price: float = 5.0) -> Player:
    return Player(id=pid, name=f"Player {pid}", club=club, position=position, price=price)


def make_squad() -> Squad:
    """A legal 15: 1-4-4-2; bench GK (unnumbered), DEF 1, MID 2, FWD 3. Three per club."""
    layout = [
        ("gk1", Position.GK, Role.STARTER, None),
        ("d1", Position.DEF, Role.STARTER, None),
        ("d2", Position.DEF, Role.STARTER, None),
        ("d3", Position.DEF, Role.STARTER, None),
        ("d4", Position.DEF, Role.STARTER, None),
        ("m1", Position.MID, Role.STARTER, None),
        ("m2", Position.MID, Role.STARTER, None),
        ("m3", Position.MID, Role.STARTER, None),
        ("m4", Position.MID, Role.STARTER, None),
        ("f1", Position.FWD, Role.STARTER, None),
        ("f2", Position.FWD, Role.STARTER, None),
        ("gk2", Position.GK, Role.BENCH, None),
        ("d5", Position.DEF, Role.BENCH, 1),
        ("m5", Position.MID, Role.BENCH, 2),
        ("f3", Position.FWD, Role.BENCH, 3),
    ]
    slots = []
    for index, (pid, position, role, order) in enumerate(layout):
        slots.append(
            SquadSlot(
                player=make_player(pid, position, CLUBS[index % len(CLUBS)]),
                role=role,
                bench_order=order,
                is_captain=pid == "f1",
                purchase_price=5.0,
                sale_value=5.0,
            )
        )
    return Squad(tuple(slots))


@pytest.fixture()
def squad() -> Squad:
    return make_squad()


def change(squad: Squad, pid: str, **fields) -> Squad:
    slot = squad.slot(pid)
    assert slot is not None
    return squad.with_slot(replace(slot, **fields))


def move_to_club(squad: Squad, pid: str, club: str) -> Squad:
    slot = squad.slot(pid)
    assert slot is not None
    return squad.with_slot(replace(slot, player=replace(slot.player, club=club)))
