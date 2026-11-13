# Connecting Claude to Patrick Fantasy on the host PC

The tool server lets Claude Desktop or Claude Code read your squad and run the validators
and calculators. It is read-only, opens no network port, and needs no API key. Whatever a
tool returns becomes part of your Claude conversation, so it is sent to Anthropic.

These steps were written from the SDK and Claude documentation. They have not been run on
"beast" yet; the last section is the check that confirms they work.

## Before you start

In PowerShell, from the repository folder:

```powershell
.venv\Scripts\activate
pip install -e ".[dev]"
uclfa init-db
uclfa squad import squads\md5.yaml
pytest
```

Note the full path of the program the server runs with:

```powershell
(Get-Command uclfa).Source
```

It will look like `C:\Users\<you>\patrick-fantasy\.venv\Scripts\uclfa.exe`.

## Claude Code

```powershell
claude mcp add patrick-fantasy -- "C:\Users\<you>\patrick-fantasy\.venv\Scripts\uclfa.exe" mcp
claude mcp list
```

## Claude Desktop

Open Settings, then Developer, then Edit Config. This opens `claude_desktop_config.json`
(usually in `%APPDATA%\Claude`). Add the server, keeping any entries already there:

```json
{
  "mcpServers": {
    "patrick-fantasy": {
      "command": "C:\\Users\\<you>\\patrick-fantasy\\.venv\\Scripts\\uclfa.exe",
      "args": ["mcp"]
    }
  }
}
```

Quit Claude Desktop fully and start it again.

## The check (acceptance criterion 5)

Ask Claude:

1. "Use patrick-fantasy to show my squad." It should list eleven starters, four bench
   players and Raphinha as captain.
2. "Validate transferring Gadou out for a 4.5m Lille defender." It should report valid,
   0 points deducted and a bank of 0.3m.

If Claude does not see the tools, run `uclfa mcp` in PowerShell. It should start and wait
silently; press Ctrl+C to stop. An error there is the thing to send me.

## What Claude can and cannot do

- It can read your squad, bank, shortlist, journal and the rules, and run validations and
  the captain and substitution calculators.
- It cannot change your data or your UEFA team. You make every change in the UEFA app.
- It has no projections. Any expected-points figure it gives is its own estimate.
- The iPhone app cannot reach this server; that needs a public endpoint, which this
  project does not create.
