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
| `automatic_substitutions` | Only if no manual change of any kind was made |
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

## Unverified: these block until you confirm them

| Rule id | Blocks | Confirm with |
|---|---|---|
| `selling_value` | Any transfer out of a player with no sale value entered | `uclfa rules confirm selling_value --value current_price` or `purchase_price` |
| `goalkeeper_manual_substitution` | Substituting the goalkeeper between playing days | `--value allowed` or `not_allowed` |
| `captain_on_substituted_in` | Captaincy for a player brought on in the same break | `--value allowed` or `not_allowed` |
| `late_changes_after_kickoff` | Changes after the next playing day has kicked off | `--value allowed` or `not_allowed` |
| `two_chips_same_matchday` | A second chip on a matchday with one active | `--value allowed` or `not_allowed` |

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

- [ ] Sale value shown for a player whose price has changed since you bought him.
- [ ] Whether any goalkeeper's breakdown shows balls-recovered points.
- [ ] Whether the goalkeeper can be swapped between playing days.
- [ ] Whether the armband can go to a player you have just brought on.
- [ ] The matchday 5 deadline time and its time zone.
- [ ] Whether changes are accepted after the first kick-off of day two.
