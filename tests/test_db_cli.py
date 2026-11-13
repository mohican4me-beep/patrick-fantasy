"""Database migration, storage round trip and the command line."""

from pathlib import Path

import pytest
import yaml
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from uclfa import cli
from uclfa.db import store
from uclfa.db.models import FantasyFact, SquadSnapshot
from uclfa.rules import Chip, Position, validate_lineup, validate_squad

from .conftest import make_squad

EXPECTED_TABLES = {
    "club",
    "player",
    "fixture",
    "fantasy_fact",
    "shortlist_entry",
    "squad_snapshot",
    "squad_player",
    "transfer",
    "journal_entry",
}


@pytest.fixture()
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "test.db"
    monkeypatch.setenv("UCLFA_DB", str(path))
    monkeypatch.setenv("UCLFA_CONFIRMATIONS", str(tmp_path / "no-confirmations.yaml"))
    store.migrate(path)
    return path


def squad_file(tmp_path: Path, **overrides) -> Path:
    players = []
    for slot in make_squad().slots:
        players.append(
            {
                "name": slot.player.name,
                "club": slot.player.club,
                "position": slot.player.position.value,
                "price": 5.0,
                "purchase_price": 5.0,
                "sale_value": 5.0,
                "role": slot.role.value,
                "bench_order": slot.bench_order,
                "captain": slot.is_captain,
            }
        )
    data = {
        "matchday": 5,
        "label": "pre_deadline",
        "bank": 1.0,
        "free_transfers": 2,
        "chips_used": [],
        "players": players,
    }
    data.update(overrides)
    path = tmp_path / "squad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_migration_creates_the_schema(db):
    tables = set(inspect(store.make_engine(db)).get_table_names())
    assert EXPECTED_TABLES <= tables
    assert not any("feed" in t for t in tables)  # no table mirrors an external feed


def test_migration_is_repeatable(db):
    store.migrate(db)  # running it again must not fail or change anything


def test_fact_tags_and_sources_are_constrained(db):
    from sqlalchemy.exc import IntegrityError

    with Session(store.make_engine(db)) as session:
        player = store.get_or_create_player(session, "Test Player", "Alpha", Position.MID)
        store.record_fact(session, player, "price", value_num=5.0, source="scraped")
        with pytest.raises(IntegrityError):
            session.commit()


def test_facts_are_appended_not_overwritten(db):
    with Session(store.make_engine(db)) as session:
        player = store.get_or_create_player(session, "Test Player", "Alpha", Position.MID)
        store.record_fact(session, player, "price", value_num=5.0)
        store.record_fact(session, player, "price", value_num=5.2)
        session.commit()
        facts = session.scalars(select(FantasyFact).where(FantasyFact.fact_type == "price")).all()
        assert [f.value_num for f in facts] == [5.0, 5.2]
        assert store.latest_fact(session, player.id, "price").value_num == 5.2
        assert {f.tag for f in facts} == {"entered"} and {f.source for f in facts} == {"manual"}


def test_position_conflict_is_refused(db):
    with Session(store.make_engine(db)) as session:
        store.get_or_create_player(session, "Test Player", "Alpha", Position.MID)
        with pytest.raises(ValueError):
            store.get_or_create_player(session, "Test Player", "Alpha", Position.FWD)


def test_squad_import_show_and_reload(db, tmp_path, rules, capsys):
    assert cli.main(["squad", "import", str(squad_file(tmp_path))]) == 0
    assert "VALID" in capsys.readouterr().out
    with Session(store.make_engine(db)) as session:
        state = store.latest_team_state(session)
        assert state.matchday == 5 and state.bank == 1.0 and state.free_transfers == 2
        assert state.chips_used == frozenset()
        assert len(state.squad.slots) == 15
        assert state.squad.captain.player.name == "Player f1"
        assert validate_squad(state.squad, 5, rules).ok and validate_lineup(state.squad, rules).ok
    assert cli.main(["squad", "show"]) == 0
    shown = capsys.readouterr().out
    assert "Player f1 (C)" in shown and "Bench" in shown
    assert cli.main(["squad", "validate"]) == 0


def test_illegal_squad_is_not_saved(db, tmp_path, capsys):
    file = squad_file(tmp_path)
    data = yaml.safe_load(file.read_text())
    data["players"][-1]["position"] = "MID"  # six midfielders, two forwards
    file.write_text(yaml.safe_dump(data))
    assert cli.main(["squad", "import", str(file)]) == 1
    out = capsys.readouterr().out
    assert "INVALID" in out and "squad_composition" in out and "Nothing was saved" in out
    with Session(store.make_engine(db)) as session:
        assert session.scalars(select(SquadSnapshot)).all() == []


def test_snapshots_accumulate_and_chips_persist(db, tmp_path):
    cli.main(["squad", "import", str(squad_file(tmp_path))])
    cli.main(
        ["squad", "import", str(squad_file(tmp_path, label="after_day_1", chips_used=["wildcard"]))]
    )
    with Session(store.make_engine(db)) as session:
        assert len(session.scalars(select(SquadSnapshot)).all()) == 2
        state = store.latest_team_state(session)
        assert state.label == "after_day_1" and state.chips_used == frozenset({Chip.WILDCARD})


