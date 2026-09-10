# Claude and ChatGPT connection preparation

Decision: support **both Claude and ChatGPT** under one Solutionist brand and
one business workflow contract. Recorded 2026-09-10. Neither provider is a
separate edition. Connect and Complete remain the proposed funding arrangements.

## What this branch implements

`connected_agents` is a local, Python 3.11+ development rehearsal. It has separate
adapters for unmodified Claude Code and Codex, native sign-in entry points,
sanitized authentication status, and a shared invoice-follow-up draft contract.
The public provider IDs are `claude` and `chatgpt`; the latter executes through
Codex. They are account/provider choices, not hardcoded model IDs.

The rehearsal accepts **only its built-in synthetic invoice**. It does not load
business data, listen on a port, poll production jobs, pair a device, approve
anything, or send a message. It is not imported by the FastAPI server. Production
`service_profile.external_agent.in_app_delegation_supported` stays false.

The existing MCP connector remains the way to use Solutionist from Claude or
ChatGPT. That direction of control is separate from Chief dispatching tasks to
a customer's agent. This branch does not claim that MCP alone supplies that
execution capacity.

## Local setup

Install each provider's official native client. Do not replace or modify its
binary. Use an account-private directory outside the repository for native
sign-in state. The program creates distinct `chatgpt` and `claude` subdirectories.
Never commit, upload, or copy these directories into a server or shared image.

From the backend repository, repeat these commands for each provider:

On Windows, `./scripts/setup-connected-ai.ps1` runs installation checks and
native sign-in for both providers in sequence. It does not run a paid draft.
Use `-Provider claude` or `-Provider chatgpt` to finish one separately. The manual
equivalents below also work with an explicit executable path.

```powershell
python -m connected_agents check --provider chatgpt --state-dir "$env:LOCALAPPDATA/Solutionist/ConnectedAI"
python -m connected_agents login --provider chatgpt --state-dir "$env:LOCALAPPDATA/Solutionist/ConnectedAI"
python -m connected_agents status --provider chatgpt --state-dir "$env:LOCALAPPDATA/Solutionist/ConnectedAI"
python -m connected_agents draft --provider chatgpt --state-dir "$env:LOCALAPPDATA/Solutionist/ConnectedAI"

python -m connected_agents check --provider claude --state-dir "$env:LOCALAPPDATA/Solutionist/ConnectedAI"
python -m connected_agents login --provider claude --state-dir "$env:LOCALAPPDATA/Solutionist/ConnectedAI"
python -m connected_agents status --provider claude --state-dir "$env:LOCALAPPDATA/Solutionist/ConnectedAI"
python -m connected_agents draft --provider claude --state-dir "$env:LOCALAPPDATA/Solutionist/ConnectedAI"
```

If the executable is not on PATH, append `--executable` with its native binary
path. Windows `.cmd`, `.bat`, and `.ps1` wrappers are never executed as shell
commands. The known Claude npm wrapper can resolve to its bundled native binary;
Codex wrappers require an explicit native executable path. On macOS/Linux choose
an account-private state directory, for example `~/.local/share/solutionist-ai`.

`login` opens the provider's own interactive flow. Sign in there; do not paste
subscription tokens into Solutionist. The harness does not read credential
files, intercept authentication, or accept an API key option. A native provider
account can still have its own paid billing arrangement: successful sign-in
does not verify a subscription allowance or promise unlimited use.

`check` verifies installation only. `status` reports authentication without an
email, organization name, or credential. `draft` first requires authentication,
then sends the synthetic fixture to the chosen provider. It can consume that
account's provider allowance. It prints progress to stderr and a validated JSON
draft to stdout. Exit codes: 0 success, 1 failure, 130 user cancellation.

Press Ctrl+C to cancel; `--timeout 60` gives a shorter deadline (maximum 300
seconds). Errors do not trigger another provider or Solutionist-paid fallback.
The return envelope marks `sent: false`, `requires_human_review: true`,
`fixture_only: true`, and zero Solutionist inference calls. Token usage and
subscription entitlement are not asserted from untrusted output.

## Execution boundaries

- Each run uses a temporary working directory and a small environment allowlist.
  Platform API keys, Supabase secrets, provider proxy overrides, and shell
  preload variables are not inherited.
- Claude uses an empty tool list, empty MCP configuration, safe mode, disabled
  hooks and slash commands, and no session persistence. It does not use `--bare`,
  which changes the native authentication behavior.
- Codex uses a read-only sandbox, no approval escalation, disabled shell,
  browser, computer, app, plugin, memory and image-generation features, and
  ephemeral output. Managed provider policies remain authoritative. The harness
  is not a substitute for OS isolation before accepting untrusted live jobs.
- Output size and duration are bounded. Completed provider output must pass the
  shared schema and length checks. A partial output file or failed turn does not
  become a successful draft. Raw provider errors are not exposed to the server.
- Local cancellation terminates the rehearsal process; process groups on POSIX
  and the selected process tree on Windows are used for cleanup. This is not a
  durable distributed cancellation protocol or a guarantee of refunded usage.

## Verification and remaining release gates

Validated locally against installation metadata for Codex CLI 0.153.4 and Claude
Code 2.1.267. Both new, isolated sign-in homes correctly report unauthenticated.
No real account/model run has been completed. `__tests__/test_connected_agents.py`
executes fake native processes through both adapters, covering draft results,
failed/partial/invalid output, cancellation, timeouts, secret exclusion, and
oversized responses. It uses no provider network or paid inference.

Before live customer rollout:

1. Complete native sign-in and a real synthetic draft with **each** provider.
   Record successful execution, cancellation, quota exhaustion, and native
   account funding. Revalidate CLI flags when the supported versions change.
2. Add authenticated device pairing and durable Chief job leases, tenant/owner
   binding, heartbeat, connection revocation, and job cancellation. A desktop
   worker going offline must be shown as unavailable, including on mobile.
3. Integrate drafts with the existing approval queue, revalidate invoice and
   recipient facts before delivery, and prove duplicate-send protection and
   recovery from ambiguous delivery. Do not autoapprove externally drafted work.
4. Measure coordination and tool costs; implement server-controlled edition
   mapping and billing rehearsal before exposing a Connect price or checkout.

No migration, new price, account conversion, deployment, or customer-facing
connection-success claim is included in this local preparation.

## Provider references checked 2026-09-10

- [OpenAI non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
  documents structured final output and machine-readable execution events.
- [OpenAI configuration](https://learn.chatgpt.com/docs/config-file/config-reference)
  documents sandbox, approval and tool settings. A later interactive product
  integration can use the [App Server](https://developers.openai.com/codex/app-server).
- [Claude programmatic execution](https://code.claude.com/docs/en/headless) and
  [CLI reference](https://code.claude.com/docs/en/cli-reference) document native
  execution, structured results, tools and authentication commands.
- [Claude credential and product conditions](https://code.claude.com/docs/en/legal-and-compliance)
  distinguish running the unmodified native product with end-user authentication
  from collecting subscription credentials or proxying them through an app.
  This rehearsal invokes the native product; it is not a custom subscription
  login or shared credential service. Recheck applicable conditions before launch.
