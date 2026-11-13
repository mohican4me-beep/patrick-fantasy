# Project status

Updated 13 November 2026.

## Where things stand

Release 1a is complete (Phase 1 and the calculators and tool server), accepted on
13 November 2026. Release 1b (web app) is deferred by Patrick's decision.

Release 2 Phase A (data ingestion) ran for real on 13 November (probe, 12:31 UTC). Two of
three sources work. **ClubElo failed** (HTTP 502), so the phase waits on Patrick's decision.

## Release 2 Phase A acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | All tests pass, output shown | Met | 226 passed; `ruff check` clean |
| 2 | Probe report shows each source working or not, with fields found | Met | `data/probe/report.md`: fixtures ok (144), odds ok (18), ClubElo failed (502) |
| 3 | Matchday 5 fixtures and kick-off times are in the repo and match the game | Met | 18 fixtures; first kick-off 24 Nov 19:45 Athens equals the deadline Patrick read from the game |
| 4 | A broken response leaves existing data untouched | Met | Tests, and the real ClubElo failure wrote no snapshot |
| 5 | No key appears in the repository or its history | Met | Checked after the real run: the saved odds URL shows `apiKey=REDACTED`; no token pattern in the tree |

Found by the real run and fixed: bookmakers quote different goal lines (9 of 19 at 3.5, one
at 2.5 for Galatasaray v Aston Villa), so odds records now keep every line and name the most
quoted one. The 13 November odds snapshot was written by the old parser: its over/under
prices are the 2.5 line from few bookmakers. Six odds club names added to
`data/club_aliases.yaml`; all 36 clubs now match.

Still not tested: the ClubElo parser against a real response; the scheduled (non-probe) run.

## Release 1a, step 2 acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | All tests pass, output shown | Met | 204 passed; `ruff check` clean |
| 2 | Scenarios C and D give the expected numbers and state their assumptions | Met | `test_scenario_c_keep_the_captain_on_seven` (gain -0.6, keep); `test_scenario_d_secured_points_are_lost` |
| 3 | Calculator output is labelled `analyst_estimate` | Met | Tag fixed in `decisions.py`; asserted through the server |
| 4 | The server exposes no tool that changes data | Met | Twelve read-only tools; the database connection refuses INSERT and DELETE; the file is byte-identical after tool calls |
| 5 | Claude can list the squad and validate a transfer from a chat with the repository attached (reworded by Patrick) | Met | Done on 13 November: squad valid; Gadou for a 4.5m defender valid, 0 points, bank 0.3m. The desktop connector is built and tested but was not connected on the host |

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
| 9 | Patrick's real matchday 5 squad is entered and validates | Met | `squads/md05-1-pre-deadline.yaml` imports as VALID: 2-5-5-3, 4-4-2, at most 2 per club against a limit of 3, squad value 99.6m, bank 0.8m, 2 free transfers, Limitless used. Imported on a scratch database; the real database is created on the host at install |
| 10 | Full test output shown | Met | 156 passed; `ruff check` clean |

## Last test run

```
pytest      224 passed in the planning environment (includes launching the server over stdio).
            On the host: 203 of 204 passed before the tzdata fix; the rerun was not reported.
ruff check  All checks passed
ruff format all files formatted
```

Run on Python 3.13 in the planning environment. Not yet run on the host PC.

## Not tested

- Installation and tests on the Windows host.
- Scoring rows not yet seen in real data: saves beyond one block, penalty events, red
  cards, own goals, goals from outside the box, extra time.

## Open items for Patrick

1. Create the two free keys, add them as repository secrets and run the "Fetch data"
   workflow with the probe box ticked (`docs/data-sources.md`).
2. On the host: `git checkout main`, `git pull`, reinstall and report the `pytest` result.
3. Push the `phase-1` tag from the host: this environment could not push tags.
4. Before matchday 5 (24 November, 19:45): send any transfers you are weighing.
3. Whether both chips can be played on one matchday (not urgent).

Done on 13 November: six in-game checks answered; matchday 5 deadline time recorded.

Done: repository created at github.com/mohican4me-beep/patrick-fantasy; host confirmed as
"beast" (AMD Ryzen 5 5600X, 32 GB RAM).

## Next, after Phase 1 is accepted

Release 2 Phase B: the match model (team goal expectations from odds and Elo) once real
fixtures, ratings and odds are flowing. Needs its own approval.

## Known limits of Phase 1

- Deadline clock times are not stored; only dates are known.
- Matchdays 2 and 3 have no deadline date in the rules file. Both are past.
- The `fixture` and `transfer` tables exist but nothing writes to them yet.
- The command line identifies players in a transfer file by exact name.
