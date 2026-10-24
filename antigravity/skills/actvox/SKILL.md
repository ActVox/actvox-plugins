---
name: actvox
description: Use when the user wants Antigravity to read or update an ActVox workspace — pages, databases, comments, files, or assigned tasks. Uses the actvox MCP server. Inspects first and writes only when the user asked for that change.
---

# ActVox

ActVox is the shared workspace. This Antigravity session reaches it through the `actvox` MCP server at `https://api.actvox.com/mcp`.

## Sign in

The server uses OAuth. The user signs in once: Agent settings → **Customizations** → **Authenticate** next to `actvox`, then approves the workspace on the ActVox page.

Never ask the user for a password, token, or API key in chat. If an `actvox` tool answers that authorization is required, tell the user to authenticate the `actvox` server, then stop.

Do not use the ActVox CLI or a Python client from this plugin. Those are a different transport. If the MCP server is not connected, say so and stop.

## Start

1. Call `doctor`. If it errors, stop and tell the user the ActVox connection is not ready. Do not invent a workspace id.
2. Call `capabilities`. Use only tools the result marks as allowed.
3. For how to organize pages, databases, whiteboards, and tasks, call `get_guide` with `skill` `actvox-workspace-operator` and `path` `SKILL.md`. Follow that guide. When it names another file, call `get_guide` again with that path. For an interactive HTML page, call `get_guide` with `skill` `actvox-html-artifact`.

`doctor` reports standing pages in `standingPages`. `instructions` is ACTVOX.md and `design` is DESIGN.md. `null` means that page does not exist. Read an existing one with `get_instructions` or `get_design`. Do not create either page just to look around.

## Writes

A read-only request makes no remote writes. That includes pages, comments, memory, imports, and standing documents.

When the user asked for a specific change, do that change. When they asked to explore or to see options, propose the object and the edit, then wait.

- Create with a new `operation_id`. Retry the same payload with the same id. A different task gets a new id.
- On a conflict, re-read and plan again. Do not overwrite.
- After a write, read the object back. Tell the user what changed, the workspace URL, and one next action on that object.

Archive, share, and publish only when the user asked for that action and `capabilities` allows it.

## Looking around

`get_workspace_tree` lists the workspace. Follow its cursor until the tree is complete, or say the inventory is partial. `search_workspace` finds a known title. Neither call is a reason to create objects.