def test_transfers_check_reports_cost_and_blocks(db, tmp_path, capsys):
    cli.main(["squad", "import", str(squad_file(tmp_path))])
    capsys.readouterr()
    plan = tmp_path / "transfers.yaml"
    plan.write_text(
        yaml.safe_dump(
            {
                "transfers": [
                    {
                        "out": "Player m1",
                        "in": {
                            "name": "New One",
                            "club": "Yankee",
                            "position": "MID",
                            "price": 5.5,
                        },
                    }
                ]
            }
        )
    )
    assert cli.main(["transfers", "check", str(plan)]) == 0
    out = capsys.readouterr().out
    assert "VALID" in out and "points deducted: 0" in out and "bank afterwards: 0.5" in out
    assert "free transfers next matchday: 3" in out


def test_transfers_check_blocks_unknown_sale_value(db, tmp_path, capsys):
    file = squad_file(tmp_path)
    data = yaml.safe_load(file.read_text())
    for p in data["players"]:
        p["sale_value"] = None
    file.write_text(yaml.safe_dump(data))
    cli.main(["squad", "import", str(file)])
    capsys.readouterr()
    plan = tmp_path / "transfers.yaml"
    plan.write_text(
        yaml.safe_dump(
            {
                "transfers": [
                    {
                        "out": "Player m1",
                        "in": {
                            "name": "New One",
                            "club": "Yankee",
                            "position": "MID",
                            "price": 5.0,
                        },
                    }
                ]
            }
        )
    )
    assert cli.main(["transfers", "check", str(plan)]) == 1
    out = capsys.readouterr().out
    assert "BLOCKED [selling_value]" in out and "bank afterwards: -" in out


def test_shortlist_score_rules_and_journal_commands(db, capsys):
    assert (
        cli.main(
            [
                "player",
                "add",
                "--name",
                "Some Mid",
                "--club",
                "Alpha",
                "--position",
                "MID",
                "--price",
                "6.5",
                "--ownership",
                "12",
            ]
        )
        == 0
    )
    assert cli.main(["shortlist"]) == 0
    assert "Some Mid" in capsys.readouterr().out

    assert (
        cli.main(
            ["score", "--position", "MID", "--minutes", "90", "--goals", "1", "--recoveries", "7"]
        )
        == 0
    )
    assert "total" in (out := capsys.readouterr().out) and " 10" in out

    assert cli.main(["rules", "status"]) == 0
    status = capsys.readouterr().out
    assert "unverified" in status and "selling_value" in status

    assert (
        cli.main(
            [
                "journal",
                "add",
                "--kind",
                "captain",
                "--summary",
                "Kept day-one captain on 7",
                "--matchday",
                "5",
                "--estimate",
                "day-two option 6.4",
                "--author",
                "Patrick",
            ]
        )
        == 0
    )
    assert cli.main(["journal", "list"]) == 0
    listed = capsys.readouterr().out
    assert "Kept day-one captain" in listed and "analyst_estimate" in listed


def test_squad_without_free_transfers_is_checked_but_not_saved(db, tmp_path, capsys):
    """A missing free-transfer count is never read as unlimited."""
    file = squad_file(tmp_path, free_transfers=None)
    assert cli.main(["squad", "import", str(file)]) == 1
    out = capsys.readouterr().out
    assert "VALID" in out and "free_transfers is missing" in out
    with Session(store.make_engine(db)) as session:
        assert session.scalars(select(SquadSnapshot)).all() == []


def test_load_rebuilds_the_database_from_repository_files(db, tmp_path, capsys):
    """A fresh Claude session rebuilds its database from squads/ and journal/."""
    root = tmp_path / "repo"
    (root / "squads").mkdir(parents=True)
    (root / "journal").mkdir()
    first = squad_file(tmp_path, label="pre_deadline")
    (root / "squads" / "md05-1-pre-deadline.yaml").write_text(first.read_text())
    second = squad_file(tmp_path, label="after_day_1", bank=0.4)
    (root / "squads" / "md05-2-after-day-1.yaml").write_text(second.read_text())
    (root / "journal" / "journal.yaml").write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "kind": "captain",
                        "summary": "Kept the day-one captain",
                        "matchday": 5,
                        "estimate": "alternative 6.4",
                        "estimate_author": "Claude",
                        "outcome": "captain scored 7",
                    }
                ]
            }
        )
    )
    cli.main(["journal", "add", "--kind", "note", "--summary", "stale entry to be replaced"])
    assert cli.main(["load", "--root", str(root)]) == 0
    assert "Loaded 2 squad file(s); journal entries: 1." in capsys.readouterr().out
    with Session(store.make_engine(db)) as session:
        state = store.latest_team_state(session)
        assert state.label == "after_day_1" and state.bank == 0.4  # last file is current
        assert len(session.scalars(select(SquadSnapshot)).all()) == 2
    cli.main(["journal", "list"])
    listed = capsys.readouterr().out
    assert "Kept the day-one captain" in listed and "outcome: captain scored 7" in listed
    assert "stale entry" not in listed  # the database was rebuilt, not appended to


def test_load_stops_on_an_illegal_squad_file(db, tmp_path, capsys):
    root = tmp_path / "repo"
    (root / "squads").mkdir(parents=True)
    file = squad_file(tmp_path)
    data = yaml.safe_load(file.read_text())
    data["players"][-1]["position"] = "MID"
    (root / "squads" / "md05-1-bad.yaml").write_text(yaml.safe_dump(data))
    assert cli.main(["load", "--root", str(root)]) == 1
    assert "did not import" in capsys.readouterr().out
