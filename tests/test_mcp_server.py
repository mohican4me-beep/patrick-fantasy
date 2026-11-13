"""The read-only tool server, exercised through the MCP client against Patrick's real
matchday 5 squad file."""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from uclfa import cli
from uclfa.db import store
from uclfa.mcp_server import INSTRUCTIONS, build_server
from uclfa.rules.model import REPO_ROOT

REAL_SQUAD = REPO_ROOT / "squads" / "md05-1-pre-deadline.yaml"

EXPECTED_TOOLS = {
    "get_squad",
    "get_bank_and_transfers",
    "list_shortlist",
    "compare_players",
    "list_fixtures",
    "get_rules",
    "get_journal",
    "validate_squad",
    "validate_transfers",
    "validate_between_days",
    "captain_switch_value",
    "substitution_value",
}
WRITE_WORDS = ("add", "create", "update", "delete", "save", "import", "set", "write", "confirm")


@pytest.fixture()
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "mcp.db"
    monkeypatch.setenv("UCLFA_DB", str(path))
    store.migrate(path)
    assert cli.main(["squad", "import", str(REAL_SQUAD)]) == 0
    return path


@pytest.fixture()
def call(db, confirm):
    """Call a tool through a real MCP client session and return its structured result."""
    rules = confirm(
        selling_value="current_price",
        goalkeeper_manual_substitution="allowed",
        captain_on_substituted_in="allowed",
        late_changes_after_kickoff="not_allowed",
    )
    server = build_server(db, rules=rules)

    def _call(tool: str, **arguments):
        async def run():
            async with Client(server) as client:
                result = await client.call_tool(tool, arguments)
                assert not result.is_error, result.content
                return result.structured_content

        return asyncio.run(run())

    return _call


def test_tools_are_exactly_the_read_only_set(db):
    async def run():
        async with Client(build_server(db)) as client:
            return await client.list_tools(), client.instructions

    tools, instructions = asyncio.run(run())
    names = {t.name for t in tools.tools}
    assert names == EXPECTED_TOOLS
    assert not [n for n in names if n.split("_")[0] in WRITE_WORDS]
    assert instructions == INSTRUCTIONS and "read-only" in instructions


def test_database_connection_cannot_write(db):
    """Acceptance: the server's connection refuses every write."""
    engine = store.make_readonly_engine(db)
    with Session(engine) as session:
        assert session.execute(text("SELECT count(*) FROM squad_snapshot")).scalar() == 1
        with pytest.raises(OperationalError):
            session.execute(text("INSERT INTO club (name, created_at) VALUES ('X', '2026-01-01')"))
        with pytest.raises(OperationalError):
            session.execute(text("DELETE FROM squad_snapshot"))
    engine.dispose()


def test_tool_calls_leave_the_database_unchanged(db, call):
    before = db.read_bytes()
    call("get_squad")
    call("validate_squad")
    call(
        "validate_transfers",
        transfers=[
            {"out": "Gadou", "in": {"name": "X", "club": "Y", "position": "DEF", "price": 4.0}}
        ],
    )
    call("validate_between_days", new_captain="Kane", played=["Raphinha"])
    assert db.read_bytes() == before


def test_get_squad_returns_tagged_real_squad(call):
    squad = call("get_squad")
    assert squad["matchday"] == 5
    starters = {p["name"]: p for p in squad["starting_eleven"]}
    assert len(starters) == 11 and len(squad["bench"]) == 4
    assert starters["Raphinha"]["captain"] is True
    assert starters["H. Kane"]["price"] == {"value": 11.2, "tag": "entered"}
    assert starters["H. Kane"]["sale_value"] == {
        "value": 11.2,
        "tag": "derived_from_confirmed_rule",
    }
    assert [p["name"] for p in squad["bench"]] == [
        "G. Kobel",
        "Vinicius Junior",
        "K. Mbappe",
        "R. Calafiori",
    ]


def test_bank_and_transfers(call):
    bank = call("get_bank_and_transfers")
    assert bank["bank"] == {"value": 0.8, "tag": "entered"}
    assert bank["squad_value"]["value"] == 99.6
    assert bank["free_transfers"]["value"] == 2
    assert bank["chips_used"] == ["limitless"] and bank["chips_available"] == ["wildcard"]
    assert bank["club_limit"] == {"value": 3, "tag": "official"}
    assert bank["deadline_utc"]["value"].startswith("2026-11-24T17:45")


def test_validate_squad(call):
    assert call("validate_squad")["status"] == "valid"


def test_missing_data_is_reported_as_unavailable(call):
    assert call("list_fixtures")["tag"] == "unavailable"
    compared = call("compare_players", names=["Kane", "Nobody Known"])["players"]
    assert compared[0]["price"]["value"] == 11.2
    assert compared[0]["ownership"] == {"value": None, "tag": "unavailable"}
    assert compared[0]["expected_points"] == {"value": None, "tag": "unavailable"}
    assert compared[1]["error"] == "not found in the database"


def test_validate_transfers_legal(call):
    result = call(
        "validate_transfers",
        transfers=[
            {
                "out": "Gadou",
                "in": {"name": "New Def", "club": "Lille", "position": "DEF", "price": 4.5},
            }
        ],
    )
    assert result["status"] == "valid"
    assert result["points_deducted"] == {"value": 0, "tag": "official"}
    assert result["bank_after"]["value"] == 0.3
    assert result["free_transfers_next_matchday"] == 3


