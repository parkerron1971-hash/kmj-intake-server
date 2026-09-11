# Connected AI pilot: implementation and release

Solutionist keeps one workspace and two eventual AI funding arrangements. This
change connects customer-device Claude/ChatGPT execution to the existing Chief
job and approval records. It does not introduce edition prices or change billing.

## Implemented scope

- Owner-only Settings → Connect your AI, paired with the frontend change.
- ChatGPT through native Codex; Claude through native Claude Code. Native sign-in
  is handled by those programs in separate local state directories. Provider
  credentials are never read or uploaded by Solutionist.
- Ten-minute, single-use pairing codes. Only their hashes reach the database.
  Device bearer secrets expire after 90 days, are independently revocable, and
  are protected with the current Windows user's DPAPI (POSIX permissions 0600).
- Foreground desktop companion with heartbeat, bounded draft execution,
  cancellation and reconnect polling. Closing its window stops local work.
- One active connected task per business. An overdue invoice is resolved to an
  existing same-business contact. Only six required drafting facts reach the
  provider; recipient addresses and send authority stay on the server.
- Completion creates an ordinary `follow_up` draft in `agent_queue`, linked to
  `chief_jobs`. Review edits and sending are claimed atomically. Both the new
  review screen and existing authenticated approval endpoint use that claim.
  Chief conversational approvals and automatic approval do not supply its
  explicit owner-review identity and cannot send these drafts.
- Invoice/contact snapshot checks at lease, completion and approval; recipient
  address checked again immediately before the existing email sender runs.
- One send attempt per job. A failed, timed-out, or interrupted delivery becomes
  `unknown` and cannot be automatically retried. Check sent mail/provider logs
  before a human resolves it. The pilot also refuses another follow-up for an
  invoice already sent or with uncertain delivery; repeated reminder campaigns
  are outside this release.

The launch companion is a Python 3.11+ ZIP, not a packaged desktop installer.
Windows users extract it and open `Start Solutionist.cmd`; macOS/Linux users run
`python3 -m connected_agents.companion`. The native provider executable must be
installed. Provider subscription allowances are not independently verified.
Successful native authentication does not promise unlimited or always-on usage.

## Release order

1. Keep `CONNECTED_AI_ENABLED=off` while merging/deploying the reviewed backend.
2. Kevin applies `supabase/APPLY-2026-09-11-connected-ai.sql` manually after merge,
   following the repository migration rule. Prerequisites: invoices, contacts,
   agent_queue, chief_jobs and the September 9 invoice-archive migration.
3. Verify the schema/functions and grants using the read-only queries below.
4. Deploy the frontend. The page displays an unavailable notice until enabled.
5. Set `CONNECTED_AI_PILOT_BUSINESSES` to explicitly approved business UUIDs and
   `CONNECTED_AI_ENABLED=on`. Existing `agent_connector_write` entitlement is
   still required. No editable business setting grants eligibility.
6. In an approved test business, pair each native provider, prepare a test invoice
   draft, change an invoice to demonstrate stale rejection, cancel/revoke work,
   and explicitly approve a delivery to an authorized test recipient. Verify
   actual receipt and repeated approval rejection. Do not send customer messages
   as a smoke test. Record native provider versions and funding behavior.

Claude's previous native rehearsal hit its weekly account limit. Its successful
live draft is still a release check. ChatGPT's earlier synthetic native run
passed. Neither provider has completed this new deployed end-to-end workflow yet.

The kill switch stops new pairing, heartbeat, execution and approval. The worker
terminates active native work when authorization fails; owner disconnect/cancel
remain available. A delivery already claimed cannot be recalled. Keep schema and
job history on rollback; do not delete uncertain-delivery markers.

```sql
SELECT to_regclass('public.connected_ai_devices'),
       to_regclass('public.connected_ai_pairings');
SELECT proname, prosecdef, proacl FROM pg_proc
 WHERE proname IN ('connected_ai_transition','connected_ai_invoice_snapshot');
SELECT relname, relrowsecurity FROM pg_class
 WHERE relname IN ('connected_ai_devices','connected_ai_pairings');
SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants
 WHERE table_name IN ('connected_ai_devices','connected_ai_pairings')
   AND grantee IN ('anon','authenticated'); -- zero rows
SELECT has_function_privilege('authenticated',
 'public.connected_ai_transition(text,uuid,uuid,jsonb)','EXECUTE'); -- false
```

## Validation

`__tests__/test_connected_ai.py` checks HTTP owner boundaries, server-controlled
eligibility, hashed pairing, token expiration/owner transfer, structured output,
single-claim send ordering, ambiguous delivery, the shared sender guard, ZIP
contents, local credential encryption and cancellation of a native task.
Existing adapter, service-profile, approval and Chief job tests also run.

```powershell
python -m pytest __tests__/test_connected_ai.py __tests__/test_connected_agents.py __tests__/test_service_profile.py __tests__/test_approvals_router.py __tests__/test_chief_jobs_enqueue.py --basetemp=output/connected-ai-test -q
```

Windows DPAPI round-trip requires the ordinary Windows user profile; a restricted
automation sandbox may lack that profile. It passed outside that restriction
using a dummy token, without reading existing credentials.

The shipped SQL runs in PGlite's PostgreSQL engine against synthetic tables with
the existing queue constraints. The test applies the migration twice and checks
pairing replay/expiry, ownership, redacted leases, idempotency, stale snapshots,
revocation, cancellation, expired leases, provider limits, duplicate send and
crash recovery. This is a **single-connection** test, not a cross-process race
test or a substitute for the live grant checks. Transitions use a PostgreSQL
transaction advisory lock per business and uniqueness constraints.

```powershell
npm install --prefix output/sql-test --no-audit --no-fund --ignore-scripts @electric-sql/pglite
node __tests__/connected_ai_database.mjs output/sql-test/node_modules/@electric-sql/pglite/dist/index.js
```

External email delivery cannot share a database transaction. Durable claims
prevent a second attempt, at the cost of holding ambiguous outcomes for review.
Invoice edits after the final approval snapshot are not transactionally locked
through the external email request. Do not describe this as exactly-once delivery.

`service_profile.external_agent.in_app_delegation_supported` continues to describe
the external MCP transport, not this companion. `/connected-ai/status` is the
authoritative runtime availability for this feature. Existing Chief-paid work
and plan pricing remain as before; this pilot has no paid fallback.

Provider references: [Codex authentication](https://learn.chatgpt.com/docs/auth),
[noninteractive execution](https://learn.chatgpt.com/docs/non-interactive-mode),
and [Claude programmatic execution](https://code.claude.com/docs/en/headless).
