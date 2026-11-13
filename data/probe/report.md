# Source probe report

Run at 2026-11-13T12:31:35+00:00.

| Source | Result | HTTP | Records | Quota |
|---|---|---|---|---|
| football-data.org (Champions League fixtures and results) | ok | 200 | 144 | x-requests-available-minute=9, x-requestcounter-reset=60 |
| ClubElo (daily club ratings) | failed | - | 0 | - |
| The Odds API (Champions League match odds) | ok | 200 | 18 | x-requests-remaining=498, x-requests-used=2, x-requests-last=2 |

## football-data.org (Champions League fixtures and results)

- Result: **ok**. 144 records saved to data/snapshots/fixtures/2026-11-13.json.
- Fields returned: area, awayTeam, competition, group, homeTeam, id, lastUpdated, matchday, odds, referees, score, season, stage, status, utcDate
- Expected fields missing: none
- Raw sample: `data/probe/fixtures-sample.json`

## ClubElo (daily club ratings)

- Result: **failed**. HTTP 502 from api.clubelo.com: 
- Expected fields missing: none

## The Odds API (Champions League match odds)

- Result: **ok**. 18 records saved to data/snapshots/odds/2026-11-13.json.
- Fields returned: away_team, bookmakers, commence_time, home_team, id, sport_key, sport_title
- Expected fields missing: none
- Raw sample: `data/probe/odds-sample.json`