def test_validate_transfers_names_the_rule_broken(call):
    """Acceptance: an illegal proposal comes back with the rule broken."""
    over_budget = call(
        "validate_transfers",
        transfers=[
            {
                "out": "Gadou",
                "in": {"name": "Dear Def", "club": "Lille", "position": "DEF", "price": 6.0},
            }
        ],
    )
    assert over_budget["status"] == "invalid"
    assert over_budget["rules_broken"][0]["rule_id"] == "budget_by_stage"

    third = {"name": "Third", "club": "Barcelona", "position": "DEF", "price": 4.0}
    fourth = {"name": "Fourth", "club": "Barcelona", "position": "DEF", "price": 4.0}
    crowded = call(
        "validate_transfers",
        transfers=[{"out": "Gadou", "in": third}, {"out": "Geertruida", "in": fourth}],
    )
    assert "club_limit_by_stage" in {r["rule_id"] for r in crowded["rules_broken"]}

    used_chip = call("validate_transfers", transfers=[], chip="limitless")
    assert "chips" in {r["rule_id"] for r in used_chip["rules_broken"]}


def test_validate_transfers_hit(call):
    def new(i):
        return {"name": f"New {i}", "club": f"Club {i}", "position": "DEF", "price": 4.0}

    result = call(
        "validate_transfers",
        transfers=[
            {"out": "Gadou", "in": new(1)},
            {"out": "Geertruida", "in": new(2)},
            {"out": "Calafiori", "in": new(3)},
        ],
    )
    assert result["paid_transfers"] == 1 and result["points_deducted"]["value"] == 4


def test_unknown_player_is_an_error_not_a_guess(call):
    result = call(
        "validate_transfers",
        transfers=[
            {"out": "Haaland", "in": {"name": "X", "club": "Y", "position": "FWD", "price": 5.0}}
        ],
    )
    assert "not in the saved squad" in result["error"]


def test_validate_between_days_on_the_real_squad(call):
    # Day one: Barcelona, Bayern, Man Utd and PSV have played; Real Madrid play on day two.
    played = ["Joan Garcia", "Raphinha", "Kane", "Mbeumo", "Bruno Fernandes", "Geertruida"]
    switch = call("validate_between_days", new_captain="Joao Neves", played=played)
    assert switch["status"] == "valid" and switch["lineup_after"]["captain"] == "Joao Neves"
    assert switch["automatic_substitutions_disabled"] is True

    refused = call("validate_between_days", new_captain="Kane", played=played)
    assert refused["rules_broken"][0]["rule_id"] == "captain_switch"

    sub = call(
        "validate_between_days",
        substitutions=[{"out": "Mbeumo", "in": "Mbappe"}],
        played=played,
    )
    assert sub["status"] == "valid" and "K. Mbappe" in sub["lineup_after"]["starting_eleven"]

    late = call(
        "validate_between_days", new_captain="Joao Neves", played=played, next_day_started=True
    )
    assert late["rules_broken"][0]["rule_id"] == "late_changes_after_kickoff"


def test_calculators_through_the_server(call):
    captain = call(
        "captain_switch_value",
        current_captain_points=7,
        candidates=[{"name": "Day-two option", "expected_points": 6.4}],
        estimate_author="Claude",
    )
    assert captain["recommendation"] == "keep" and captain["gains"] == {"Day-two option": -0.6}
    assert captain["tag"] == "analyst_estimate" and captain["estimate_author"] == "Claude"

    swap = call(
        "substitution_value",
        swaps=[
            {"out": "Starter", "in": "Bench", "in_expected_points": 6.4, "out_realised_points": 7}
        ],
        estimate_author="Claude",
    )
    assert swap["recommendation"] == "none" and swap["tag"] == "analyst_estimate"
    assert swap["swaps"][0]["points_given_up_tag"] == "entered"

    bad = call(
        "substitution_value",
        swaps=[{"out": "A", "in": "B", "in_expected_points": 4}],
        estimate_author="Claude",
    )
    assert "exactly one" in bad["error"]


def test_rules_tool_reports_verification_status(call):
    rules = call("get_rules")
    assert rules["register"]["selling_value"]["confirmed_value"] == "current_price"
    assert rules["register"]["two_chips_same_matchday"]["status"] == "unverified"
    assert rules["scoring"]["balls_recovered_block"] == 3


def test_no_database_is_reported(tmp_path):
    async def run():
        async with Client(build_server(tmp_path / "missing.db")) as client:
            return (await client.call_tool("get_squad", {})).structured_content

    assert "No database found" in asyncio.run(run())["error"]


def test_server_starts_over_standard_input_and_output(db):
    """End to end: launch `python -m uclfa.mcp_server` as Claude Desktop would."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "uclfa.mcp_server"],
        env={**os.environ, "UCLFA_DB": str(db)},
    )

    async def run():
        async with Client(params) as client:
            tools = await client.list_tools()
            squad = await client.call_tool("get_squad", {})
            return {t.name for t in tools.tools}, squad.structured_content

    names, squad = asyncio.run(run())
    assert names == EXPECTED_TOOLS and squad["matchday"] == 5
