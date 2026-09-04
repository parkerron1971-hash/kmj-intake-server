# The agent connector — a practitioner's own AI, operating their business through Solutionist

**Status:** Stage 4 shipped 2026-09-03 (`mcp_server.py`, `mcp_tokens.py`, `mcp_oauth.py`).
Strategy: `future_architecture.md` §3 (MCP in both directions), the frontend's
`PERSONAL_AGENT_ARCHITECTURE.md` §10 Stage 4. Stage 1 (2026-07-28) was read-only
and owner-only; this is the door it reserved.

## What it is

An MCP (Model Context Protocol) server at `https://kmj-intake-server-production.up.railway.app/mcp`.
Any MCP client — Claude.ai custom connectors, ChatGPT apps, Claude Desktop, Claude Code,
a self-hosted agent — connects with OAuth 2.1 or a pasted key and gets tools over
**one business**: the one whose owner minted the key. There is no parameter for a
business id anywhere on the wire; a cross-tenant request is unrepresentable, not blocked.

## Two scopes

| Scope | What the connected agent can do | What decides it |
|---|---|---|
| `read` | Every read verb the action registry marks agent-exposable (30 on 2026-09-03): catch up, contacts, revenue, availability, modules, forms, texting and email setup, inventory, missions… | `action_registry.may_expose_to_agent(verb)` |
| `write` | The **class A** verbs that also have a reviewed schema in `mcp_server.WRITE_TOOL_SCHEMAS` (28 on 2026-09-03; 55 after batch 2 on 2026-09-04, adding goals, projects, booking configuration, testimonials, policies, email templates, read-marks, scheduled cancels, draft saves, contact health, owner notifications, time write-offs, prepaid balances, texting switches, template clauses and bookkeeping-proposal rejections): contacts, notes, activities, tasks, projects, time, expenses, sessions on the practitioner's own calendar, availability, module rows, offerings, email *drafts*, memories, notes, content plans, FAQ, and `undo_last`. | registry ceiling ∩ schema floor |

Never, at any scope: **class C** (anything that sends, charges, refunds, posts publicly,
hard-deletes, moves money, or starts a mission), sensitive reads (giving records, the
ledger), bulk verbs, UI verbs, and verbs that spend model tokens from an outside caller.
A refusal for those says "not available" — never "needs a scope" — so a refusal is not a hint.

`write` always carries `read`. A key minted with `write` grants both; a key minted
read-only grants only read, whatever the client asks for at consent.

## How a practitioner connects

1. **Settings → Agent Access** in the app: mint a key, name it ("my ChatGPT"), choose
   read-only or read + write. The key is shown once.
2. In Claude.ai: *Settings → Connectors → Add custom connector*, paste the `/mcp` URL.
   Claude registers itself (RFC 7591), sends the practitioner to our consent page, they
   paste the key, approve. Claude holds an ordinary `mcp_tokens` credential from then on
   — same row, same revoke button, refreshes itself at 90 days.
3. In ChatGPT: the same MCP + OAuth flow through its connector/apps settings.
4. Claude Desktop / Claude Code / anything with a config file: paste the key as a bearer
   token directly. No OAuth needed.

Revoke in Agent Access; it stops working on the next call, and kills the refresh chain.

## What every call goes through, in order

1. Scoped token verified (HMAC, expiry, then the revocation row — fails closed).
2. Subscription lock (dormant behind `BILLING_ENFORCE`).
3. Rate limit, `mcp` bucket, **fails closed** (`RL_MCP_PER_MIN`).
4. Registry: could any scope reach this verb? If not, flat refusal.
5. Scope: does THIS key carry `write` if the verb writes?
6. Tier gate: `agent_connector` is a Professional feature (dormant, fails open — an
   entitlement gate, not a security gate).
7. `policy_engine.evaluate(surface="agent", prompted=False)` — an agent's call is
   unattended. So a business that **paused automations** pauses its agent; a regulated
   practice's client-facing switch is honoured; bulk is refused.
8. The handler, called directly (never through `_execute_actions`, so the unknown-verb
   remapper is not on the path).
9. On a successful write: `chief_undo_log` row, exactly as a chat action — `undo_last`
   and `what_undo` see it.
10. Audit: `agent_runs` (argument **names**, never values) and the action ledger
    (`actor_type='agent'`, the policy reason as `authorized_by`).

## Operating it

- **Kill switch:** `MCP_ENABLED=off` — the surface and the OAuth endpoints answer 503.
- **Rotate every agent key at once:** change `MCP_TOKEN_SECRET`. (If it is unset the
  surface falls back to `CUSTOMER_TOKEN_SECRET`, and rotating that also breaks booking
  links — set the dedicated one.)
- **See what agents did:** `agent_runs` (Mission Control → Agent Access reads it), and
  the ledger. Refusals are rows too; those are the ones worth reading.
- **Widen the write surface:** read the handler, add a `WRITE_TOOL_SCHEMAS` entry whose
  argument names are the ones the handler reads, bump the count in
  `__tests__/test_mcp_writes.py`. The registry must already say class A, non-bulk,
  non-sensitive; if it does not, the schema alone does nothing.

## What is deliberately not here yet

- **Class B.** The registry defines it as a send with a recall window and there is no
  outbox, so nothing is class B and no scope exists for it. The day a 60-second delayed
  send exists, outbound drafts become the first candidates.
- **Per-category scopes** (`manage_schedule`, `manage_tasks`…) from
  `extensibility_and_autonomy.md` §2.2. `read` / `write` is the honest v1: the registry
  has no category axis yet, and a scope vocabulary the registry cannot enforce is a
  promise.
- **Trust Track graduation unlocking scopes automatically.** The data accumulates; the
  grant is still a human click. That is the on-ramp the July spec asked for.
