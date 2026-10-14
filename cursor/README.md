# ActVox for Cursor

Connect Cursor to an [ActVox](https://actvox.com) workspace. The agent reads and updates shared pages, tables, comments, and tasks through the hosted MCP server at `https://api.actvox.com/mcp`.

The key is a workspace API key. Cursor sends it as the Bearer token. The hosted server accepts that header for clients that are not on the OAuth allowlist. Cursor is not on that allowlist, so this plugin does not start an OAuth sign-in.

## Install locally

Cursor staff document a local plugin directory at `~/.cursor/plugins/local` (forum, March 2026). From a clone of this repo:

```bash
mkdir -p ~/.cursor/plugins/local
ln -sfn "$PWD/cursor" ~/.cursor/plugins/local/actvox
```

Reload Cursor. Open **Customize**, install **actvox**, and set **ActVox API key** when asked.

Create the key in the workspace: **Connectors → API keys**. It must be bound to one workspace. A key that spans every workspace is refused. Copy it into the plugin setting only. Do not put it in chat, git, or this README.

Then run `/actvox`. A healthy connection reports the workspace and makes no writes.

## What the agent is told

`skills/actvox/SKILL.md` tells the agent to call `doctor` and `capabilities` first, then `get_guide` for the workspace-operator and HTML-artifact guides the deployment already serves. It does not vendor those guides, so the instructions stay the ones this deployment ships.

## Check

```bash
bun test cursor/plugin.test.ts
```
