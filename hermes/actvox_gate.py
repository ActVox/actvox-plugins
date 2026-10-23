"""Cron wake gate for the ActVox inbox worker.

A Hermes cron job runs this (through the shim `hermes actvox install-gate` writes) before
its agent turn. It reads the inbox with the person's own `actvox` CLI login and prints one
JSON line. `{"wakeAgent": false}` skips the agent run, so an empty inbox costs no model call.

Rules this file keeps:

- Standard library only: the shim imports it outside the Hermes plugin runtime.
- Always exit 0. Hermes honours `wakeAgent: false` only from a script that succeeded; a
  failing gate would wake the model on every tick. A failure wakes the agent once, so it can
  tell the person, and is then silent until a healthy tick.
- The context is ids, kinds and states only: no comment text and no titles. The worker
  reads the items through MCP, and user text never reaches the cron prompt scanner.
- Nothing here writes to ActVox.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

# The states in which an owner has work to start or resume (the server's NEXT_ACTIONS table).
OWNER_STATES = frozenset({"assigned", "acknowledged", "changes_requested", "claimed"})
# The wait before attempts 2, 3 and 4 of an item that is still pending. Attempt 4 is the last:
# the worker asks a person in the thread and the gate stops waking for that item.
BACKOFF_SECONDS = (15 * 60, 60 * 60, 6 * 60 * 60)
CLI_TIMEOUT_SECONDS = 30
STATE_VERSION = 1
MAX_ERROR_CHARS = 200


def empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "items": {}, "lastError": None}


def _iso_seconds(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _list(container: Any, key: str) -> list[dict[str, Any]]:
    items = container.get(key) if isinstance(container, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def pending_items(payload: dict[str, Any], now: float) -> list[dict[str, str]]:
    """The items Hermes should act on, from `actvox inbox --all --json`."""
    data = payload.get("data") if isinstance(payload, dict) else None
    return pending_in_workspaces(_list(data, "workspaces"), now)


def pending_in_workspaces(workspaces: list[dict[str, Any]], now: float) -> list[dict[str, str]]:
    """The same rule over a list of inbox workspaces: the CLI's `data.workspaces` or the
    hosted MCP `check_inbox` result's `workspaces` (same inner shapes)."""
    items: list[dict[str, str]] = []
    for ws in workspaces:
        if ws.get("skipped") or ws.get("error") or ws.get("assignable") is False:
            continue
        workspace_id = str(ws.get("workspaceId") or "")
        for mention in _list(ws.get("mentions"), "mentions"):
            if mention.get("id") and not mention.get("acknowledgedAt"):
                items.append({"kind": "mention", "id": str(mention["id"]), "workspaceId": workspace_id})
        for task in _list(ws.get("assignments"), "assignments"):
            state = task.get("state")
            if task.get("role") != "owner" or state not in OWNER_STATES or not task.get("id"):
                continue
            if not task.get("nextActions"):
                continue
            if state == "claimed":
                expires = _iso_seconds((task.get("lease") or {}).get("expiresAt"))
                if expires is not None and expires > now:
                    continue  # the claim is alive: Hermes is still working on it
            items.append({"kind": "assignment", "id": str(task["id"]), "workspaceId": workspace_id, "state": str(state)})
    return items


def _key(item: dict[str, str]) -> str:
    return f"{item['kind']}:{item['workspaceId']}:{item['id']}"


def decide(items: list[dict[str, str]], state: dict[str, Any], now: float):
    """Return `(wake, context, new_state)` for one healthy tick."""
    known = state.get("items") if isinstance(state.get("items"), dict) else {}
    new_items: dict[str, Any] = {}
    context: dict[str, list] = {"mentions": [], "assignments": [], "stuck": []}
    for item in items:
        key = _key(item)
        entry = known.get(key) if isinstance(known.get(key), dict) else None
        attempts = int(entry.get("attempts", 0)) if entry else 0
        if entry and entry.get("stuck"):
            new_items[key] = entry
            continue
        if entry and attempts >= 1:
            wait = BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1]
            if now < float(entry.get("lastWokenAt", 0)) + wait:
                new_items[key] = entry
                continue
        attempts += 1
        stuck = attempts > len(BACKOFF_SECONDS)
        new_items[key] = {"attempts": attempts, "lastWokenAt": now, "stuck": stuck}
        if stuck:
            context["stuck"].append({"kind": item["kind"], "id": item["id"], "workspaceId": item["workspaceId"]})
        elif item["kind"] == "mention":
            context["mentions"].append({"id": item["id"], "workspaceId": item["workspaceId"]})
        else:
            context["assignments"].append({"id": item["id"], "workspaceId": item["workspaceId"], "state": item["state"]})
    new_state = {"version": STATE_VERSION, "items": new_items, "lastError": None}
    wake = any(context.values())
    return wake, (context if wake else None), new_state


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return empty_state()
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".gate-state.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class GateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message[:MAX_ERROR_CHARS]


def read_inbox(cli: str, profile: str, run: Callable[..., Any]) -> dict[str, Any]:
    cmd = [cli, "inbox", "--all", "--json"] + (["--profile", profile] if profile else [])
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS, check=False)
    except FileNotFoundError:
        raise GateError("cli_missing", "The actvox CLI is not installed. Run: npm i -g @actvox/cli") from None
    except subprocess.TimeoutExpired:
        raise GateError("cli_timeout", f"actvox inbox did not answer in {CLI_TIMEOUT_SECONDS} s") from None
    try:
        payload = json.loads(proc.stdout or "")
    except ValueError:
        raise GateError("cli_bad_output", f"actvox inbox printed no JSON (exit {proc.returncode})") from None
    if proc.returncode != 0 or not isinstance(payload, dict) or payload.get("ok") is not True:
        error = payload.get("error") if isinstance(payload, dict) else None
        error = error if isinstance(error, dict) else {}
        raise GateError(str(error.get("code") or "cli_failed"), str(error.get("message") or f"actvox inbox exited {proc.returncode}"))
    return payload


def main(
    argv: Optional[list[str]] = None,
    *,
    run: Callable[..., Any] = subprocess.run,
    now: Callable[[], float] = time.time,
    stdout: Callable[[str], None] = print,
    stderr: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> int:
    parser = argparse.ArgumentParser(prog="actvox-inbox-gate")
    parser.add_argument("--cli", default=shutil.which("actvox") or "actvox")
    parser.add_argument("--profile", default="")
    parser.add_argument("--state", required=True)
    args = parser.parse_args(argv)
    state_path = Path(args.state)
    state = load_state(state_path)
    tick = now()
    try:
        payload = read_inbox(args.cli, args.profile, run)
    except GateError as exc:
        stderr(f"actvox gate: {exc.code}: {exc.message}")
        first = not state.get("lastError")
        state["lastError"] = {"code": exc.code, "message": exc.message, "at": tick}
        save_state(state_path, state)
        if first:
            context = {"gateError": {"code": exc.code, "message": exc.message}, "mentions": [], "assignments": [], "stuck": []}
            stdout(json.dumps({"wakeAgent": True, "context": context}))
        else:
            stdout(json.dumps({"wakeAgent": False}))
        return 0
    wake, context, new_state = decide(pending_items(payload, tick), state, tick)
    save_state(state_path, new_state)
    stdout(json.dumps({"wakeAgent": True, "context": context} if wake else {"wakeAgent": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
