# Data sources and the daily fetch

Three documented sources are fetched once a day by a GitHub workflow and committed to
`data/snapshots/`. No UEFA address is ever contacted; the HTTP client refuses UEFA hosts.

| Source | Provides | Key needed | Snapshot folder |
|---|---|---|---|
| football-data.org | Champions League fixtures, kick-off times, results | Yes | `data/snapshots/fixtures/` |
| ClubElo | Daily club strength ratings | No | `data/snapshots/elo/` |
| The Odds API | Match-result and over/under 2.5 odds, median across bookmakers | Yes | `data/snapshots/odds/` |

Status on 13 November 2026: football-data.org and The Odds API returned real data through
the workflow and their parsers are tested against those responses. ClubElo answered HTTP 502
and is untested against a real response.

## One-time setup (about ten minutes)

1. Create a free account at football-data.org and copy the API token it emails you.
2. Create a free account at the-odds-api.com and copy the API key.
3. On GitHub, open the `patrick-fantasy` repository, then Settings, then Secrets and
   variables, then Actions, then "New repository secret". Add two secrets:
   - name `FOOTBALL_DATA_TOKEN`, value: the football-data.org token
   - name `ODDS_API_KEY`, value: The Odds API key
4. Open the Actions tab, choose "Fetch data", click "Run workflow", tick the probe box and
   run it.
5. When it finishes, tell Claude. The report is at `data/probe/report.md`.

Never paste a key into a chat, a file or a commit. If one leaks, revoke it on the
provider's site and create a new one.

## What runs daily

`uclfa fetch` at 05:17 UTC. Each source writes `data/snapshots/<source>/<date>.json` with
its fetch time and the request address (keys redacted). A response that is malformed or
has too few records is rejected and writes nothing, so the previous snapshot stays
current, and the workflow run is marked failed so you get GitHub's failure email.

Quota: The Odds API costs about 2 credits per run, roughly 60 of the 500 free credits a
month. football-data.org allows 10 calls a minute; the fetch makes one.

## Commands

| Command | What it does |
|---|---|
| `uclfa fetch` | Fetch all sources (or `--source fixtures`) into `data/snapshots/` |
| `uclfa probe` | Fetch once and write `data/probe/report.md` with fields found and missing |
| `uclfa fixtures --matchday 5` | List fixtures in Athens time and compare the first kick-off with the recorded deadline |
| `uclfa clubs` | Report club names that do not match across the three sources |

The same commands work on the host PC as a fallback: set the two keys as environment
variables, run `uclfa fetch`, then commit and push `data/snapshots`.

## Club names

The three sources spell clubs differently. `uclfa clubs` lists names it cannot match.
Add each to `data/club_aliases.yaml` only after seeing it reported; no match is guessed.
