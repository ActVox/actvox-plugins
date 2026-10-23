"""The in-session reads: the first-turn note and `/actvox`."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import actvox_inbox as inbox  # noqa: E402

NOW = 1_800_000_000.0


class FakeCtx:
    def __init__(self, answers=None, raises=None, cron=None):
        self.answers, self.raises, self.cron, self.calls = answers or {}, raises, cron, []

    def call_mcp(self, server, tool, arguments=None, timeout=30):
        self.calls.append((server, tool, arguments, timeout))
        if self.raises:
            raise self.raises
        return self.answers.get(tool, {"ok": False, "error": "MCP server 'actvox' is not connected"})

    def current_cron_execution(self):
        return self.cron


def ok(data):
    # Hermes hands the tool's text content back as a JSON string.
    return {"ok": True, "result": json.dumps(data)}


def check_inbox(mentions=(), assignments=()):
    return ok({"workspaces": [
        {"workspaceId": "ws1", "name": "Team", "assignable": True,
         "mentions": {"mentions": list(mentions), "count": len(mentions), "hasMore": False},
         "assignments": {"assignments": list(assignments), "count": len(assignments)}},
        {"workspaceId": "ws2", "name": "Personal", "assignable": False},
    ]})


MENTION = {"id": "m1", "threadId": "t1", "body": "ping", "acknowledgedAt": None}
TASK = {"id": "a1", "role": "owner", "state": "assigned", "title": "x", "lease": None, "nextActions": ["acknowledge"]}


class TestMcpData:
    def test_parses_json_text(self):
        assert inbox.mcp_data(ok({"a": 1})) == {"a": 1}

    def test_prefers_structured_content(self):
        assert inbox.mcp_data({"ok": True, "result": "text", "structuredContent": {"b": 2}}) == {"b": 2}

    def test_error_and_non_object_are_none(self):
        assert inbox.mcp_data({"ok": False, "error": "x"}) is None
        assert inbox.mcp_data({"ok": True, "result": "plain words"}) is None


class TestSessionNote:
    def test_first_turn_with_work_gets_one_line(self):
        hook = inbox.make_session_note(FakeCtx({"check_inbox": check_inbox([MENTION], [TASK])}), now=lambda: NOW)
        note = hook(is_first_turn=True, session_id="s", user_message="hi")
        assert note.startswith("ActVox: 1 task and 1 mention wait for you.")
        assert "actvox:actvox-inbox" in note

    def test_single_item_reads_naturally(self):
        hook = inbox.make_session_note(FakeCtx({"check_inbox": check_inbox([MENTION])}), now=lambda: NOW)
        assert hook(is_first_turn=True).startswith("ActVox: 1 mention waits for you.")

    def test_later_turns_and_cron_runs_say_nothing(self):
        ctx = FakeCtx({"check_inbox": check_inbox([MENTION])})
        assert inbox.make_session_note(ctx)(is_first_turn=False) is None
        cron_ctx = FakeCtx({"check_inbox": check_inbox([MENTION])}, cron=object())
        assert inbox.make_session_note(cron_ctx)(is_first_turn=True) is None
        assert ctx.calls == [] and cron_ctx.calls == []

    def test_empty_inbox_says_nothing(self):
        assert inbox.make_session_note(FakeCtx({"check_inbox": check_inbox()}))(is_first_turn=True) is None

    def test_unreachable_or_not_allowed_says_nothing(self):
        assert inbox.make_session_note(FakeCtx())(is_first_turn=True) is None
        assert inbox.make_session_note(FakeCtx(raises=PermissionError("no")))(is_first_turn=True) is None

    def test_the_note_uses_a_short_timeout_and_small_limit(self):
        ctx = FakeCtx({"check_inbox": check_inbox()})
        inbox.make_session_note(ctx)(is_first_turn=True)
        assert ctx.calls == [("actvox", "check_inbox", {"limit": 5}, inbox.NOTE_TIMEOUT_SECONDS)]


class TestCommand:
    def test_default_verb_is_inbox(self):
        reply = inbox.make_command(FakeCtx({"check_inbox": check_inbox([MENTION], [TASK])}), now=lambda: NOW)("")
        assert "Team: 1 task, 1 mention to act on" in reply
        assert "task a1 · assigned" in reply and "mention m1" in reply
        assert "Personal: not assignable here" in reply

    def test_status_lists_workspaces_and_handles(self):
        doctor = ok({"ok": True, "apiUrl": "https://api.actvox.com", "connection": {"workspaces": [
            {"workspaceId": "ws1", "name": "Team", "assignable": True, "scopes": ["read", "write"], "self": {"handle": "hermes"}},
        ]}})
        reply = inbox.make_command(FakeCtx({"doctor": doctor}))("status")
        assert "connected to https://api.actvox.com" in reply
        assert "Team: @hermes · read,write · takes tasks" in reply

    def test_missing_allowlist_names_the_config_key(self):
        reply = inbox.make_command(FakeCtx(raises=PermissionError("no")))("status")
        assert "plugins.entries.actvox.mcp_allowlist" in reply

    def test_disconnected_server_names_the_mcp_steps(self):
        reply = inbox.make_command(FakeCtx())("inbox")
        assert "hermes mcp login actvox" in reply

    def test_unknown_verb_prints_usage(self):
        assert inbox.make_command(FakeCtx())("launch") == "Usage: /actvox [inbox|status]"
