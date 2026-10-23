# ActVox plugins

Public plugins for connecting coding agents to an [ActVox](https://actvox.com) workspace.

| Directory | Host | Status |
| --- | --- | --- |
| [`cursor/`](cursor/) | Cursor | Ready to install locally. Marketplace submission is a separate step. |
| [`hermes/`](hermes/) | Hermes Agent | Inbox autopilot: Hermes works its ActVox tasks and @mentions on a schedule. Install with `hermes plugins install ActVox/actvox-plugins#hermes --ref <commit-sha>`. |
| `claude/` | Claude Code | Not in this repo yet. Add it as its own plugin with `.claude-plugin/plugin.json` and `.mcp.json`. Claude's directory connector uses OAuth, so it must not reuse the Cursor API-key header. |

The hosted MCP server is `https://api.actvox.com/mcp`.

## Cursor marketplace

Submit [cursor.com/marketplace/publish](https://cursor.com/marketplace/publish) with this repository:

`https://github.com/ActVox/actvox-plugins`

| Field | Value |
| --- | --- |
| Organization name | `ActVox` |
| Organization handle | `actvox` |
| Contact email | `support@actvox.com` |
| Website URL | `https://actvox.com` |
| Logotype URL | `https://raw.githubusercontent.com/ActVox/actvox-plugins/main/cursor/assets/logo.png` |
| GitHub repository | `https://github.com/ActVox/actvox-plugins` |
| Description | Connect Cursor to an ActVox workspace. Read and update shared pages, tables, comments, and tasks with the permissions on your workspace API key. |

**Submit Application** accepts the Publisher Terms. This repo being public does not submit the form.
