---
name: actvox
description: Check the ActVox connection and summarize what this workspace already contains
---

# ActVox status

1. Call the `actvox` MCP tools `doctor` and `capabilities`.
2. If the connection is healthy, call `get_workspace_tree` and follow its cursor until the list is complete or you must report it as partial.
3. Reply with the workspace, what this key can read or write, whether ACTVOX.md and DESIGN.md already exist (`standingPages`), and the top-level objects you found.

Make no writes.
