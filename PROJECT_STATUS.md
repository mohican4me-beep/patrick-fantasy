# Project status

Updated 13 November 2026.

## Where things stand

Phase 1 (rules engine, schema, command line) is built and its automated tests pass. Two
acceptance criteria need data only Patrick can supply and are still open. Phase 1 is not
complete until they pass.

## Phase 1 acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Every confirmed rule has a passing test naming its rule id | Met | `tests/`, rule ids in docstrings |
| 2 | Every unverified rule blocks, with a test proving no default | Met | Five rules: `selling_value`, `goalkeeper_manual_substitution`, `captain_on_substituted_in`, `late_changes_after_kickoff`, `two_chips_same_matchday` |
| 3 | An illegal squad, lineup or transfer names the rule broken | Met | `Violation.rule_id` and message |
| 4 | Carry gives 3 after one unused league transfer, never more; 0 after a chip or in the knockouts | Met | `test_transfers_chips.py` |
| 5 | Over-limit squad validates with zero transfers, fails with a transfer that leaves it over | Met | `test_inherited_over_limit_squad` |
| 6 | A transfer with an unconfirmed sale value is blocked | Met | `test_unconfirmed_sale_value_blocks_the_transfer` |
| 7 | Scoring reproduces ten real performances from the game, all four positions | **Open** | Needs ten points breakdowns from Patrick |
| 8 | A value changed in the rules file changes behaviour with no code change | Met | `test_changing_the_rules_file_changes_behaviour` |
| 9 | Patrick's real matchday 5 squad is entered and validates | **Open** | Needs the squad |
| 10 | Full test output shown | Met | 156 passed; `ruff check` clean |

## Last test run

```
pytest      156 passed
ruff check  All checks passed
ruff format 25 files already formatted
```

Run on Python 3.13 in the planning environment. Not yet run on the host PC.

## Not tested

- Installation and tests on the Windows host.
- Scoring against real UEFA points (criterion 7).
- Anything involving a real squad (criterion 9).

## Open items for Patrick

1. Create the private GitHub repository so the code can be pushed.
2. Send the matchday 5 squad: fifteen players, clubs, positions, prices, sale values if
   shown, starters, bench order, captain, bank, free transfers, chips used.
3. Send ten points breakdowns from the game, covering all four positions.
4. Make the six checks listed at the end of `FANTASY_RULES.md`.
5. Send the host PC's CPU and memory.

## Next, after Phase 1 is accepted

Release 1a, step 2: the read-only tool server for Claude Desktop and Claude Code, and the
captain and substitution calculator. Needs its own approval.

## Known limits of Phase 1

- Deadline clock times are not stored; only dates are known.
- Matchdays 2 and 3 have no deadline date in the rules file. Both are past.
- The `fixture` and `transfer` tables exist but nothing writes to them yet.
- The command line identifies players in a transfer file by exact name.
