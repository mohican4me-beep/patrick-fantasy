# Match model (Release 2 Phase B)

`uclfa outlook --matchday N` gives, for every match of a matchday that bookmakers have
priced, each team's expected goals, its chance of keeping a clean sheet, its chance of
scoring, and the most likely scorelines. Claude reads the same view through the
`match_outlook` tool.

**Everything here is an estimate** (`analyst_estimate`), made by a method Claude chose
and Patrick approved. It is not UEFA data and not a promise.

## How it works

1. **Odds in.** The daily fetch stores, for each match, the median price across
   bookmakers for home win, draw and away win, and for over/under at every goal line
   quoted.
2. **Margin out.** Bookmaker prices add up to more than 100%; the extra is their margin.
   It is removed with the *power method*: each implied probability (1 / price) is raised
   to the same power, chosen so they add up to exactly 100%. This takes more off
   outsiders than off favourites, matching the known tendency of bookmakers to
   overprice outsiders.
3. **Goals line.** The model uses the half-goal line (2.5, 3.5, 4.5 and so on) that most
   bookmakers quote. Quarter and whole lines (3.25, 3.0) partly refund stakes and would
   need extra assumptions, so they are not used. If no half-goal line exists, the match
   is fitted from the result odds alone and marked low confidence.
4. **Fit.** Each team gets one goal rate. Goals are assumed to follow a Poisson
   distribution, with the Dixon-Coles correction that makes 0-0 and 1-1 slightly more
   likely. The two rates are chosen so the model's home/draw/away and over/under
   probabilities match the market's as closely as possible (least squares).
5. **Read off.** From the resulting scoreline grid: expected goals, clean sheet (the
   opponent scores 0), scoring at least once, and the three most likely scores.

## Settings

The modelling choices live in `model/settings.yaml`, never in code:

| Setting | Value | Meaning |
|---|---|---|
| margin_method | power | How the margin is removed |
| low_score_correction | -0.05 | Dixon-Coles correction; Claude's assumption, not fitted to data; 0 switches it off |
| max_goals | 20 | Scoreline grid size per team |
| fit_tolerance | 0.01 | The fit must match each market probability within 1 point |
| min_result_bookmakers | 5 | Fewer bookmakers on the result means low confidence |
| min_goals_bookmakers | 3 | Fewer bookmakers on the goals line means low confidence |

## When a match is marked low confidence

- The model misses a market probability by more than 1 percentage point. This happens
  most in evenly matched games, where the market expects more draws than a Poisson
  model gives.
- The goals line or the result is quoted by too few bookmakers.
- No half-goal line exists.
- A goal rate hit its search bound (0.05 or 6.0).
- The odds and the fixture disagree on the kick-off time.

## When a match is unavailable

No number is produced, and the reason is shown, when:
- no odds are listed for it (bookmakers usually list one matchday ahead);
- the odds name the teams the other way round from the fixture;
- the odds are unusable (for example a price of 1.0);
- the match has already been played.

Odds whose club names do not resolve to a fixture are listed separately, never matched
by guesswork. Club spellings are mapped in `data/club_aliases.yaml`.

## Limits

- **Team level only.** A clean-sheet chance belongs to the team. A defender earns the
  points only if he plays 60 minutes and his team concedes none while he is on, so
  player numbers need minutes, which come in Phase C.
- **Poisson is a simplification.** It assumes goals arrive independently at a steady
  rate. It slightly misjudges draws and very lopsided games; the correction reduces
  this but does not remove it.
- **Odds move.** The outlook uses the latest daily snapshot and shows its age. Team news
  after the snapshot is not in it.
- **No track record yet.** Odds for past matchdays were never captured, so the method
  could not be tested on history. From Matchday 5, predictions are compared with
  results and recorded in the journal. 18 matches are too few to prove accuracy; the
  record builds over the season.
