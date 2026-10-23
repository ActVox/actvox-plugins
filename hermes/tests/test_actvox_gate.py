"""The cron gate: when an ActVox inbox tick wakes Hermes, and when it costs nothing."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import actvox_gate as gate  # noqa: E402

NOW = 1_800_000_000.0
MIN = 60.0
HOUR = 60 * MIN


def inbox(*workspaces):
    return {"schemaVersion": "1", "ok": True, "requestId": "local", "data": {"workspaces": list(workspaces)}, "warnings": []}


def workspace(workspace_id="ws1", mentions=(), assignments=(), **extra):
    return {
        "workspaceId": workspace_id,
        "notices": None,
        "mentions": {"mentions": list(mentions), "count": len(mentions), "hasMore": False},
        "assignments": {"assignments": list(assignments), "count": len(assignments)},
        **extra,
    }


def mention(mention_id="m1", **extra):
    return {"id": mention_id, "threadId": "t1", "body": "please look", "acknowledgedAt": None, **extra}


def assignment(assignment_id="a1", state="assigned", role="owner", lease=None, next_actions=("acknowledge", "release")):
    return {"id": assignment_id, "role": role, "state": state, "title": "Write the brief",
            "lease": lease, "nextActions": list(next_actions)}


class TestPendingItems:
    def test_empty_inbox_has_nothing_pending(self):
        assert gate.pending_items(inbox(workspace()), NOW) == []

    def test_unacknowledged_mention_is_pending(self):
        items = gate.pending_items(inbox(workspace(mentions=[mention()])), NOW)
        assert items == [{"kind": "mention", "id": "m1", "workspaceId": "ws1"}]

    def test_acknowledged_mention_is_not_pending(self):
        payload = inbox(workspace(mentions=[mention(acknowledgedAt="2026-10-23T10:00:00Z")]))
        assert gate.pending_items(payload, NOW) == []

    @pytest.mark.parametrize("state", ["assigned", "acknowledged", "changes_requested"])
    def test_owner_task_to_start_is_pending(self, state):
        items = gate.pending_items(inbox(workspace(assignments=[assignment(state=state)])), NOW)
        assert items == [{"kind": "assignment", "id": "a1", "workspaceId": "ws1", "state": state}]

    def test_claimed_task_with_live_lease_is_in_progress(self):
        live = {"expiresAt": "2027-06-01T00:00:00Z"}  # after NOW (2027-01-15T08:00:00Z)
        payload = inbox(workspace(assignments=[assignment(state="claimed", lease=live)]))
        assert gate.pending_items(payload, NOW) == []

    def test_claimed_task_with_expired_lease_is_pending(self):
        expired = {"expiresAt": "2026-01-01T00:00:00Z"}  # before NOW
        payload = inbox(workspace(assignments=[assignment(state="claimed", lease=expired)]))
        assert gate.pending_items(payload, NOW)[0]["state"] == "claimed"

    @pytest.mark.parametrize("role,state", [("reviewer", "needs_review"), ("requester", "assigned")])
    def test_review_and_requester_work_never_wakes(self, role, state):
        payload = inbox(workspace(assignments=[assignment(role=role, state=state)]))
        assert gate.pending_items(payload, NOW) == []

    def test_task_with_no_next_action_is_not_pending(self):
        payload = inbox(workspace(assignments=[assignment(next_actions=())]))
        assert gate.pending_items(payload, NOW) == []

    def test_skipped_and_failed_workspaces_are_ignored(self):
        payload = inbox(
            workspace("ws1", mentions=[mention()], skipped={"code": "agent_not_enabled", "message": "x"}),
            workspace("ws2", mentions=[mention("m2")], error={"code": "rate_limited", "message": "x", "retryable": True}),
            workspace("ws3", mentions=[mention("m3")]),
        )
        assert [item["id"] for item in gate.pending_items(payload, NOW)] == ["m3"]

    def test_no_comment_text_or_titles_leave_the_gate(self):
        payload = inbox(workspace(mentions=[mention()], assignments=[assignment()]))
        text = json.dumps(gate.pending_items(payload, NOW))
        assert "please look" not in text and "Write the brief" not in text


class TestDecide:
    def item(self, item_id="m1"):
        return {"kind": "mention", "id": item_id, "workspaceId": "ws1"}

    def test_nothing_pending_does_not_wake(self):
        wake, context, state = gate.decide([], gate.empty_state(), NOW)
        assert wake is False and context is None and state["items"] == {}

    def test_new_item_wakes_once(self):
        wake, context, state = gate.decide([self.item()], gate.empty_state(), NOW)
        assert wake is True
        assert context == {"mentions": [{"id": "m1", "workspaceId": "ws1"}], "assignments": [], "stuck": []}
        assert state["items"]["mention:ws1:m1"] == {"attempts": 1, "lastWokenAt": NOW, "stuck": False}

    def test_still_pending_item_waits_for_backoff(self):
        _, _, state = gate.decide([self.item()], gate.empty_state(), NOW)
        wake, _, state = gate.decide([self.item()], state, NOW + 14 * MIN)
        assert wake is False
        wake, _, state = gate.decide([self.item()], state, NOW + 15 * MIN)
        assert wake is True and state["items"]["mention:ws1:m1"]["attempts"] == 2

    def test_backoff_grows_then_item_goes_stuck_once(self):
        state, t = gate.empty_state(), NOW
        wakes = []
        for step in (0, 15 * MIN, HOUR, 6 * HOUR, 6 * HOUR, 24 * HOUR):
            t += step
            wake, context, state = gate.decide([self.item()], state, t)
            wakes.append((wake, context and context["stuck"]))
        assert wakes == [
            (True, []),
            (True, []),
            (True, []),
            (True, [{"kind": "mention", "id": "m1", "workspaceId": "ws1"}]),
            (False, None),
            (False, None),
        ]

    def test_item_that_left_the_inbox_is_forgotten(self):
        _, _, state = gate.decide([self.item()], gate.empty_state(), NOW)
        _, _, state = gate.decide([], state, NOW + MIN)
        assert state["items"] == {}

    def test_only_due_items_are_in_the_context(self):
        _, _, state = gate.decide([self.item("m1")], gate.empty_state(), NOW)
        wake, context, _ = gate.decide([self.item("m1"), self.item("m2")], state, NOW + MIN)
        assert wake is True
        assert [m["id"] for m in context["mentions"]] == ["m2"]

    def test_a_healthy_tick_clears_the_last_error(self):
        state = gate.empty_state()
        state["lastError"] = {"code": "auth_missing", "at": NOW}
        _, _, state = gate.decide([], state, NOW + MIN)
        assert state["lastError"] is None


class FakeCli:
    """Stands in for subprocess.run with the `actvox` CLI."""

    def __init__(self, stdout="", returncode=0, raises=None):
        self.stdout, self.returncode, self.raises, self.calls = stdout, returncode, raises, []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr="boom")


def run_gate(tmp_path, cli, now=NOW, profile="hermes"):
    out = []
    code = gate.main(
        ["--cli", "/opt/bin/actvox", "--profile", profile, "--state", str(tmp_path / "gate-state.json")],
        run=cli, now=lambda: now, stdout=out.append, stderr=lambda _msg: None,
    )
    return code, json.loads(out[-1])


class TestMain:
    def test_runs_the_cli_for_every_workspace_with_the_profile(self, tmp_path):
        cli = FakeCli(json.dumps(inbox(workspace())))
        run_gate(tmp_path, cli)
        cmd, kwargs = cli.calls[0]
        assert cmd == ["/opt/bin/actvox", "inbox", "--all", "--json", "--profile", "hermes"]
        assert kwargs["timeout"] == gate.CLI_TIMEOUT_SECONDS

    def test_empty_inbox_prints_wake_false(self, tmp_path):
        assert run_gate(tmp_path, FakeCli(json.dumps(inbox(workspace())))) == (0, {"wakeAgent": False})

    def test_work_prints_wake_true_with_context(self, tmp_path):
        code, line = run_gate(tmp_path, FakeCli(json.dumps(inbox(workspace(mentions=[mention()])))))
        assert code == 0 and line["wakeAgent"] is True
        assert line["context"]["mentions"] == [{"id": "m1", "workspaceId": "ws1"}]

    def test_state_persists_between_ticks(self, tmp_path):
        cli = FakeCli(json.dumps(inbox(workspace(mentions=[mention()]))))
        run_gate(tmp_path, cli)
        assert run_gate(tmp_path, cli, now=NOW + MIN) == (0, {"wakeAgent": False})

    @pytest.mark.parametrize("cli", [
        FakeCli(raises=FileNotFoundError("actvox")),
        FakeCli(raises=subprocess.TimeoutExpired("actvox", 30)),
        FakeCli(stdout=json.dumps({"ok": False, "error": {"code": "auth_missing", "message": "Run actvox auth login"}}), returncode=3),
        FakeCli(stdout="not json"),
    ])
    def test_cli_failure_wakes_once_to_report_then_stays_silent(self, tmp_path, cli):
        code, first = run_gate(tmp_path, cli)
        assert code == 0  # a non-zero exit would wake the model on every tick
        assert first["wakeAgent"] is True and first["context"]["gateError"]["code"]
        assert run_gate(tmp_path, cli, now=NOW + 15 * MIN) == (0, {"wakeAgent": False})

    def test_failure_keeps_the_item_backoff(self, tmp_path):
        work = FakeCli(json.dumps(inbox(workspace(mentions=[mention()]))))
        run_gate(tmp_path, work)
        run_gate(tmp_path, FakeCli(raises=FileNotFoundError("actvox")), now=NOW + MIN)
        state = json.loads((tmp_path / "gate-state.json").read_text())
        assert state["items"]["mention:ws1:m1"]["attempts"] == 1

    def test_corrupt_state_file_starts_fresh(self, tmp_path):
        (tmp_path / "gate-state.json").write_text("{not json")
        code, line = run_gate(tmp_path, FakeCli(json.dumps(inbox(workspace(mentions=[mention()])))))
        assert code == 0 and line["wakeAgent"] is True

    def test_profile_is_optional(self, tmp_path):
        cli = FakeCli(json.dumps(inbox(workspace())))
        run_gate(tmp_path, cli, profile="")
        assert "--profile" not in cli.calls[0][0]
