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

# Player expected points (Release 2 Phase C)

`uclfa points --matchday N` estimates each pool player's points for his match. Claude reads
the same view through the `player_points` tool. Every number is an `analyst_estimate`.

## Inputs

The pool is `data/players/pool.yaml`. For each player:

| Input | Meaning | Who sets it |
|---|---|---|
| price, price_tag | `entered` (Patrick read it in the game) or `third_party` (public fantasy site, dated) | Patrick or Claude |
| start_prob | Chance he starts | Claude, from predicted lineups |
| p60_if_start, minutes_if_start | Chance a start lasts 60 minutes; average minutes as a starter | Claude, from his recent matches |
| sub_prob, minutes_if_sub | Chance he comes on when not starting, and for how long | Claude |
| goal_share | His share of his team's goals over a full match (penalties included) | Claude, from season stats |
| assist_share | His assists per team goal over a full match | Claude, from season stats |
| recoveries_p90, saves_p90, cards_p90 | Per 90 minutes | Claude, from season stats |

Each player lists his sources. **A missing required input means no number**: the player is
shown as unavailable with the missing fields named. Prices are never guessed.

## Calculation

For a start and for a substitute appearance separately, then weighted by their chances:

- appearance point, and the 60-minute point times the chance of reaching 60;
- goals = team expected goals x goal share x minutes/90 x goal points for his position;
- assists likewise;
- clean sheet = points for his position x chance of reaching 60 x the team's 90-minute
  clean-sheet chance scaled down to the minutes he is on the pitch;
- goals conceded (goalkeepers and defenders) = -1 per two, from the opponent's expected
  goals while he is on;
- ball recoveries and saves = 1 point per three, with the rounding down counted exactly;
- yellow cards if a card rate is entered.

The point values come from `rules/2026-27.yaml`. A test simulates 40,000 matches per
position, scores each with the rules engine, and checks the formula gives the same average.

## Limits

- **Not modelled:** player of the match (3 points), goals from outside the box, penalties
  won, conceded, missed or saved, own goals and red cards. Stars are therefore slightly
  underestimated, since player of the match goes mostly to them.
- **Inputs are judgement.** A wrong starting chance moves the number more than anything
  in the formula. The command shows "points if he starts" beside the expected figure.
- **Shares are season averages** and do not adapt to the opponent.
- **No track record yet**, as for the match model.

# Choices over the coming matchdays (Release 2 Phase E)

Bookmakers price about one matchday ahead. To judge a choice over the matchdays that follow,
the app needs its own estimate of each team.

## Team ratings

Every club gets an attack rating and a defence rating, plus one home advantage. Expected
goals are `exp(base + home + attack[team] - defence[opponent])`. The ratings are fitted to:

- **odds:** every match a daily snapshot has priced, at the market-implied goal rates,
  weighted 3 times a played result;
- **results:** every finished league-phase match, each team's goals capped at 3 so one 9-1
  does not dominate;
- older matchdays count less (weight halves every 4 matchdays), and every rating is pulled
  towards average (shrinkage 2).

All of these are in `model/settings.yaml` (`ratings`).

**How good are the projections?** Fitted to Matchday 1-4 results only, they predicted the
Matchday 5 market's goal rates with an average miss of 31%, against 44% for treating every
team as equal (24 November 2026). Each new matchday of odds and results improves them.

## How numbers are marked

A matchday with odds uses them (`source: odds`). Without odds the match is projected from
the ratings (`source: projection`, shown with `~`). Team news has a matchday range: an
absence reported for one match counts there only; a long injury (Kane, out to MD10) counts
across it.

## Commands

| Command | What it answers |
|---|---|
| `uclfa outlook --from 6 --to 8 [--mine]` | Each club's fixture run: expected goals for and against, clean-sheet chance |
| `uclfa player-outlook NAME ... [--mine] --from 6 --to 8` | Players' expected points per matchday and in total |
| `uclfa evaluate --out A --in B --matchday 6 [--to 8]` | Does this move make sense over the stretch? Rules check, hit, bank, gain per matchday, verdict |
| `uclfa optimize --matchday 6 --to 8` | Suggested transfers at matchday 6, judged over 6-8 |

The stretch defaults to the last matchday before the next one with unlimited transfers.
The same views are read-only tools for Claude: `team_outlook`, `player_outlook`,
`evaluate_move`.

**How a move is judged.** For each matchday, the squad's best lineup and captain are found
with and without the move; the gain is the difference, summed over the stretch, minus any
hit. A move within 2 points (`verdict_margin`) is "too close to call". Because the lineup is
re-picked every matchday, a player who would sit on the bench adds nothing, and two
goalkeepers who cover each other's hard fixtures are valued as such.

## Limits

- Projections weeks ahead ignore injuries, form and rotation not yet known.
- The stretch optimizer plans transfers at the first matchday only, then holds them.
- The between-days option (swapping in Wednesday players after Tuesday) is not valued;
  it favours squads with players on both days.
