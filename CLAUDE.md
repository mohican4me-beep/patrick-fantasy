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
8. **Free and local.** No paid API, no hosted service, no API key committed.

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
- `src/uclfa/cli.py`: command line.
- `tests/`: each rule test names its rule id in the docstring, in square brackets.

## Conventions

- Python 3.12+, type hints, `ruff` line length 100.
- Observations are appended, never updated: a new price is a new `fantasy_fact` row.
- Times are stored in UTC and shown in Europe/Athens.
- Small commits, one branch per phase, a tag at each approval.
