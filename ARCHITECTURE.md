# Architecture

Local-first modular monolith. One Python package, one SQLite file, hosted on the Windows
PC "beast". Phase 1 contains the two bottom layers and a command line.

## Layers

| Layer | Package | Depends on | Phase |
|---|---|---|---|
| Rules engine | `uclfa.rules` | Pydantic, PyYAML | 1 (done) |
| Storage | `uclfa.db` | SQLAlchemy, Alembic, rules types | 1 (done) |
| Command line | `uclfa.cli` | rules, storage | 1 (done) |
| Read-only tool server for Claude | `uclfa.mcp` | rules, storage | 1a, next |
| Web API and front end | to come | all of the above | 1b |
| Ingestion, model, optimizer | to come | | Release 2 |

The rules engine imports nothing from storage or the command line, so it can be tested and
reused alone.

## Rules engine

- `rules/2026-27.yaml` holds every game value and a verification register.
- `rules/confirmations.yaml` holds rules the user has checked in the game.
- `model.py` loads both into a frozen `RuleSet`.
- `validators.py` checks squads, lineups, transfers, chips and between-days changes.
- `scoring.py` turns one player's match events into points.

Each validator returns a `Result` with three lists: violations (a rule is broken), blocks
(a needed rule is unverified) and notes. Status is `invalid`, `blocked` or `valid`, in that
order of precedence.

## Storage

Nine tables. Fantasy facts are provider-neutral: one row per player, fact type and
observation time, with a `source` (`manual`, `file`, `derived`) and a `tag` (`official`,
`entered`, `analyst_estimate`). No table mirrors an external feed.

| Table | Holds |
|---|---|
| `club`, `player` | Entities you have entered |
| `fixture` | Matches, for later phases |
| `fantasy_fact` | Prices, ownership, points, sale values; append-only |
| `shortlist_entry` | Players you are tracking |
| `squad_snapshot`, `squad_player` | Your team at one moment; never updated |
| `transfer` | Transfers made |
| `journal_entry` | Decisions, the estimate behind them, the outcome |

Schema changes are Alembic migrations. `uclfa init-db` upgrades to the latest.

## What is deliberately absent

No network calls, no scheduler, no model, no optimizer, no web server, no authentication.
Each arrives in its own approved phase.
