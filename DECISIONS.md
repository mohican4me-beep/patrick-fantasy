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
| Package requires Python 3.12+ and was tested on 3.13 | The planning environment had 3.13 |
