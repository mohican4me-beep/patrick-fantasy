# Patrick Fantasy

A personal assistant for UEFA Champions League Fantasy. This is Release 1a: a
verified rules engine, a squad record, decision calculators, a command line and a read-only
tool server for Claude. There is no prediction model, no optimizer and no web app yet.

The app never contacts UEFA and stores no UEFA credentials. Everything it knows about the
game is entered by you.

## Setup on Windows

Requires Python 3.12 or newer and Git.

```powershell
git clone https://github.com/mohican4me-beep/patrick-fantasy.git
cd patrick-fantasy
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\uclfa init-db
```

Run commands from inside the `patrick-fantasy` folder. They are written as `uclfa ...`
below; without activating the environment, type `.venv\Scripts\uclfa ...`.

The database is created at `data\uclfa.db` and is not committed to Git.

## Commands

| Command | What it does |
|---|---|
| `uclfa rules status` | Lists every rule and whether it is confirmed, partly confirmed or unverified |
| `uclfa rules confirm RULE --value VALUE` | Records a rule you checked in the game |
| `uclfa player add --name ... --club ... --position MID --price 6.5` | Adds a player to the shortlist |
| `uclfa shortlist` | Shows the shortlist with latest price and ownership |
| `uclfa squad import docs\squad-template.yaml` | Validates and saves your squad |
| `uclfa squad show` / `uclfa squad validate` | Shows or re-checks the saved squad |
| `uclfa transfers check docs\transfers-template.yaml` | Checks transfers: legality, cost, bank, next free transfers |
| `uclfa score --position DEF --minutes 90 --recoveries 7` | Scores one match with the official table |
| `uclfa decide captain --points 7 --candidate "Name=6.4" --author Patrick` | Value of moving the armband between playing days |
| `uclfa decide sub --swap "Out\|7\|In\|6.4" --author Patrick` | Value of a manual substitution; add `\|to-play` if the outgoing player has not played |
| `uclfa mcp` | Runs the read-only tool server for Claude (see `docs/claude-setup.md`) |
| `uclfa journal add ...` / `uclfa journal list` | Records and lists decisions |

## Entering your squad

Copy `docs/squad-template.yaml`, replace the fifteen players with yours, and run
`uclfa squad import yourfile.yaml`. Enter `sale_value` for each player from the game's
transfer screen if you can: until the selling-value rule is confirmed, a transfer out of
a player with no sale value is blocked, not guessed.

## Results

Every check returns one of three results:

- **VALID**: no rule is broken.
- **INVALID**: a rule is broken; the rule and the reason are named.
- **BLOCKED**: the action depends on a rule UEFA's page does not settle. Check it in the
  game and record it with `uclfa rules confirm`.

## Documents

- `FANTASY_RULES.md`: the rules as implemented, with their verification status.
- `ARCHITECTURE.md`: how the code is organised.
- `DECISIONS.md`: decisions taken and why.
- `PROJECT_STATUS.md`: what is done and what is open.
- `CLAUDE.md`: working rules for Claude Code in this repository.
