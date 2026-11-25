# Project status

Updated 15 November 2026.

## Where things stand

Release 1a is complete (Phase 1 and the calculators and tool server), accepted on
13 November 2026. Release 1b (web app) is deferred by Patrick's decision.

Release 2 Phase A (data ingestion) was **accepted by Patrick on 15 November 2026**. Fixtures and odds
arrive daily from GitHub Actions. ClubElo was dropped on 15 November (Patrick's decision).

Release 2 Phase B (match model) was **accepted by Patrick on 15 November 2026** and merged
into `main`.

Release 2 Phases C (player expected points) and D (optimizer) were **accepted by Patrick on
24 November 2026** and merged into `main`. They produced the Matchday 5 Wildcard squad.

## Release 2 Phases C and D acceptance criteria (accepted 24 November 2026)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | All tests pass, lint clean | Met | 266 passed; `ruff check` clean |
| 2 | Points formula matches hand-worked examples and the scoring engine | Met | `tests/test_player_model.py`, including a 40,000-match simulation per position |
| 3 | Every optimizer plan passes the rules engine | Met | `tests/test_optimize.py`; real MD5 plans all `valid` |
| 4 | Optimizer matches brute force on small cases | Met | `test_one_transfer_matches_brute_force` |
| 5 | Every number tagged with source; missing inputs stay missing | Met | Pool prices `entered`/`third_party` with date; players without inputs get no number |
| 6 | Method and limits written up | Met | `docs/model.md` |

Known limits: one matchday at a time; ball recoveries are position averages; player of the
match not modelled; inputs are baselines from league stats plus team news.

## Release 2 Phase B acceptance criteria (accepted 15 November 2026)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | All tests pass, lint clean, output shown | Met | 245 passed; `ruff check` clean |
| 2 | `uclfa outlook --matchday 5` lists all 18 matches with expected goals, clean-sheet and scoring chances, odds age and bookmaker count, or a reason | Met | 18 fitted, 0 unavailable on the 15 November odds; `test_every_matchday_5_match_is_fitted_from_real_odds` |
| 3 | Each fitted match reproduces the market within 1 point, or is flagged | Met | 15 within 1 point; 3 even games (Galatasaray v Aston Villa, Shakhtar v Fenerbahçe, Sporting v Man Utd) miss the draw by 1.0 to 1.1 points and are marked low confidence |
| 4 | `docs/model.md` states method, assumptions and limits | Met | Written |
| 5 | Every number labelled as Claude's estimate | Met | `analyst_estimate` on the view, each match and the tool output; command prints ANALYST ESTIMATE |

Found while building: the scoreline cap was raised from 10 to 20 goals because a team
expected to score 4.3 (Barcelona at Sabah) lost a measurable share of probability at 10.
The Dixon-Coles value -0.05 is an assumption, to be checked against results.

## Release 2 Phase A acceptance criteria (accepted 15 November 2026)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | All tests pass, output shown | Met | 225 passed; `ruff check` clean |
| 2 | Probe report shows each source working or not, with fields found | Met | `data/probe/report.md` (13 Nov): fixtures ok (144), odds ok (18), ClubElo failed (502), since dropped |
| 3 | Matchday 5 fixtures and kick-off times are in the repo and match the game | Met | 18 fixtures; first kick-off 24 Nov 19:45 Athens equals the deadline Patrick read from the game |
| 4 | A broken response leaves existing data untouched | Met | Tests, and two real ClubElo failures wrote no snapshot |
| 5 | No key appears in the repository or its history | Met | Checked after the real runs: saved odds URLs show `apiKey=REDACTED`; no token pattern in the tree |

Found by the real runs and fixed: bookmakers quote different goal lines, so odds records
keep every line and name the most quoted one (14 Nov: 3.5 goals, 10 of 19 bookmakers, for
Galatasaray v Aston Villa); six odds club names recorded as aliases, all 36 clubs match; the
workflow now rebases before pushing. The 13 November odds snapshot predates the line fix.

Known limit: GitHub started the first scheduled run about seven hours late (12:09 UTC for a
05:17 slot). Data is daily, not at a fixed hour.

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

## Release 2 Phase E (approved 24 November 2026): built, awaiting acceptance

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | All tests pass, lint clean | Met | 277 passed; `ruff check` clean |
| 2 | `uclfa outlook --from 6 --to 8` covers every club, odds-based and projected marked | Met | 36 clubs; `~` marks projections; `test_matches_without_odds_are_projected_and_marked` |
| 3 | `uclfa evaluate` answers the goalkeeper example per matchday and in total | Met | Donnarumma -> Becker over MD6-8: +0.0, too close to call, because Joan García covers MD6 |
| 4 | The Matchday 6 decision is made with it | Pending | Odds for MD6 expected about 1 December |

## Next

Matchday 5 between-days swaps (25 Nov), then the Matchday 6 decision with Phase E.

## Known limits of Phase 1

- Deadline clock times are not stored; only dates are known.
- Matchdays 2 and 3 have no deadline date in the rules file. Both are past.
- The `fixture` and `transfer` tables exist but nothing writes to them yet.
- The command line identifies players in a transfer file by exact name.
