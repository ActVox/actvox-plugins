"""`register(ctx)`: what the plugin adds to Hermes, and the `hermes actvox` commands."""
import argparse
import importlib.util
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin():
    """Import the plugin as a package, the way Hermes loads it."""
    name = "actvox_plugin_under_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "__init__.py",
                                                  submodule_search_locations=[str(PLUGIN_DIR)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RecordingCtx:
    def __init__(self, settings=None):
        self.skills, self.hooks, self.commands, self.cli = {}, {}, {}, {}
        self.settings = settings or {}

    def register_skill(self, name, path):
        self.skills[name] = Path(path)

    def register_hook(self, event, callback):
        self.hooks[event] = callback

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = (handler, description, args_hint)

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli[name] = (setup_fn, handler_fn)

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def call_mcp(self, *args, **kwargs):
        return {"ok": False, "error": "MCP server 'actvox' is not connected"}

    def current_cron_execution(self):
        return None


def test_register_adds_skills_hook_and_commands():
    plugin, ctx = load_plugin(), RecordingCtx()
    plugin.register(ctx)
    assert set(ctx.skills) == {"actvox", "actvox-inbox"}
    assert all(path.name == "SKILL.md" and path.exists() for path in ctx.skills.values())
    assert set(ctx.hooks) == {"pre_llm_call"}
    assert set(ctx.commands) == {"actvox"} and ctx.commands["actvox"][2] == "[inbox|status]"
    assert set(ctx.cli) == {"actvox"}


def test_skills_have_frontmatter_names_that_match_their_folders():
    for skill in (PLUGIN_DIR / "skills").iterdir():
        head = (skill / "SKILL.md").read_text().split("---")[1]
        assert f"name: {skill.name}\n" in head
        assert "description: " in head


def cli(ctx, argv, monkeypatch, tmp_path, plugin):
    monkeypatch.setattr(plugin, "_paths", lambda: (tmp_path / "scripts", tmp_path / "data" / "gate-state.json"))
    setup_fn, handler = ctx.cli["actvox"]
    parser = argparse.ArgumentParser(prog="hermes actvox")
    setup_fn(parser)
    lines = []
    monkeypatch.setattr(plugin, "print", lines.append, raising=False)
    code = plugin._make_cli_handler(ctx, out=lines.append)(parser.parse_args(argv))
    return code, "\n".join(lines)


def test_install_gate_writes_the_shim_and_prints_the_cron_command(monkeypatch, tmp_path):
    plugin, ctx = load_plugin(), RecordingCtx()
    plugin.register(ctx)
    fake_cli = tmp_path / "actvox"
    fake_cli.write_text("#!/bin/sh\n")
    code, text = cli(ctx, ["install-gate", "--cli", str(fake_cli)], monkeypatch, tmp_path, plugin)
    shim = tmp_path / "scripts" / "actvox-inbox-gate.py"
    assert code == 0 and shim.exists()
    assert repr("hermes") in shim.read_text()  # the default CLI profile
    assert "hermes cron create" in text and "--script actvox-inbox-gate.py" in text


def test_install_gate_uses_the_profile_setting(monkeypatch, tmp_path):
    plugin, ctx = load_plugin(), RecordingCtx({"cli_profile": "team-bot"})
    plugin.register(ctx)
    cli(ctx, ["install-gate", "--cli", "/opt/actvox"], monkeypatch, tmp_path, plugin)
    assert repr("team-bot") in (tmp_path / "scripts" / "actvox-inbox-gate.py").read_text()


def test_install_gate_without_a_cli_explains_the_fix(monkeypatch, tmp_path):
    plugin, ctx = load_plugin(), RecordingCtx()
    plugin.register(ctx)
    monkeypatch.setattr(plugin.shutil, "which", lambda _name: None)
    code, text = cli(ctx, ["install-gate"], monkeypatch, tmp_path, plugin)
    assert code == 1 and "npm i -g @actvox/cli" in text


def test_setup_prints_the_checklist(monkeypatch, tmp_path):
    plugin, ctx = load_plugin(), RecordingCtx()
    plugin.register(ctx)
    monkeypatch.setattr(plugin.shutil, "which", lambda _name: None)
    code, text = cli(ctx, ["setup"], monkeypatch, tmp_path, plugin)
    assert code == 0 and "ActVox for Hermes: setup" in text and "[TODO] ActVox CLI: not found" in text


def test_no_subcommand_prints_usage(monkeypatch, tmp_path):
    plugin, ctx = load_plugin(), RecordingCtx()
    plugin.register(ctx)
    code, text = cli(ctx, [], monkeypatch, tmp_path, plugin)
    assert code == 2 and text.startswith("Usage: hermes actvox")
