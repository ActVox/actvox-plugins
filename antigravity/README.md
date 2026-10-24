# ActVox for Antigravity

Connect Google Antigravity (the app and the `agy` CLI) to an [ActVox](https://actvox.com) workspace. The plugin adds the hosted MCP server `https://api.actvox.com/mcp` and the `actvox` skill.

The plugin holds no key. Antigravity signs in with OAuth. ActVox identifies Antigravity by its client metadata document, `https://antigravity.google/oauth/client-metadata.json`, and accepts only its hosted callback, `https://antigravity.google/oauth-callback`.

## Install

```bash
git clone https://github.com/ActVox/actvox-plugins.git
agy plugin install "$PWD/actvox-plugins/antigravity"
```

Then sign in:

1. Open Agent settings (Cmd+,) → **Customizations**.
2. Click **Authenticate** next to `actvox`.
3. Approve the workspace and the access on the ActVox page.
4. Copy the authorization code that the browser shows. Paste it in Antigravity. Click **Submit**.

`agy plugin list` shows the plugin with 1 skill and 1 MCP server. In the CLI, `/mcp` opens the MCP Manager. Then ask Antigravity to call `doctor` on ActVox. A healthy connection reports the workspace and makes no writes.

Without the plugin, add only the server: `agy mcp add actvox https://api.actvox.com/mcp`.

## Update and remove

Pull the repository, then run the install command again. Remove with `agy plugin uninstall actvox`.

## What the agent is told

`skills/actvox/SKILL.md` tells the agent to call `doctor` and `capabilities` first, then `get_guide` for the workspace-operator and HTML-artifact guides that the server provides. It does not copy those guides, so the instructions stay current.

## Check

```bash
agy plugin validate antigravity --strict
```
