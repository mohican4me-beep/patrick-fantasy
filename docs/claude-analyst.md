# Using Claude as your Fantasy analyst

Chosen route (decision of 13 November 2026): a Claude chat with this repository attached.
Claude runs the rules engine and calculators itself. It works from the desktop app and
from your phone, needs no connector, and uses your subscription, not the API.

## Starting a session

Open a Claude chat that has `mohican4me-beep/patrick-fantasy` attached and say what you
need, for example "check this transfer" or "day one is finished, here are my points".
Claude's first step in a new session is:

```
pip install -e ".[dev]"
uclfa load
```

`uclfa load` rebuilds the database from `squads/` and `journal/`, because a session's
database does not persist.

## Where your data lives

| Data | File | How it changes |
|---|---|---|
| Squad states | `squads/mdNN-S-label.yaml`, one per state | You send a screenshot or the changes; Claude writes the next file and commits it |
| Decisions | `journal/journal.yaml` | Claude appends an entry and commits it |
| Rules you confirmed | `rules/confirmations.yaml` | `uclfa rules confirm ...`, then commit |

Squad files are imported in file-name order and the last one is the current state. Name
them by matchday and step: `md05-1-pre-deadline.yaml`, `md05-2-after-day-1.yaml`,
`md06-1-pre-deadline.yaml`.

The repository is private. Whatever Claude reads in a session is sent to Anthropic as
part of that conversation.

## What to send Claude

- **Before a deadline:** any transfers you are weighing, with the incoming player's club,
  position and current price from the game.
- **After a playing day:** each of your players' points so far, and which teams have
  played. A screenshot of the points screen is enough.
- **After the matchday:** total points, overall rank and mini-league rank, and the new
  squad screen if you made changes.

## What Claude will and will not do

- It validates every proposed transfer, substitution and captain change with the rules
  engine before presenting it.
- It labels every expected-points figure as its own estimate. There is no prediction
  model in this release.
- It records each decision, the estimate behind it and later the outcome.
- It never changes your UEFA team. You make every change in the UEFA app.
- It does not fetch anything from UEFA.

## The other routes

The read-only tool server (`uclfa mcp`) is built and tested, and stays available. Setup
for the desktop app and Claude Code is in `docs/claude-setup.md`. On this PC the desktop
app reads its config from
`%LOCALAPPDATA%\Claude-Data\claude_pzs8sxrjxfjjc\claude_desktop_config.json`, not from
either location the public documentation gives. That connection was not completed.
