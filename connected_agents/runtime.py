"""Run an unmodified, customer-installed CLI against a synthetic fixture.

Separate provider homes keep sign-in under the native client's control. Nothing
reads, copies or uploads its credential files. This is a local development
rehearsal, not the hosted worker or a production tenant isolation boundary.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from .contracts import Draft, OUTPUT_SCHEMA, Provider, RehearsalError, fixture_prompt

MAX_OUTPUT = 1_000_000
SAFE_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "LANG", "LC_ALL", "TERM",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
}


def provider_env(provider: Provider, state: Path) -> dict[str, str]:
    # Allowlist prevents silent use of a platform API key, arbitrary proxy,
    # shell preload, or another agent's injected credentials/configuration.
    env = {k: v for k, v in os.environ.items() if k.upper() in SAFE_ENV}
    home = state.resolve() / provider.value
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    env["CODEX_HOME" if provider == Provider.CHATGPT else "CLAUDE_CONFIG_DIR"] = str(home)
    return env


def executable(provider: Provider, override: str | None = None) -> str:
    name = "codex" if provider == Provider.CHATGPT else "claude"
    candidate = override or shutil.which(name)
    # Windows npm wrappers are scripts. Resolve only the known native binary;
    # never interpolate a wrapper command or a prompt into a shell.
    if candidate and Path(candidate).suffix.lower() in {".cmd", ".bat", ".ps1"}:
        if provider == Provider.CLAUDE:
            candidate = str(Path(candidate).parent / "node_modules" / "@anthropic-ai"
                            / "claude-code" / "bin" / "claude.exe")
        else:
            raise RehearsalError("native_executable_required")
    if not candidate or not Path(candidate).is_file():
        raise RehearsalError("provider_not_installed")
    return str(Path(candidate).resolve())


def login_command(provider: Provider, binary: str) -> list[str]:
    return [binary, "login"] if provider == Provider.CHATGPT else [binary, "auth", "login"]


async def auth_status(provider: Provider, state: Path, binary: str) -> dict:
    args = ([binary, "login", "status"] if provider == Provider.CHATGPT
            else [binary, "auth", "status"])
    with TemporaryDirectory(prefix="solutionist-status-") as directory:
        code, out, err = await run_process(args, provider_env(provider, state),
                                           Path(directory), "", 15)
    method = "unknown"
    if code == 0:
        if provider == Provider.CHATGPT:
            method = "chatgpt" if b"chatgpt" in (out + err).lower() else "unknown"
        else:
            try:
                value = json.loads(out)
                if value.get("loggedIn") is not True:
                    return {"authenticated": False, "auth_method": "unknown"}
                # Pass only a small known enum, never an email, org, or token.
                native_method = value.get("authMethod")
                method = native_method if native_method in {"oauth_token", "api_key"} else "unknown"
            except (ValueError, AttributeError):
                raise RehearsalError("invalid_auth_status") from None
    return {"authenticated": code == 0, "auth_method": method}


def draft_command(provider: Provider, binary: str, work: Path) -> list[str]:
    if provider == Provider.CLAUDE:
        return [binary, "-p", "--output-format", "json", "--json-schema",
                json.dumps(OUTPUT_SCHEMA), "--tools", "", "--permission-mode", "dontAsk",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
                "--disable-slash-commands", "--no-session-persistence", "--no-chrome",
                "--safe-mode"]
    schema = work / "draft-schema.json"
    schema.write_text(json.dumps(OUTPUT_SCHEMA), encoding="utf-8")
    args = [binary, "exec", "--ignore-user-config", "--ephemeral",
            "--skip-git-repo-check", "--sandbox", "read-only", "--json",
            "--output-schema", str(schema), "--output-last-message", str(work / "draft.json")]
    for setting in (
        'approval_policy="never"', 'web_search="disabled"', "project_doc_max_bytes=0",
        "features.shell_tool=false", "features.unified_exec=false",
        "features.multi_agent=false",
        "features.plugins=false", "features.apps=false", "features.memories=false",
        "features.browser_use=false", "features.computer_use=false",
        "features.hooks=false", "features.image_generation=false",
        "features.remote_plugin=false", "features.workspace_dependencies=false",
        "features.skip_host_skill_discovery=true",
    ):
        args.extend(["-c", setting])
    return args + ["-"]


async def _drain(reader: asyncio.StreamReader) -> bytes:
    data = bytearray()
    oversized = False
    while chunk := await reader.read(16384):
        if len(data) + len(chunk) > MAX_OUTPUT:
            oversized = True
        if not oversized:
            data.extend(chunk)
        # Keep draining after the cap without retaining more bytes. Otherwise
        # a full pipe can deadlock process.wait(), even after SIGKILL on POSIX.
    if oversized:
        raise RehearsalError("provider_output_too_large")
    return bytes(data)


async def _stop(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    if os.name == "nt":
        # Kill only this rehearsal's process tree, including native CLI helpers.
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        killer = await asyncio.create_subprocess_exec(
            str(Path(system_root) / "System32" / "taskkill.exe"),
            "/PID", str(proc.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    await proc.wait()


async def run_process(args: list[str], env: dict[str, str], cwd: Path,
                      prompt: str, timeout: float) -> tuple[int, bytes, bytes]:
    if not 0 < timeout <= 300:
        raise ValueError("timeout must be between 0 and 300 seconds")
    kwargs = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
              else {"start_new_session": True})
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **kwargs)
    stdout = asyncio.create_task(_drain(proc.stdout))
    stderr = asyncio.create_task(_drain(proc.stderr))
    try:
        async with asyncio.timeout(timeout):
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            # Drainers must survive timeout/cancellation until cleanup kills
            # the process and reaches EOF; paused pipe readers prevent reaping.
            _, out, err = await asyncio.gather(
                proc.wait(), asyncio.shield(stdout), asyncio.shield(stderr))
        return proc.returncode, out, err
    except TimeoutError:
        raise RehearsalError("timed_out") from None
    finally:
        await _stop(proc)
        for task in (stdout, stderr):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout, stderr, return_exceptions=True)


def decode(provider: Provider, stdout: bytes, work: Path) -> Draft:
    try:
        if provider == Provider.CLAUDE:
            result = json.loads(stdout)
            if result.get("is_error") or result.get("subtype") != "success":
                raise RehearsalError("provider_failed")
            return Draft.parse(result.get("structured_output"))
        # Require a completed turn, not just a file created before an error.
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        if any(e.get("type") in {"error", "turn.failed"} for e in events):
            raise RehearsalError("provider_failed")
        if not any(e.get("type") == "turn.completed" for e in events):
            raise RehearsalError("incomplete_output")
        path = work / "draft.json"
        if path.stat().st_size > MAX_OUTPUT:
            raise RehearsalError("provider_output_too_large")
        return Draft.parse(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError, AttributeError, TypeError):
        raise RehearsalError("invalid_output") from None


async def rehearse(provider: Provider, state: Path, binary: str,
                   timeout: float = 180,
                   progress: Callable[[str], None] = lambda _: None) -> dict:
    env = provider_env(provider, state)
    with TemporaryDirectory(prefix="solutionist-fixture-") as directory:
        work = Path(directory)
        args = draft_command(provider, binary, work)
        progress("running")
        try:
            code, out, _ = await run_process(args, env, work, fixture_prompt(), timeout)
            if code:
                raise RehearsalError("provider_failed")
            draft = decode(provider, out, work)
        except asyncio.CancelledError:
            progress("cancelled")
            raise
        except (RehearsalError, OSError):
            progress("failed")
            raise
        progress("draft_ready")
        return {
            "provider": provider.value, "status": "draft_ready", "fixture_only": True,
            "subject": draft.subject, "body": draft.body,
            "sent": False, "requires_human_review": True,
            "execution_source": "customer_device",
            "funding_source": "provider_native_account",
            "subscription_entitlement_verified": False,
            "solutionist_inference_calls": 0,
        }
