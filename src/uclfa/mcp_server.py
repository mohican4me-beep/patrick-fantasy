"""Read-only tool server for Claude Desktop and Claude Code.

Run with `uclfa mcp` (standard input and output; no network port). Every tool reads; none
writes. The database connection is opened read-only, so even a faulty tool cannot change
your data. The calculators compute from numbers the caller supplies and store nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session

from uclfa import service
from uclfa.db import store
from uclfa.rules import RuleSet, load_rules

INSTRUCTIONS = """\
You are helping Patrick with his UEFA Champions League Fantasy team, "Pistolia Fc".
These tools expose his own records and a verified rules engine. They are read-only.

How to use them honestly:
1. Quote only values the tools return, with their tag. `entered` means Patrick typed it
   from the game; `official` means UEFA's published rules; `unavailable` means there is no
   data. Never fill an `unavailable` value from memory and present it as fact.
2. This release has no prediction model. Any expected-points number is your estimate or
   Patrick's. Say so every time, and pass your name as `estimate_author`.
3. Before proposing a transfer, call `validate_transfers`. Before proposing a substitution
   or captain change between playing days, call `validate_between_days`. Do not present a
   proposal whose status is `invalid`; explain a `blocked` one and which rule is unverified.
4. The calculators judge expected points only. State their assumptions when you rely on them.
5. You cannot change Patrick's squad or his UEFA account. He makes every change himself in
   the UEFA app.
"""

DB_MISSING = {"error": "No database found. Run `uclfa init-db` and import a squad first."}


def build_server(db_path: Path | str | None = None, rules: RuleSet | None = None) -> MCPServer:
    """Create the server. Paths and rules can be injected for tests."""
    server = MCPServer(name="patrick-fantasy", instructions=INSTRUCTIONS, version="0.2.0")

    def current_rules() -> RuleSet:
        return rules if rules is not None else load_rules()

    def with_session(view: Callable[[Session], dict[str, Any]]) -> dict[str, Any]:
        path = Path(db_path) if db_path is not None else store.db_path()
        if not path.exists():
            return dict(DB_MISSING)
        engine = store.make_readonly_engine(path)
        try:
            with Session(engine) as session:
                return view(session)
        finally:
            engine.dispose()

    @server.tool()
    def get_squad() -> dict[str, Any]:
        """Patrick's saved squad: starting eleven, bench order, captain, prices and sale values."""
        return with_session(lambda s: service.squad_view(s, current_rules()))

    @server.tool()
    def get_bank_and_transfers() -> dict[str, Any]:
        """Bank, squad value, free transfers, chips used and available, club limit and deadline."""
        return with_session(lambda s: service.bank_view(s, current_rules()))

    @server.tool()
    def list_shortlist() -> dict[str, Any]:
        """Players Patrick is tracking, with the latest price and ownership he entered."""
        return with_session(service.shortlist_view)

    @server.tool()
    def compare_players(names: list[str]) -> dict[str, Any]:
        """Stored facts for the named players side by side. No projections exist yet."""
        return with_session(lambda s: service.compare_view(s, names))

    @server.tool()
    def list_fixtures(matchday: int | None = None) -> dict[str, Any]:
        """Fixtures entered so far. Returns `unavailable` when none have been entered."""
        return with_session(lambda s: service.fixtures_view(s, matchday))

    @server.tool()
    def get_rules() -> dict[str, Any]:
        """The 2026/27 rules as implemented, with each rule's verification status."""
        return service.rules_view(current_rules())

    @server.tool()
    def get_journal(limit: int = 20) -> dict[str, Any]:
        """Recent decision-journal entries, newest first."""
        return with_session(lambda s: service.journal_view(s, limit))

    @server.tool()
    def validate_squad() -> dict[str, Any]:
        """Check the saved squad and lineup against the rules."""
        return with_session(lambda s: service.validate_saved_squad(s, current_rules()))

    @server.tool()
    def validate_transfers(
        transfers: list[dict[str, Any]], chip: str | None = None, matchday: int | None = None
    ) -> dict[str, Any]:
        """Check proposed transfers: legality, points deducted, bank afterwards and next
        matchday's free transfers. Each transfer is
        {"out": "<squad player>", "in": {"name", "club", "position", "price"}}.
        `chip` may be "wildcard" or "limitless". Nothing is saved."""
        return with_session(
            lambda s: service.validate_transfers_view(
                s, current_rules(), transfers, chip=chip, matchday=matchday
            )
        )

    @server.tool()
    def validate_between_days(
        substitutions: list[dict[str, str]] | None = None,
        new_captain: str | None = None,
        played: list[str] | None = None,
        sent_off: list[str] | None = None,
        previous_captains: list[str] | None = None,
        next_day_started: bool = False,
    ) -> dict[str, Any]:
        """Check manual substitutions and a captain switch between playing days.
        `substitutions` are {"out": name, "in": name}. `played` lists squad players whose
        team has already played this matchday. Nothing is saved."""
        return with_session(
            lambda s: service.validate_between_days_view(
                s,
                current_rules(),
                substitutions=substitutions,
                new_captain=new_captain,
                played=played,
                sent_off=sent_off,
                previous_captains=previous_captains,
                next_day_started=next_day_started,
            )
        )

    @server.tool()
    def captain_switch_value(
        current_captain_points: float,
        candidates: list[dict[str, Any]],
        estimate_author: str,
        auto_sub_risks: list[dict[str, Any]] | None = None,
        automatic_substitutions_already_disabled: bool = False,
    ) -> dict[str, Any]:
        """Expected gain from moving the armband off a captain who has played.
        `candidates` are {"name", "expected_points"}; those expected points are estimates
        and `estimate_author` says whose. `auto_sub_risks` are
        {"player", "probability_not_playing", "replacement_expected_points"} for later
        starters who might not play. The result is always an analyst estimate."""
        return service.captain_view(
            current_rules(),
            current_captain_points,
            candidates,
            estimate_author=estimate_author,
            auto_sub_risks=auto_sub_risks,
            automatic_substitutions_already_disabled=automatic_substitutions_already_disabled,
        )

    @server.tool()
    def substitution_value(
        swaps: list[dict[str, Any]],
        estimate_author: str,
        auto_sub_risks: list[dict[str, Any]] | None = None,
        automatic_substitutions_already_disabled: bool = False,
    ) -> dict[str, Any]:
        """Expected gain from manual substitutions between playing days. Each swap is
        {"out", "in", "in_expected_points"} plus exactly one of "out_realised_points" (he
        has played; those points are lost) or "out_expected_points" (still to play), and
        optionally "out_is_captain". The result is always an analyst estimate."""
        return service.substitution_view(
            current_rules(),
            swaps,
            estimate_author=estimate_author,
            auto_sub_risks=auto_sub_risks,
            automatic_substitutions_already_disabled=automatic_substitutions_already_disabled,
        )

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
