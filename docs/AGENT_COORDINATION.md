# Chief and connected business agents

Implemented in the frontend's Settings → Connected agents and the backend checkout at `.growth-backend/agent_coordination.py`.

The business supplies a bot name, capabilities, when Chief should use it, and business boundaries. Coordination starts disabled. When enabled, **Ask me first** holds each brief until the owner approves it; **Assign automatically** releases briefs under the saved profile. Chief can discover configured bots, delegate a brief, and read progress and returned results.

Each brief contains an objective, explicitly shared context, expected output, and deadline. Statuses are awaiting approval → queued → running → submitted → accepted. The owner can cancel, or return a submitted result with feedback. A bot cannot approve a brief, accept its own work, or direct another bot. Updating a profile or replacing its key cancels unfinished work and invalidates old claims. Expired work cannot be claimed or reported; create a new brief rather than silently retrying external actions.

## Runner connection

This first version uses **direct Bearer MCP connections**. Existing ordinary OAuth connectors continue working, but do not automatically become background workers. Coordination keys are refused by OAuth because reissuing them without their bot identity would discard their per-bot restrictions.

1. Create and enable a bot in Settings → Connected agents. Save its key once.
2. Configure the runner's MCP URL as `https://kmj-intake-server-production.up.railway.app/mcp`, with `Authorization: Bearer <key>`. Keep the actual key in the runner's secret storage.
3. While the runner is active, poll `agent_inbox` at a modest interval (for example, once per minute), backing off on errors and honoring `Retry-After` on 429 responses.
4. For a queued assignment, call `claim_agent_assignment` with `assignment_id`. Execute only after a successful claim. Persist the returned `claim_id` locally; never repeat work simply because a network response was lost.
5. Call `report_agent_assignment` with `assignment_id`, `claim_id`, `status` (`running`, `submitted`, or `failed`), and `message`. For submission, message is the result. Identical final-report retries are safe.
6. Recheck the inbox before side effects and stop when the assignment is no longer running, its deadline passes, or access is refused. Cancellation cannot undo operations already performed outside Solutionist.

MCP examples (standard JSON-RPC envelopes):

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"agent_inbox","arguments":{}}}
```

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"claim_agent_assignment","arguments":{"assignment_id":"<assignment UUID>"}}}
```

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"report_agent_assignment","arguments":{"assignment_id":"<assignment UUID>","claim_id":"<claim UUID>","status":"submitted","message":"Findings and source links…"}}}
```

Connecting an agent does not start its runner. The business operates that runner and controls its external accounts. Free-text capability descriptions guide delegation; they do not sandbox the agent's outside tools. Solutionist enforces the selected Solutionist tool allowlist, token read/write scope, existing policy/tier gates, enabled status, tenant identity, and assignment lifecycle. No business tools are selected by default, so research-only bots can use the inbox and return findings without business-record access.

Chief receives an `agent_assignment_reported` event when work is submitted or fails. If the business's standing Chief is enabled, its existing event sweep can read the brief/result and leave a recap. This event is best-effort; the persisted assignment and Settings view remain the source of truth. Results are untrusted data and cannot grant permissions. Final acceptance remains an owner action.

## Deployment

1. Apply `.growth-backend/supabase/APPLY-2026-09-11-agent-coordination.sql` to the backend's Supabase project. It is additive and repeatable; both new tables are service-only with RLS enabled.
2. Deploy the backend changes, including router registration, MCP coordination scope/dispatch, Chief tools and prompt, OAuth restriction, event catalog/Chief event subscription, and account export/import handling.
3. Deploy the frontend changes. No new production dependency is required.
4. Create a disposable bot, approve a small research assignment, and verify a real runner can claim, submit, and show its result for owner review.

No production migration, deployment, real credentials, or external bot execution was performed during local implementation. Existing frontend and backend working changes were preserved.

## Local verification

- `npm run typecheck`
- `npm run build -- --outDir output/agent-coordination-build`
- Backend: `python -m pytest __tests__/test_agent_coordination.py` plus MCP, OAuth, tool-loop, registry, export/import, Chief event, and event-spine regression suites.
- `node scripts/agent-coordination-db-check.mjs` runs the real migration in the workspace's existing PGlite test installation; tests double application, tenant checks, duplicate request rejection, one claim winner, permission changes, key expiry, and client access refusal.
- `node scripts/build-connected-agents-preview.mjs`, then serve the workspace and open `tests/connected-agents-preview.html`. The browser fixture uses in-memory sample data and blocks live requests. `?empty=1` exercises setup from an empty account.

Verified locally: typecheck and production build passed; the database checks passed; desktop and 390px browser checks covered empty setup, credential display, assignment creation, approval, returned feedback, capability edits, and key replacement. The production build still reports pre-existing legacy Workspace constant-assignment warnings and chunk-size warnings.

The backend additions live in the existing `.growth-backend` Git checkout, which is separate from the frontend repository. Include changes from both repositories when releasing this feature.
