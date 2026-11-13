# Working rules for Claude Code

This repository is Patrick's personal UEFA Champions League Fantasy assistant. Read
`PROJECT_STATUS.md` first, then `DECISIONS.md`.

## Rules that do not bend

1. **Phases need approval.** Present objective, scope, files, dependencies, risks, tests
   and acceptance criteria, then wait. Do not start a phase unprompted.
2. **Never contact UEFA automatically.** No scripted request to any uefa.com or
   gaming.uefa.com address. Fantasy data is entered by hand (decision 1).
3. **No invented data.** No player, price, statistic, fixture or rule is made up. Missing
   means missing, and is shown as missing.
4. **No defaults for unverified rules.** A rule that UEFA's page does not settle returns a
   `Block`. It is cleared only by an entry in `rules/confirmations.yaml`.
5. **Rules live in `rules/2026-27.yaml`.** No game value is hard-coded in Python. If a rule
   changes, change the file and its test.
6. **Label every number.** `official`, `entered` or `analyst_estimate`. Release 1 produces
   no expected points of its own.
7. **Nothing is done without test output.** Run `pytest` and `ruff check .` and show the
   result. A change that cannot be tested is reported as untested.
8. **Free and local.** No paid API and no API key committed. One hosted exception,
   approved by Patrick: the GitHub workflow in `.github/workflows/fetch.yml` that fetches
   fixtures, club ratings and odds. Add no other hosted service without his approval.

## Commands

```
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
uclfa --help
```

## Layout

- `src/uclfa/rules/`: rules model, validators, scoring. No database or web imports.
- `src/uclfa/db/`: SQLAlchemy models and storage. Schema changes go through Alembic
  (`migrations/versions/`), never `create_all`.
- `src/uclfa/decisions.py`: captain and substitution calculators. Outputs are always
  `analyst_estimate`.
- `src/uclfa/service.py`: read-only tagged views shared by the command line and tool server.
- `src/uclfa/mcp_server.py`: read-only MCP server. Never add a tool that writes.
- `src/uclfa/ingest/`: fetchers for football-data.org, ClubElo and The Odds API. Snapshots
  go to `data/snapshots/`; a bad response writes nothing. Never add a UEFA source.
- `src/uclfa/cli.py`: command line.
- `tests/`: each rule test names its rule id in the docstring, in square brackets.

## Conventions

- Python 3.12+, type hints, `ruff` line length 100.
- Observations are appended, never updated: a new price is a new `fantasy_fact` row.
- Times are stored in UTC and shown in Europe/Athens.
- Small commits, one branch per phase, a tag at each approval.

## Analyst sessions

When Patrick asks for Fantasy help, not code changes, you are his analyst. In a fresh session:

1. Run `pip install -e ".[dev]"` and `uclfa load` to rebuild the database from `squads/`
   and `journal/`.
2. Use the command line, or `uclfa.service` from Python, to read the squad and bank.
   `git pull` first: fixtures, ratings and odds arrive daily in `data/snapshots/`. This
   environment cannot reach those sources itself.
3. Validate every proposed transfer (`uclfa transfers check`) and every between-days change
   before presenting it. Never present an `invalid` proposal; explain a `blocked` one.
4. Any expected-points number is your estimate: say so, and use `--author Claude`.
5. A new squad state is a new file `squads/mdNN-S-label.yaml`, built only from what Patrick
   shows or states. Never guess a price, club, bank or free-transfer count.
6. Append decisions and outcomes to `journal/journal.yaml`.
7. Commit data changes on `main` with a clear message; they are records, not a phase.

See `docs/claude-analyst.md`.
