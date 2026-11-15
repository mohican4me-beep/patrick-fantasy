# Decisions

Newest last. Each entry: the decision, who made it, and the reason.

## 13 November 2026: blueprint and addendum

| # | Decision | By | Reason |
|---|---|---|---|
| 1 | Fantasy data by shortlist entry only (route A). No feed file, no scripted fetch | Patrick | UEFA's terms prohibit automated collection and systematic compilation; no bulk route is clearly permitted |
| 2 | Release 1 split into 1a (matchday 5) and 1b (matchday 6) | Patrick | A dashboard cannot be ready for matchday 5 without cutting tests |
| 3 | Host is the Windows PC "beast": AMD Ryzen 5 5600X, 32 GB RAM | Patrick | Ample for the rules engine, and for the later solver and simulation |
| 4 | Phone access through Tailscale; nothing exposed publicly | Patrick | |
| 5 | Screenshot import uses local recognition first | Patrick | |
| 6 | Source probe approved, to run before Release 2 | Patrick | No API could be tested from the planning environment |
| 7 | Line-ups by manual entry only; ESPN endpoints not used | Patrick | Undocumented, terms unclear |
| 8 | Premier League public dataset excluded | Patrick | Licence not established |
| 9 | Claude as analyst accepted: tool results enter Claude conversations | Patrick | |
| 10 | Code in a private GitHub repository named "Patrick Fantasy" | Patrick | |
| 11 | Stack: Python, FastAPI later, SQLite, HiGHS later, React with Vite later | Claude, approved | Simplest free stack for a single user |
| 12 | Unverified rules block; they never get a default | Patrick (review) | A plausible default can produce a valid-looking wrong recommendation |
| 13 | Rival squads modelled from the previous matchday; ranges, not point probabilities | Patrick, Claude | Current rival squads are not visible |

## 13 November 2026: Phase 1 implementation choices

| Choice | Reason |
|---|---|
| Rule confirmations live in `rules/confirmations.yaml`, not the database | The rules engine stays free of storage, and confirmations are versioned in Git |
| Command line uses `argparse` | No extra dependency |
| Property-style tests use a seeded `random`, not Hypothesis | One fewer dependency; results are reproducible |
| Squad import reports an over-limit club as a note | A squad copied from the game can legitimately be over the limit after a real move; the limit is enforced on the next transfer |
| `Fixture` table created now, unused | Avoids a migration when Release 2 starts; holds nothing invented |
| Bench order follows the game: three outfield substitutes numbered 1 to 3, bench goalkeeper unnumbered | Seen in Patrick's squad screenshot; the first version wrongly numbered four |
| `UCLFA_CONFIRMATIONS` can point to another confirmations file | Tests must not depend on Patrick's real confirmations |
| Package requires Python 3.12+ and was tested on 3.13 | The planning environment had 3.13 |

## 13 November 2026: Release 1a, step 2

| Choice | Reason |
|---|---|
| MCP Python SDK 2.x (`mcp>=2.3,<3`), using `MCPServer` | The current release; version 1's `FastMCP` name no longer exists. Checked before writing code |
| Server opens SQLite with `mode=ro` and `query_only` | Read-only is enforced by the database, not by convention |
| SQLite write-ahead logging switched off | A read-only connection to a write-ahead-log database can need write access to the folder; a single user does not need it |
| Calculator outputs are always tagged `analyst_estimate` | Their inputs are estimates; no model exists yet |
| A tie is a "keep" in the captain calculator | The switch cannot be undone and gains nothing |
| Automatic-substitution cost is the sum of probability times replacement points | Simple and stated as an approximation; it ignores formation limits and shared bench cover |
| Tool server tests use explicit confirmations, not `rules/confirmations.yaml` | Tests must not change meaning when Patrick confirms another rule |
| `tzdata` added as a dependency | Windows ships no time-zone database, so `Europe/Athens` could not be resolved on the host; found by the first test run on beast |

## 13 November 2026: analyst route

| Decision | By | Reason |
|---|---|---|
| Claude acts as analyst from a chat with the repository attached (option A) | Patrick | Works now and from the phone; the desktop connector needed a config location that differs by app build |
| Squad states and the journal are files in the repository; `uclfa load` rebuilds the database | Claude, following A | A session's database does not persist, so the files are the record |
| Release 1a acceptance criterion 5 reworded to "Claude can list the squad and validate a transfer from a chat with the repository attached" | Patrick | Demonstrated on 13 November; the desktop connector is built and tested but not connected on the host |

## 13 November 2026: Release 1b deferred, Release 2 Phase A

| Decision | By | Reason |
|---|---|---|
| Release 1b (web dashboard, editor, screenshot screen, Tailscale) deferred | Patrick | The chat route already covers squad entry, validation and phone access |
| Next is Release 2, starting with data ingestion | Patrick | Predictions are the priority |
| Daily fetch runs on GitHub Actions (option 2) | Patrick | The chat environment cannot reach the sources; no machine has to stay on. This is the one approved exception to "no hosted service" |
| Keys are GitHub encrypted secrets, never in the repository | Claude | Standard practice; tests assert no key reaches disk |
| Snapshots are JSON files in the repository, one per source per day | Claude | Any Claude session gets them with `git pull`; history is kept by Git |
| Parsers tested on synthetic samples until the probe supplies real ones | Claude | No real response could be obtained from the build environment; stated in the tests and status |
| HTTP client refuses any uefa.com host | Claude | Makes decision 1 impossible to break by accident |

## 15 November 2026: ClubElo dropped

| Decision | By | Reason |
|---|---|---|
| ClubElo removed from the daily fetch | Patrick | HTTP 502 from GitHub on 13 and 14 November; odds cover the coming matchdays. Code is in Git history (commit 6c6c1ec and earlier) if it is wanted back |
| Workflow rebases on `main` before pushing snapshots | Claude | A re-run of an older run failed to push on 14 November |

## 15 November 2026: Release 2 Phase B, match model

| Decision | By | Reason |
|---|---|---|
| Phase B approved as planned | Patrick | |
| Margin removed with the power method | Claude | Standard; corrects the favourite-longshot bias |
| Only half-goal lines are used; the most quoted one per match | Claude | Quarter and whole lines refund stakes and would need extra assumptions |
| Poisson goals with a Dixon-Coles correction of -0.05 | Claude | Common, simple, explainable; the value is an assumption to check against results |
| Scoreline grid capped at 20 goals per team | Claude | At 10 a 4.3-goal favourite lost measurable probability |
| Modelling choices in `model/settings.yaml`, not code | Claude | Same principle as the rules file |
| Real-data tests use a pinned copy of the 15 November snapshots | Claude | Daily snapshots change; tests must not |

## 15 November 2026: Release 2 Phases C and D, player data

| Decision | By | Reason |
|---|---|---|
| Phases C (player expected points) and D (optimizer: transfers, hits, Wildcard) approved together | Patrick | He wants the app to name the best possible squad before the Matchday 5 deadline |
| Claude chooses the players and checks prices; Patrick no longer supplies names | Patrick | "The point is that you propose players" |
| Prices and player stats may come from public third-party sites, read by Claude in chat sessions, tagged `third_party` with source and date | Patrick ("do it as you wish") | UEFA's game has no public price page; scripted requests to it stay ruled out (decision 1). The in-game price at purchase is the truth |
| Player model is a formula, not a simulation | Claude | Explainable and testable; a simulation test checks it against the scoring engine |
