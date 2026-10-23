"""`hermes actvox setup` and `hermes actvox install-gate`."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

import actvox_setup as setup  # noqa: E402


def write_fake_cli(path: Path, inbox: dict, authenticated: bool = True) -> Path:
    """A stand-in `actvox` executable for the shim test."""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"INBOX = {json.dumps(inbox)!r}\n"
        f"AUTH = {json.dumps({'ok': True, 'data': {'authenticated': authenticated, 'profile': 'hermes', 'workspaceIds': ['ws1', 'ws2']}})!r}\n"
        "args = sys.argv[1:]\n"
        "print(INBOX if args[:1] == ['inbox'] else AUTH)\n"
    )
    path.chmod(0o755)
    return path


class TestInstallGate:
    def test_writes_a_marked_shim_with_the_given_values(self, tmp_path):
        target = setup.install_gate(tmp_path / "scripts", plugin_dir=PLUGIN_DIR, cli="/opt/bin/actvox",
                                    profile="hermes", state=tmp_path / "state.json")
        text = target.read_text()
        assert target.name == "actvox-inbox-gate.py"
        assert setup.SHIM_MARKER in text
        assert repr(str(PLUGIN_DIR)) in text and repr("/opt/bin/actvox") in text

    def test_rewrites_its_own_shim(self, tmp_path):
        kwargs = dict(plugin_dir=PLUGIN_DIR, cli="/a", profile="hermes", state=tmp_path / "s.json")
        setup.install_gate(tmp_path, **kwargs)
        target = setup.install_gate(tmp_path, **{**kwargs, "cli": "/b"})
        assert repr("/b") in target.read_text()

    def test_refuses_to_overwrite_a_file_it_did_not_write(self, tmp_path):
        (tmp_path / "actvox-inbox-gate.py").write_text("print('mine')\n")
        with pytest.raises(FileExistsError):
            setup.install_gate(tmp_path, plugin_dir=PLUGIN_DIR, cli="/a", profile="", state=tmp_path / "s.json")
        assert (tmp_path / "actvox-inbox-gate.py").read_text() == "print('mine')\n"

    def test_the_shim_runs_the_gate_end_to_end(self, tmp_path):
        inbox = {"ok": True, "data": {"workspaces": [{"workspaceId": "ws1",
                 "mentions": {"mentions": [{"id": "m1", "acknowledgedAt": None}]}, "assignments": {"assignments": []}}]}}
        cli = write_fake_cli(tmp_path / "actvox", inbox)
        shim = setup.install_gate(tmp_path / "scripts", plugin_dir=PLUGIN_DIR, cli=str(cli),
                                  profile="hermes", state=tmp_path / "data" / "gate-state.json")
        first = subprocess.run([sys.executable, "-I", str(shim)], capture_output=True, text=True, timeout=60)
        second = subprocess.run([sys.executable, "-I", str(shim)], capture_output=True, text=True, timeout=60)
        assert first.returncode == 0 and json.loads(first.stdout.splitlines()[-1])["wakeAgent"] is True
        assert second.returncode == 0 and json.loads(second.stdout.splitlines()[-1]) == {"wakeAgent": False}

    def test_the_shim_stays_silent_when_the_plugin_is_gone(self, tmp_path):
        shim = setup.install_gate(tmp_path, plugin_dir=tmp_path / "removed", cli="/a", profile="",
                                  state=tmp_path / "s.json")
        result = subprocess.run([sys.executable, "-I", str(shim)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0
        assert json.loads(result.stdout.splitlines()[-1]) == {"wakeAgent": False}
        assert "plugin not found" in result.stderr


class TestChecklist:
    def run_checks(self, tmp_path, cli, **kwargs):
        return {check.key: check for check in setup.checklist(
            cli=cli, profile="hermes", scripts_dir=tmp_path / "scripts", state_path=tmp_path / "state.json", **kwargs)}

    def test_missing_cli_names_the_install_command(self, tmp_path):
        checks = self.run_checks(tmp_path, cli="")
        assert checks["cli"].ok is False and checks["cli"].fix == "npm i -g @actvox/cli"
        assert checks["login"].ok is False

    def test_signed_out_cli_names_the_login_command(self, tmp_path):
        cli = write_fake_cli(tmp_path / "actvox", {}, authenticated=False)
        checks = self.run_checks(tmp_path, cli=str(cli))
        assert checks["cli"].ok is True
        assert checks["login"].ok is False and checks["login"].fix == "actvox auth login --profile hermes"

    def test_signed_in_cli_reports_its_workspaces(self, tmp_path):
        cli = write_fake_cli(tmp_path / "actvox", {})
        checks = self.run_checks(tmp_path, cli=str(cli))
        assert checks["login"].ok is True and "2 workspaces" in checks["login"].label

    def test_gate_check_follows_the_shim(self, tmp_path):
        cli = write_fake_cli(tmp_path / "actvox", {})
        assert self.run_checks(tmp_path, cli=str(cli))["gate"].ok is False
        setup.install_gate(tmp_path / "scripts", plugin_dir=PLUGIN_DIR, cli=str(cli), profile="hermes",
                           state=tmp_path / "state.json")
        assert self.run_checks(tmp_path, cli=str(cli))["gate"].ok is True

    def test_last_gate_error_is_reported(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps(
            {"version": 1, "items": {}, "lastError": {"code": "auth_missing", "message": "Run actvox auth login", "at": 1}}))
        checks = self.run_checks(tmp_path, cli="")
        assert checks["last_tick"].ok is False and "auth_missing" in checks["last_tick"].label


def test_cron_command_attaches_the_skill_and_the_gate():
    command = setup.cron_create_command("15m")
    assert command.startswith('hermes cron create "every 15m" ')
    assert "--skill actvox:actvox-inbox" in command and "--script actvox-inbox-gate.py" in command
    assert "--name actvox-inbox" in command


def test_setup_text_lists_every_step(tmp_path):
    text = setup.setup_text(setup.checklist(cli="", profile="hermes", scripts_dir=tmp_path,
                                            state_path=tmp_path / "s.json"), every="15m")
    for needle in ("hermes mcp add actvox", "hermes mcp login actvox", "mcp_allowlist",
                   "npm i -g @actvox/cli", "hermes actvox install-gate", "hermes cron create", "/actvox status"):
        assert needle in text, needle
    assert os.linesep in text or "\n" in text
