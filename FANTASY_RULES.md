# Fantasy rules as implemented, 2026/27

Source: UEFA's official rules page, read on 13 November 2026:
https://www.uefa.com/uefachampionsleague/news/025f-0fd4b42cc0a7-74498b7df63b-1000--uefa-champions-league-fantasy-football-rules-2026-27/

The machine-readable version is `rules/2026-27.yaml`. Run `uclfa rules status` for the live
register, including anything you have confirmed.

## Confirmed

| Rule id | Rule |
|---|---|
| `squad_composition` | 15 players: 2 GK, 5 DEF, 5 MID, 3 FWD |
| `lineup_formation` | 11 starters: exactly 1 GK, at least 3 DEF, 2 MID, 1 FWD |
| `budget_by_stage` | EUR 100m; EUR 105m after the league phase |
| `club_limit_by_stage` | 3 per club in the league phase; 4 play-offs and round of 16; 5 quarter-finals; 6 semi-finals; 8 final |
| `club_limit_inherited` | A squad pushed over the limit by a real move must be fixed at the next transfer |
| `free_transfers_table` | Unlimited before MD1, MD9, MD11; 2 per league matchday and MD10; 3 before MD12, MD14, MD16; 5 before MD13, MD15, MD17 |
| `transfer_hit` | 4 points per transfer beyond the free allowance |
| `transfer_carry` | One unused transfer carries in the league phase only; none after a chip or in the knockouts |
| `chips` | Wildcard and Limitless, once each, not on MD1, MD9, MD11 |
| `captain_double` | Captain's points doubled; captain must start |
| `captain_switch` | Between playing days, to a starter yet to play; cannot move back |
| `manual_substitutions` | Up to 4 per break; incoming player's team still to play; removed player scores 0; sent-off players cannot be removed |
| `automatic_substitutions` | Only if no manual change of any kind was made. Outfield bench players are numbered 1 to 3; the bench goalkeeper is unnumbered |
| `mid_matchday_changes_excluded` | None on MD8 or in the final |
| `scoring_table` | See below |
| `clean_sheet_on_pitch` | 60 minutes excluding added time and no goal conceded while on the pitch |
| `red_card_rules` | Minus 3; yellow then red is the red only; goals conceded keep counting |
| `extra_time` | Counts; no doubled appearance or clean sheet; shoot-outs score nothing |
| `goalkeeper_ball_recoveries` | Balls recovered are listed for all players |

## Partly confirmed

| Rule id | What is known | What is not |
|---|---|---|
| `substitution_limit_reset` | 4 per break | Whether it resets at a second break. No remaining matchday has two breaks |
| `chip_restoration` | The squad returns after Limitless | Bank and price effects. Re-confirm squad and bank from the game afterwards |
| `deadline_times` | Deadline is the matchday's first kick-off; dates are published | Clock times. `deadline_utc` stays empty until checked |
| `goals_conceded_on_pitch` | Implied by the sent-off wording | Not stated outright. Affects scoring inputs, not legality |

## Confirmed by Patrick in the game, 13 November 2026

UEFA's page does not state these. They are recorded in `rules/confirmations.yaml`.

| Rule id | Confirmed value | Meaning |
|---|---|---|
| `selling_value` | `current_price` | A sale returns the player's current price |
| `goalkeeper_manual_substitution` | `allowed` | The goalkeeper can be swapped once the day's matches are over |
| `captain_on_substituted_in` | `allowed` | The armband can go to a player just brought on |
| `late_changes_after_kickoff` | `not_allowed` | Changes lock when the next playing day's first match starts |

## Unverified: this blocks until confirmed

| Rule id | Blocks | Confirm with |
|---|---|---|
| `two_chips_same_matchday` | A second chip on a matchday with one active | `uclfa rules confirm two_chips_same_matchday --value allowed` or `not_allowed` |

## Observations from the game

- A goalkeeper's points breakdown shows saves and no balls-recovered line (Patrick,
  13 November 2026). The official table lists recoveries for all players, so the scoring
  function still accepts them; in practice goalkeepers appear not to be credited with any.
- The game shows appearance and 60 minutes as one line, for example "70 minutes played,
  2 pts".
- The bench is one goalkeeper, unnumbered, and three outfield players numbered 1 to 3.
- Matchday 5 transfer deadline: 24 November, 19:45 Europe/Athens (17:45 UTC).

## Scoring

| Event | GK | DEF | MID | FWD |
|---|---|---|---|---|
| Appearance | 1 | 1 | 1 | 1 |
| 60 minutes | 1 | 1 | 1 | 1 |
| Goal | 6 | 6 | 5 | 4 |
| Goal from outside the box | +1 | +1 | +1 | +1 |
| Assist | 3 | 3 | 3 | 3 |
| Clean sheet | 4 | 4 | 1 | 0 |
| Every 3 balls recovered | 1 | 1 | 1 | 1 |
| Every 3 saves | 1 | | | |
| Penalty save | 5 | | | |
| Every 2 goals conceded | -1 | -1 | | |
| Player of the Match | 3 | 3 | 3 | 3 |
| Penalty won (not for handball) | 2 | 2 | 2 | 2 |
| Penalty conceded | -1 | -1 | -1 | -1 |
| Penalty missed | -2 | -2 | -2 | -2 |
| Yellow card | -1 | -1 | -1 | -1 |
| Red card | -3 | -3 | -3 | -3 |
| Own goal | -2 | -2 | -2 | -2 |

## Checks to make in the game

- [x] Sale value: the current price.
- [x] Goalkeeper breakdown: saves shown, no balls recovered.
- [x] Goalkeeper swap between playing days: allowed.
- [x] Armband to a player just brought on: allowed.
- [x] Matchday 5 deadline: 19:45 Europe/Athens.
- [x] Changes after the first kick-off of day two: not accepted.
- [ ] Whether Wildcard and Limitless can be played on the same matchday.
