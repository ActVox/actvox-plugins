---
name: actvox
description: Use when the person wants Hermes to read or update an ActVox workspace — pages, databases, comments, files or assigned tasks. Uses the actvox MCP server. Inspects first and writes only the change the person asked for.
---

# ActVox

ActVox is the team's shared workspace. Hermes reaches it through the `actvox` MCP server at
`https://api.actvox.com/mcp`. Hermes names its tools `mcp__actvox__<tool>`. When Tool Search
is on, search for `actvox` plus the action, for example `actvox check inbox`.

Hermes holds the sign-in (OAuth). Never ask the person for a password, code, key or token.
Never print one.

For workspace reads and writes, use the MCP server only. The `actvox` CLI on this machine is
for the inbox gate. Do not use it for writes.

## Start

1. Call `doctor`. If it fails, tell the person the ActVox connection is not ready and stop.
   The person can run `/actvox status` to see the fix. Do not invent a workspace id.
2. Call `capabilities`. Use only the tools it allows.
3. For how to organize pages, databases, whiteboards and tasks, call `get_guide` with skill
   `actvox-workspace-operator` and path `SKILL.md`. Follow that guide. When it names another
   file, call `get_guide` again with that path. For an interactive HTML page, call
   `get_guide` with skill `actvox-html-artifact`.

`doctor` lists standing pages in `standingPages`: `instructions` is ACTVOX.md and `design` is
DESIGN.md. Read an existing one with `get_instructions` or `get_design` before you write in
that workspace. Do not create either page only to look around.

## Writes

A read-only request makes no remote writes: no pages, comments, memory or imports.

When the person asks for a specific change, make that change. When they ask to explore or
to see options, propose the object and the edit, then wait.

- Give each create a new `operation_id`. Retry the same payload with the same id.
- On a conflict, read the object again and plan again. Do not overwrite.
- After a write, read the object back. Tell the person what changed, the workspace URL, and
  one next action on that object.

Archive, share and publish only when the person asks for that action and `capabilities`
allows it.

## Tasks and mentions

For assigned tasks and @mentions, load the skill `actvox:actvox-inbox` and follow it.
