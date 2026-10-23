"""ActVox for Hermes: Hermes works its ActVox inbox like a team member.

- Skills `actvox:actvox` (the workspace) and `actvox:actvox-inbox` (the worker).
- A first-turn note when tasks or mentions wait (`pre_llm_call`).
- `/actvox [inbox|status]` in a session.
- `hermes actvox setup` and `hermes actvox install-gate` in a terminal.

ActVox reads and writes go through the person's own `actvox` MCP server
(`ctx.call_mcp`, granted by `plugins.entries.actvox.mcp_allowlist`). The cron gate runs
the person's own `actvox` CLI. This plugin holds no credential.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any, Callable

from . import actvox_inbox, actvox_setup

PLUGIN_NAME = "actvox"
PLUGIN_DIR = Path(__file__).resolve().parent
DEFAULT_CLI_PROFILE = "hermes"
DEFAULT_EVERY = "15m"


def _paths() -> tuple[Path, Path]:
    """`(scripts_dir, gate_state_path)` for the active profile."""
    from plugins.plugin_storage import plugin_data_dir

    data_dir = Path(plugin_data_dir(PLUGIN_NAME))
    return data_dir.parent.parent / "scripts", data_dir / "gate-state.json"


def _cli_settings(ctx: Any, args: argparse.Namespace) -> tuple[str, str]:
    profile = args.profile if args.profile is not None else ctx.get_config("cli_profile", DEFAULT_CLI_PROFILE)
    cli = args.cli or ctx.get_config("cli_path", "") or shutil.which("actvox") or ""
    return str(cli), str(profile or "")


def _setup_parser(parser: argparse.ArgumentParser) -> None:
    subs = parser.add_subparsers(dest="actvox_command")
    for name, help_text in (("setup", "Check the ActVox setup and print the next command"),
                            ("install-gate", "Write the cron gate script into $HERMES_HOME/scripts/")):
        sub = subs.add_parser(name, help=help_text)
        sub.add_argument("--profile", default=None, help="actvox CLI login profile (default: hermes)")
        sub.add_argument("--cli", default="", help="path to the actvox CLI (default: found on PATH)")
        sub.add_argument("--every", default=DEFAULT_EVERY, help="cron interval to print (default: 15m)")


def _make_cli_handler(ctx: Any, out: Callable[[str], None] = print) -> Callable[[argparse.Namespace], int]:
    def handle(args: argparse.Namespace) -> int:
        command = getattr(args, "actvox_command", None)
        if command not in ("setup", "install-gate"):
            out("Usage: hermes actvox <setup|install-gate>")
            return 2
        cli, profile = _cli_settings(ctx, args)
        scripts_dir, state_path = _paths()
        if command == "install-gate":
            if not cli:
                out("The actvox CLI is not on PATH. Install it (npm i -g @actvox/cli) or pass --cli <path>.")
                return 1
            try:
                target = actvox_setup.install_gate(scripts_dir, plugin_dir=PLUGIN_DIR, cli=cli,
                                                   profile=profile, state=state_path)
            except FileExistsError as exc:
                out(str(exc))
                return 1
            out(f"Wrote {target}")
            out("Create the inbox worker job (once):")
            out(f"  {actvox_setup.cron_create_command(args.every)}")
            return 0
        checks = actvox_setup.checklist(cli=cli, profile=profile, scripts_dir=scripts_dir, state_path=state_path)
        out(actvox_setup.setup_text(checks, every=args.every).rstrip("\n"))
        return 0

    return handle


def register(ctx: Any) -> None:
    skills_dir = PLUGIN_DIR / "skills"
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.exists():
            ctx.register_skill(child.name, skill_md)
    ctx.register_hook("pre_llm_call", actvox_inbox.make_session_note(ctx))
    ctx.register_command(
        "actvox",
        handler=actvox_inbox.make_command(ctx),
        description="ActVox: what waits in your inbox, and the connection status",
        args_hint="[inbox|status]",
    )
    # Hermes makes the handler's int return the exit code.
    ctx.register_cli_command(
        "actvox",
        help="Set up the ActVox inbox worker",
        setup_fn=_setup_parser,
        handler_fn=_make_cli_handler(ctx),
    )
