# Project status

Updated 13 November 2026.

## Where things stand

Phase 1 (rules engine, schema, command line) is complete. All ten acceptance criteria are
met and Patrick accepted it on 13 November 2026. Tagged `phase-1`.

## Phase 1 acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Every confirmed rule has a passing test naming its rule id | Met | `tests/`, rule ids in docstrings |
| 2 | Every unverified rule blocks, with a test proving no default | Met | Tests cover all five originally open rules. Four are now confirmed by Patrick; `two_chips_same_matchday` still blocks |
| 3 | An illegal squad, lineup or transfer names the rule broken | Met | `Violation.rule_id` and message |
| 4 | Carry gives 3 after one unused league transfer, never more; 0 after a chip or in the knockouts | Met | `test_transfers_chips.py` |
| 5 | Over-limit squad validates with zero transfers, fails with a transfer that leaves it over | Met | `test_inherited_over_limit_squad` |
| 6 | A transfer with an unconfirmed sale value is blocked | Met | `test_unconfirmed_sale_value_blocks_the_transfer` |
| 7 | Scoring reproduces ten real performances from the game, all four positions | Met | `tests/test_real_performances.py`: 11 real breakdowns (2 GK, 4 DEF, 2 MID, 3 FWD) reproduced exactly, component by component |
| 8 | A value changed in the rules file changes behaviour with no code change | Met | `test_changing_the_rules_file_changes_behaviour` |
| 9 | Patrick's real matchday 5 squad is entered and validates | Met | `squads/md5.yaml` imports as VALID: 2-5-5-3, 4-4-2, at most 2 per club against a limit of 3, squad value 99.6m, bank 0.8m, 2 free transfers, Limitless used. Imported on a scratch database; the real database is created on the host at install |
| 10 | Full test output shown | Met | 156 passed; `ruff check` clean |

## Last test run

```
pytest      170 passed
ruff check  All checks passed
ruff format all files formatted
```

Run on Python 3.13 in the planning environment. Not yet run on the host PC.

## Not tested

- Installation and tests on the Windows host.
- Scoring rows not yet seen in real data: saves beyond one block, penalty events, red
  cards, own goals, goals from outside the box, extra time.

## Open items for Patrick

1. Approve or amend the plan for Release 1a, step 2.
2. Install on the host PC and run the tests there (see README).
3. Whether both chips can be played on one matchday (not urgent).

Done on 13 November: six in-game checks answered; matchday 5 deadline time recorded.

Done: repository created at github.com/mohican4me-beep/patrick-fantasy; host confirmed as
"beast" (AMD Ryzen 5 5600X, 32 GB RAM).

## Next, after Phase 1 is accepted

Release 1a, step 2: the read-only tool server for Claude Desktop and Claude Code, and the
captain and substitution calculator. Needs its own approval.

## Known limits of Phase 1

- Deadline clock times are not stored; only dates are known.
- Matchdays 2 and 3 have no deadline date in the rules file. Both are past.
- The `fixture` and `transfer` tables exist but nothing writes to them yet.
- The command line identifies players in a transfer file by exact name.
