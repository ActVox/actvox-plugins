# ActVox for Hermes

This plugin makes [Hermes Agent](https://github.com/NousResearch/hermes-agent) a member of
your team in an [ActVox](https://actvox.com) workspace. People assign Hermes tasks and
@mention it in comments. Hermes checks its inbox on a schedule, does each task, and submits
the result for review. It answers each mention in its thread. A person accepts every result:
in ActVox, a submitted task goes to review, never straight to done.

## What you get

| Where | What |
| --- | --- |
| Skills | `actvox:actvox` (work in the workspace) and `actvox:actvox-inbox` (the worker) |
| Session start | One line when tasks or mentions wait for Hermes |
| In a session | `/actvox inbox` lists what waits; `/actvox status` checks the connection |
| Terminal | `hermes actvox setup` (a checklist) and `hermes actvox install-gate` |
| Cron | The `actvox-inbox` job wakes Hermes only when its inbox has work |

## What you need

- Hermes 0.22.5 or later, with the gateway running (`hermes gateway install`). Cron runs
  only inside the gateway.
- An ActVox workspace where Hermes may take tasks.
- Node.js and the ActVox CLI (`npm i -g @actvox/cli`) on the same machine. The cron gate
  uses it to read the inbox.

## Install

```bash
hermes plugins install ActVox/actvox-plugins#hermes --ref <commit-sha> --enable
hermes actvox setup
```

`hermes actvox setup` checks each step and prints the next command. It changes nothing on
its own. The steps are:

1. Connect the hosted ActVox MCP server. Hermes reads and writes through it.

   ```bash
   hermes mcp add actvox --url https://api.actvox.com/mcp --auth oauth
   hermes mcp login actvox
   ```

   You approve the sign-in in your own browser. ActVox asks what to call Hermes there (a
   name and an @handle) and what access to give it.

2. Let this plugin use that server (Hermes gives plugins no MCP access by default):

   ```bash
   hermes config set plugins.entries.actvox.mcp_allowlist '["actvox"]'
   ```

3. Sign the ActVox CLI in, for the inbox gate. You approve this sign-in yourself too.

   ```bash
   actvox auth login --profile hermes
   ```

4. Write the gate script and create the worker job:

   ```bash
   hermes actvox install-gate
   hermes cron create "every 15m" "Work the ActVox inbox items that the script output above lists, with the actvox:actvox-inbox skill. If none needs you, reply exactly [SILENT]." --name actvox-inbox --skill actvox:actvox-inbox --script actvox-inbox-gate.py
   ```

5. In a Hermes session, run `/actvox status`. It shows each workspace, Hermes's @handle and
   its access.

Pick the interval you want. To stop the worker, run `hermes cron remove actvox-inbox`.

## How a tick works

1. The gateway runs `$HERMES_HOME/scripts/actvox-inbox-gate.py` before the job.
2. The script runs `actvox inbox --all --json --profile hermes` and compares the result with
   its last state (`$HERMES_HOME/plugin-data/actvox/gate-state.json`).
3. Nothing new: it prints `{"wakeAgent": false}`. Hermes skips the run. **An empty tick
   makes no model call.**
4. New work: it prints the ids of the tasks and mentions. Hermes runs the job with the
   `actvox:actvox-inbox` skill. The skill acknowledges, claims, works and submits each task,
   and answers and acknowledges each mention, through the MCP server.

An item that is still open after a run waits 15 minutes, then 1 hour, then 6 hours. After
the fourth try, Hermes asks a person in the item's thread and stops trying.

The gate wakes Hermes for a task when Hermes is its owner and the task is assigned,
acknowledged, sent back with changes requested, or claimed with an expired lease. It does
not wake Hermes to review or approve other work.

If the gate cannot read the inbox (the CLI is missing, signed out or offline), it wakes
Hermes once, so Hermes tells you the error and the fix. It stays quiet after that until a
tick succeeds. `hermes actvox setup` shows the last error.

## Settings

| Key | Default | Meaning |
| --- | --- | --- |
| `plugins.entries.actvox.settings.cli_profile` | `hermes` | The `actvox auth login --profile` the gate reads |
| `plugins.entries.actvox.settings.cli_path` | empty | Path to the `actvox` CLI; empty finds it on `PATH` |

Run `hermes actvox install-gate` again after you change either one.

## What this plugin does on your machine

- **Network:** it calls ActVox only through your own `actvox` MCP server (`ctx.call_mcp`)
  and through your own `actvox` CLI. It contacts no other service. It sends no telemetry.
- **Credentials:** it reads none. Hermes holds the MCP sign-in. The `actvox` CLI holds its
  own sign-in in your OS credential store.
- **Files:** `hermes actvox install-gate` writes one file,
  `$HERMES_HOME/scripts/actvox-inbox-gate.py`, and refuses to replace a file it did not
  write. The gate keeps its state in `$HERMES_HOME/plugin-data/actvox/`.
- **Background work:** none of its own. The `actvox-inbox` cron job runs only after you
  create it.
- **Shell:** the gate starts the `actvox` CLI. Setup runs `actvox auth status`.
- **Writes to ActVox:** only the cron worker and the skills, through the MCP server, with
  the access you granted at sign-in. The worker needs the server's default `trust: full`.
  With `trust: untrusted`, Hermes refuses unattended writes.

With `plugins.isolation: host`, Hermes does not add plugin terminal commands, so
`hermes actvox …` is not available. The skills, the session line and `/actvox` still work.

## Develop

```bash
uv run --no-project --with pytest python -m pytest tests -q
hermes plugins validate . --install-deps
```

## License

MIT
