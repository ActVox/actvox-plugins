"""`hermes actvox setup` (a checklist) and `hermes actvox install-gate` (the cron shim).

Setup changes nothing in Hermes config: it checks what it can from a terminal and prints the
next command. The MCP sign-in and the allowlist are checked in a session with
`/actvox status`, because a plugin CLI command has no MCP connection.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

GATE_SCRIPT_NAME = "actvox-inbox-gate.py"
SHIM_MARKER = "# actvox-hermes-plugin gate shim v1"
CRON_JOB_NAME = "actvox-inbox"
WORKER_SKILL = "actvox:actvox-inbox"
WORKER_PROMPT = (
    "Work the ActVox inbox items that the script output above lists, with the actvox:actvox-inbox "
    "skill. If none needs you, reply exactly [SILENT]."
)
CLI_TIMEOUT_SECONDS = 20

SHIM_TEMPLATE = '''#!/usr/bin/env python3
{marker}. Written by `hermes actvox install-gate`.
# It runs the ActVox inbox gate from the installed plugin before the {job} cron job.
# Delete this file, or remove the job, to stop it.
import json
import sys

PLUGIN_DIR = {plugin_dir!r}
try:
    sys.path.insert(0, PLUGIN_DIR)
    import actvox_gate
except Exception as exc:  # the plugin was removed or moved: stay silent, never wake the model
    print(f"actvox gate: plugin not found at {{PLUGIN_DIR}}: {{exc}}", file=sys.stderr)
    print(json.dumps({{"wakeAgent": False}}))
    sys.exit(0)
sys.exit(actvox_gate.main(["--cli", {cli!r}, "--profile", {profile!r}, "--state", {state!r}]))
'''


@dataclass
class Check:
    key: str
    ok: Optional[bool]  # None: nothing to judge yet
    label: str
    fix: str = ""


def render_shim(*, plugin_dir: Path, cli: str, profile: str, state: Path) -> str:
    return SHIM_TEMPLATE.format(marker=SHIM_MARKER, job=CRON_JOB_NAME, plugin_dir=str(plugin_dir),
                                cli=cli, profile=profile, state=str(state))


def install_gate(scripts_dir: Path, *, plugin_dir: Path, cli: str, profile: str, state: Path) -> Path:
    """Write the shim; refuse to replace a file this plugin did not write."""
    target = Path(scripts_dir) / GATE_SCRIPT_NAME
    if target.exists() and SHIM_MARKER not in target.read_text(encoding="utf-8", errors="replace"):
        raise FileExistsError(f"{target} exists and was not written by this plugin; move it away first")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".actvox-gate.", suffix=".py")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(render_shim(plugin_dir=plugin_dir, cli=cli, profile=profile, state=state))
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def _auth_status(cli: str, profile: str, run: Callable[..., Any]) -> Optional[dict[str, Any]]:
    cmd = [cli, "auth", "status", "--json"] + (["--profile", profile] if profile else [])
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS, check=False)
        payload = json.loads(proc.stdout or "")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else None


def checklist(*, cli: str, profile: str, scripts_dir: Path, state_path: Path,
              run: Callable[..., Any] = subprocess.run) -> list[Check]:
    login_fix = f"actvox auth login --profile {profile}" if profile else "actvox auth login"
    checks: list[Check] = []
    has_cli = bool(cli) and Path(cli).exists()
    checks.append(Check("cli", has_cli, f"ActVox CLI: {cli}" if has_cli else "ActVox CLI: not found",
                        "" if has_cli else "npm i -g @actvox/cli"))
    status = _auth_status(cli, profile, run) if has_cli else None
    if status and status.get("authenticated"):
        count = len(status.get("workspaceIds") or [])
        workspaces = f"{count} workspace" if count == 1 else f"{count} workspaces"
        checks.append(Check("login", True, f"CLI login ({status.get('profile', profile)}): {workspaces}"))
    else:
        checks.append(Check("login", False, "CLI login: not signed in", login_fix))
    shim = Path(scripts_dir) / GATE_SCRIPT_NAME
    has_shim = shim.exists() and SHIM_MARKER in shim.read_text(encoding="utf-8", errors="replace")
    checks.append(Check("gate", has_shim, f"Gate script: {shim}" if has_shim else "Gate script: not installed",
                        "" if has_shim else "hermes actvox install-gate"))
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = None
    error = state.get("lastError") if isinstance(state, dict) else None
    if isinstance(error, dict):
        checks.append(Check("last_tick", False, f"Last gate tick: {error.get('code')}: {error.get('message', '')}",
                            "fix the step above, then: hermes cron run actvox-inbox"))
    elif isinstance(state, dict):
        checks.append(Check("last_tick", True, "Last gate tick: healthy"))
    else:
        checks.append(Check("last_tick", None, "Last gate tick: none yet"))
    return checks


def cron_create_command(every: str) -> str:
    return (f'hermes cron create "every {every}" "{WORKER_PROMPT}" --name {CRON_JOB_NAME} '
            f"--skill {WORKER_SKILL} --script {GATE_SCRIPT_NAME}")


def setup_text(checks: list[Check], *, every: str) -> str:
    mark = {True: "ok  ", False: "TODO", None: "--  "}
    lines = ["ActVox for Hermes: setup", "", "From this terminal:"]
    for check in checks:
        lines.append(f"  [{mark[check.ok]}] {check.label}")
        if check.fix:
            lines.append(f"         run: {check.fix}")
    lines += [
        "",
        "Hosted MCP (Hermes writes through it). Run once, then check in a session with /actvox status:",
        "  hermes mcp add actvox --url https://api.actvox.com/mcp --auth oauth",
        "  hermes mcp login actvox",
        "  hermes config set plugins.entries.actvox.mcp_allowlist '[\"actvox\"]'",
        "",
        "The inbox worker (after the gate script is installed):",
        f"  {cron_create_command(every)}",
        "  hermes gateway install    # cron runs only while the gateway runs",
        "",
        "You approve every sign-in yourself in your browser. Nothing here asks for a token.",
    ]
    return "\n".join(lines) + "\n"
