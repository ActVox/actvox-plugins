"""In-session ActVox reads: the first-turn inbox note and the `/actvox` command.

Everything here goes through `ctx.call_mcp("actvox", …)`, the person's own hosted MCP
sign-in. It is read-only: no claim, reply or acknowledgment.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

try:  # loaded as the plugin package by Hermes
    from . import actvox_gate
except ImportError:  # loaded as a top-level module by the tests
    import actvox_gate  # type: ignore[no-redef]

SERVER = "actvox"
NOTE_TIMEOUT_SECONDS = 5
COMMAND_TIMEOUT_SECONDS = 20
MCP_ADD = "hermes mcp add actvox --url https://api.actvox.com/mcp --auth oauth"
MCP_LOGIN = "hermes mcp login actvox"
ALLOWLIST_FIX = "hermes config set plugins.entries.actvox.mcp_allowlist '[\"actvox\"]'"
MCP_FIX = f"{MCP_ADD}, then {MCP_LOGIN}, then /reload-mcp"
WORKER_SKILL = "actvox:actvox-inbox"


def mcp_data(envelope: Any) -> Optional[dict[str, Any]]:
    """The JSON object an `actvox` tool returned, or None for an error or a non-object."""
    if not isinstance(envelope, dict) or envelope.get("ok") is not True:
        return None
    for value in (envelope.get("structuredContent"), envelope.get("result")):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                continue
        if isinstance(value, dict):
            return value
    return None


def plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def note_text(items: list[dict[str, str]]) -> Optional[str]:
    """One line for the first turn of a session, or None when nothing waits."""
    tasks = sum(1 for item in items if item["kind"] == "assignment")
    mentions = len(items) - tasks
    if not items:
        return None
    parts = [part for part in (
        plural(tasks, "task", "tasks") if tasks else "",
        plural(mentions, "mention", "mentions") if mentions else "",
    ) if part]
    verb = "waits" if len(items) == 1 else "wait"
    return (f"ActVox: {' and '.join(parts)} {verb} for you. To work them, load the skill "
            f"{WORKER_SKILL} (the person can list them with /actvox inbox).")


def call_actvox(ctx: Any, tool: str, arguments: dict[str, Any], timeout: float) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """`(data, problem)`: the tool's object, or a sentence that names the fix."""
    try:
        envelope = ctx.call_mcp(SERVER, tool, arguments, timeout=timeout)
    except PermissionError:
        return None, f"This plugin may not call the actvox MCP server yet. Run: {ALLOWLIST_FIX}"
    data = mcp_data(envelope)
    if data is not None:
        return data, None
    error = envelope.get("error") if isinstance(envelope, dict) else None
    text = error if isinstance(error, str) else json.dumps(error)[:200] if error else "no answer"
    if "not connected" in str(text) or "Unknown MCP server" in str(text) or "not configured" in str(text):
        return None, f"The actvox MCP server is not connected ({text}). Run: {MCP_FIX}"
    return None, f"actvox {tool} failed: {text}"


def make_session_note(ctx: Any, now: Callable[[], float] = time.time) -> Callable[..., Optional[str]]:
    """The `pre_llm_call` hook: on a session's first turn, say what waits in ActVox."""

    def on_pre_llm_call(*, is_first_turn: bool = False, **_kwargs: Any) -> Optional[str]:
        if not is_first_turn or ctx.current_cron_execution() is not None:
            return None
        data, _problem = call_actvox(ctx, "check_inbox", {"limit": 5}, NOTE_TIMEOUT_SECONDS)
        if data is None:
            return None  # never block or clutter a turn because ActVox is unreachable
        workspaces = [ws for ws in data.get("workspaces") or [] if isinstance(ws, dict)]
        return note_text(actvox_gate.pending_in_workspaces(workspaces, now()))

    return on_pre_llm_call


def inbox_report(data: dict[str, Any], now: float) -> str:
    lines: list[str] = []
    for ws in data.get("workspaces") or []:
        if not isinstance(ws, dict):
            continue
        name = ws.get("name") or ws.get("workspaceId")
        if ws.get("assignable") is False:
            lines.append(f"{name}: not assignable here")
            continue
        if ws.get("error"):
            lines.append(f"{name}: error {ws['error'].get('code', '')}")
            continue
        pending = actvox_gate.pending_in_workspaces([ws], now)
        tasks = [item for item in pending if item["kind"] == "assignment"]
        mentions = [item for item in pending if item["kind"] == "mention"]
        lines.append(f"{name}: {plural(len(tasks), 'task', 'tasks')}, {plural(len(mentions), 'mention', 'mentions')} to act on")
        lines.extend(f"  task {item['id']} · {item['state']}" for item in tasks)
        lines.extend(f"  mention {item['id']}" for item in mentions)
    if not lines:
        return "ActVox: no workspace answered."
    return "\n".join(lines + [f"Work them with the skill {WORKER_SKILL}."])


def status_report(ctx: Any) -> str:
    data, problem = call_actvox(ctx, "doctor", {}, COMMAND_TIMEOUT_SECONDS)
    if data is None:
        return f"ActVox: not ready. {problem}"
    connection = data.get("connection") or {}
    lines = [f"ActVox: connected to {data.get('apiUrl', 'ActVox')} (ok={bool(data.get('ok'))}).",
             "  Plugin MCP access (mcp_allowlist): granted · MCP sign-in: working"]
    for ws in connection.get("workspaces") or []:
        if not isinstance(ws, dict):
            continue
        handle = (ws.get("self") or {}).get("handle")
        scopes = ",".join(ws.get("scopes") or []) or "none"
        tasks = "takes tasks" if ws.get("assignable") else "no tasks"
        lines.append(f"  {ws.get('name', ws.get('workspaceId'))}: @{handle or '?'} · {scopes} · {tasks}")
    return "\n".join(lines)


def make_command(ctx: Any, now: Callable[[], float] = time.time) -> Callable[..., str]:
    """`/actvox [inbox|status]`."""

    def handle(raw_args: str = "", **_kwargs: Any) -> str:
        verb = (raw_args or "").strip().lower() or "inbox"
        if verb == "status":
            return status_report(ctx)
        if verb == "inbox":
            data, problem = call_actvox(ctx, "check_inbox", {"limit": 10}, COMMAND_TIMEOUT_SECONDS)
            return inbox_report(data, now()) if data is not None else f"ActVox: not ready. {problem}"
        return "Usage: /actvox [inbox|status]"

    return handle
