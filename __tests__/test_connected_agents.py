"""Exercise both adapters with real local processes; never call a paid model."""
import asyncio
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from connected_agents import runtime
from connected_agents.contracts import Draft, Provider, RehearsalError


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    script = tmp_path / "provider.py"
    script.write_text('''import json, os, pathlib, sys
prompt = sys.stdin.read()
assert "DEMO-104" in prompt
assert "SUPABASE_SERVICE_ROLE_KEY" not in os.environ
assert "ANTHROPIC_API_KEY" not in os.environ
assert "OPENAI_API_KEY" not in os.environ
assert "SECRET_CUSTOMER_EMAIL" not in prompt
draft = {"subject": "Invoice DEMO-104", "body": "Hello Alex, this is a reminder about invoice DEMO-104."}
if "exec" in sys.argv:
    assert os.environ["CODEX_HOME"].endswith("chatgpt")
    target = sys.argv[sys.argv.index("--output-last-message") + 1]
    pathlib.Path(target).write_text(json.dumps(draft), encoding="utf-8")
    print(json.dumps({"type": "turn.completed"}))
else:
    assert os.environ["CLAUDE_CONFIG_DIR"].endswith("claude")
    print(json.dumps({"subtype": "success", "is_error": False, "structured_output": draft}))
''', encoding="utf-8")
    original = runtime.draft_command
    monkeypatch.setattr(runtime, "draft_command", lambda provider, binary, work:
                        [sys.executable, str(script)] + original(provider, binary, work)[1:])
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "must-not-inherit")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-inherit")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    return script


@pytest.mark.parametrize("provider", list(Provider))
def test_both_native_protocols_produce_reviewable_drafts(fake_cli, tmp_path, provider):
    progress = []
    result = asyncio.run(runtime.rehearse(provider, tmp_path / "state", "unused",
                                         progress=progress.append))
    assert result["status"] == "draft_ready"
    assert result["provider"] == provider.value
    assert result["sent"] is False
    assert result["requires_human_review"] is True
    assert result["subscription_entitlement_verified"] is False
    assert result["solutionist_inference_calls"] == 0
    assert progress == ["running", "draft_ready"]


@pytest.mark.parametrize("provider", list(Provider))
def test_errors_do_not_fallback_or_leak_provider_logs(fake_cli, tmp_path, provider):
    fake_cli.write_text('import sys; sys.stdin.read(); print("PRIVATE_ACCOUNT_TOKEN"); sys.exit(7)')
    with pytest.raises(RehearsalError, match="^provider_failed$"):
        asyncio.run(runtime.rehearse(provider, tmp_path / "state", "unused"))


@pytest.mark.parametrize("value", [
    None, [], {"subject": "Fine", "body": "too short"},
    {"subject": "Header\nBcc: unwanted", "body": "A message that is long enough."},
    {"subject": "Fine", "body": "A message that is long enough.", "send": True},
    {"subject": "Fine", "body": "a" * 4001},
    {"subject": "Fine", "body": 123},
])
def test_rejects_unusable_or_authority_bearing_output(value):
    with pytest.raises(RehearsalError, match="invalid_output"):
        Draft.parse(value)


def test_claude_failure_cannot_masquerade_as_a_draft(tmp_path):
    payload = {"is_error": True, "subtype": "error_max_turns",
               "structured_output": {"subject": "Fine", "body": "An otherwise valid long message."}}
    with pytest.raises(RehearsalError, match="provider_failed"):
        runtime.decode(Provider.CLAUDE, json.dumps(payload).encode(), tmp_path)


def test_codex_interruption_with_partial_file_is_not_success(tmp_path):
    (tmp_path / "draft.json").write_text(json.dumps(
        {"subject": "Fine", "body": "An otherwise valid long message."}))
    with pytest.raises(RehearsalError, match="incomplete_output"):
        runtime.decode(Provider.CHATGPT, b'{"type":"thread.started"}', tmp_path)


def test_codex_error_after_completed_turn_is_not_success(tmp_path):
    with pytest.raises(RehearsalError, match="provider_failed"):
        runtime.decode(Provider.CHATGPT,
                       b'{"type":"turn.completed"}\n{"type":"turn.failed"}', tmp_path)


def test_oversized_process_output_is_bounded(tmp_path):
    with pytest.raises(RehearsalError, match="provider_output_too_large"):
        asyncio.run(runtime.run_process(
            [sys.executable, "-c", 'import sys; sys.stdin.read(); print("x" * 1100000)'],
            dict(os.environ), tmp_path, "fixture", 10))


def test_timeout_reaps_a_process_with_busy_output_pipes(tmp_path):
    with pytest.raises(RehearsalError, match="timed_out"):
        asyncio.run(runtime.run_process(
            [sys.executable, "-c", 'import os\nwhile True: os.write(1, b"x" * 16384)'],
            dict(os.environ), tmp_path, "", .3))


def test_timeout_terminates_the_actual_child(tmp_path, monkeypatch):
    created = []
    original = asyncio.create_subprocess_exec

    async def capture(*args, **kwargs):
        proc = await original(*args, **kwargs)
        created.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    with pytest.raises(RehearsalError, match="timed_out"):
        asyncio.run(runtime.run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            dict(os.environ), tmp_path, "", .15))
    assert created[0].returncode is not None


def test_cancellation_terminates_the_actual_child(tmp_path, monkeypatch):
    created = []
    original = asyncio.create_subprocess_exec

    async def capture(*args, **kwargs):
        proc = await original(*args, **kwargs)
        created.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)

    async def scenario():
        task = asyncio.create_task(runtime.run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            dict(os.environ), tmp_path, "", 10))
        while not created:
            await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert created[0].returncode is not None

    asyncio.run(scenario())


def test_no_shell_wrapper_execution(tmp_path):
    wrapper = tmp_path / "codex.cmd"
    wrapper.write_text("@echo should never execute")
    with pytest.raises(RehearsalError, match="native_executable_required"):
        runtime.executable(Provider.CHATGPT, str(wrapper))


@pytest.mark.parametrize("provider,payload", [
    (Provider.CHATGPT, b"Logged in using ChatGPT\n"),
    (Provider.CLAUDE, b'{"loggedIn":true,"authMethod":"oauth_token","email":"private@test"}'),
])
def test_status_does_not_expose_account_details(tmp_path, monkeypatch, provider, payload):
    async def status(*args):
        return 0, payload, b""
    monkeypatch.setattr(runtime, "run_process", status)
    result = asyncio.run(runtime.auth_status(provider, tmp_path, "unused"))
    assert result["authenticated"] is True
    assert "private" not in json.dumps(result)
    assert set(result) == {"authenticated", "auth_method"}


@pytest.mark.parametrize("provider", list(Provider))
def test_missing_login_is_not_ready(tmp_path, monkeypatch, provider):
    async def status(*args):
        return 1, b"", b"Private provider diagnostic"
    monkeypatch.setattr(runtime, "run_process", status)
    assert asyncio.run(runtime.auth_status(provider, tmp_path, "unused")) == {
        "authenticated": False, "auth_method": "unknown"}
