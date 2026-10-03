# Chief follow-through

Chief can report what it is handling across assignments, missions, background
jobs, errands and pending approvals. Appointment filling, invoice collection
and new-contact growth have named recipes using the existing assignment engine.
Both event and assignment planning read the current business learning profile;
a correction made during planning stops the action turn so it can prepare again.

## What is implemented

| User request | Implementation and limits |
|---|---|
| “What are you handling, and what needs me?” | `responsibility_status` native read and owner-authenticated `GET /agents/chief/responsibilities`. Real source statuses, recorded next checks, per-source read failures, held/failed work and interrupted event reviews. Reads up to 40 rows per source; a limit makes the report explicitly partial. The native result pages whole items with `next_offset`; use `source` to narrow it. |
| “Fill six appointments next week.” | `start_business_responsibility`, workflow `fill_appointments`, explicit `from`, `to`, total `count` (1–999). Reads existing bookings before saving the assignment. Target is total appointments in the range, not six additional appointments. |
| “Help collect this invoice.” | Workflow `collect_invoice`, business-owned `invoice_id`. Refuses an unavailable or already paid invoice. A reminder is not counted as payment. |
| “Help us reach ten new contacts this month.” | Workflow `grow_contacts`, explicit dates and total count. Measures actual contact rows, not drafts. |
| “I reviewed that interrupted follow-up.” | Owner-only `acknowledge_follow_up`, event ID and exact `observed_at` from a fresh report. Resolves that review only; no replay and no claim the original action succeeded. |

The frontend exposes the report through the existing Chief shortcut list on
desktop and mobile. Retry rejections are visible in the existing job indicator.
No MySite builder, voice runtime, new dashboard or external sending path is added.

## Recovery contract

`CHIEF_DURABLE_EVENTS=off` is the deployment default. When enabled, event work
claims a three-minute database lease and renews it every 30 seconds. Only a
current token can cross the action boundary or confirm completion. Preparation
can be retried at most three times, including after the event passes the normal
24-hour lookback. Exhaustion appears as a review.

The action checkpoint is written before write tools are exposed. It also stamps
the legacy event cursor so rolling the flag back cannot replay possible effects.
A crash after this point goes to review, never automatic replay. A stale worker
cannot reclaim the batch or announce completion. This is an at-most-once effect
boundary, not an exactly-once guarantee for external providers: an in-flight
request may finish even after the worker loses its lease. Review the actual
records before starting replacement work.

Generic retries atomically claim only failed jobs. Builds and connected-agent
work keep their existing continuation doors; errands require supplier review.
This change does not replace every job runner with the event delivery engine.
Existing assignment cadence, budgets, permissions and approval gates remain in
force. Creating a goal never turns on unattended work or authorizes a send,
charge or booking. Stopping a goal uses the existing `stop_assignment` action.

## Corrections and outcome evidence

Background work reads `business_learning` fresh before planning and again before
acting. A failed profile read blocks that attempt. Owner facts retain their
evidence labels; assumptions and research do not grant authority. Remembering a
calendar correction does not establish that the calendar was edited. The model
is directed to check the affected records; existing action gates still apply.

Progress comes from business records. Failed reads, missing invoices and a
possibly truncated 1,000-row measurement preserve the previous measurement and
schedule another check. They do not turn into zero. Reports distinguish observed
business growth from work Chief caused. Historical data, provider delivery or
causal revenue attribution are not invented by these workflows.

## Deployment and verification

Production schema status: **applied 2026-10-03 20:43 UTC**, explicitly authorized
by Kevin after the draft was prepared. A live rollback rehearsal and post-commit
privilege/schema checks passed; see [receipt](CHIEF_EVENT_MIGRATION_VERIFICATION.json).
Backend #1239 and frontend #1120 are merged and deployed. Recovery is enabled
on both Railway services; their runtime functions report event processing and
durable recovery on, with healthy readiness and scheduler lease. The signed-in
desktop report passed; the phone-specific shortcut correction is frontend
#1122. See [release receipt](CHIEF_FOLLOW_THROUGH_RELEASE.json). The sequence
below is retained for other environments and future rollouts.

1. Merge/deploy the backend with `CHIEF_DURABLE_EVENTS=off`.
2. Apply `supabase/APPLY-2026-10-03-chief-event-delivery.sql` in the shared
   Supabase database. The script is repeatable, grants RPC access only to the
   service role, and reloads the PostgREST schema. Existing `events` and
   `events.agent_handled_at` must already exist.
3. Pause the Chief event scheduler (`CHIEF_AGENT=off`) and drain old event runs.
   Deploy the same version to web and scheduler. Enable `CHIEF_DURABLE_EVENTS`
   on both, then restore the prior `CHIEF_AGENT` setting. Do not mix legacy and
   durable workers over the same queue. Existing business opt-ins still apply.
4. Deploy the paired frontend after the backend read/action handlers exist.
5. In a dedicated opted-in fixture business, verify an idle event completes,
   an expired planning lease retries, and an interrupted acting lease appears
   in the report and cannot replay. Acknowledge only after checking fixture
   records. Never run a destructive rehearsal on a customer's real work.
6. Verify all five base sources load for an owner, cross-business requests are
   denied, and the shortcut appears in desktop and mobile Chief.

```sql
select to_regclass('public.chief_event_deliveries');
select phase, count(*) from public.chief_event_deliveries group by phase;
select has_table_privilege('authenticated','public.chief_event_deliveries','select'); -- false
select has_function_privilege('anon','public.chief_event_claim(uuid,text[],uuid)','execute'); -- false
```

Rollback: drain workers, switch `CHIEF_DURABLE_EVENTS=off` consistently, and
restart. Keep the table and review records; do not clear handled cursors or
replay historical events. Resolve outstanding reviews before disabling their
report source. The additive schema can remain in place.

## Verification in this change

Offline Python checks cover event interruption, stale leases, owner isolation,
bounded reports, correction refresh, all three recipes, missing measurements,
and competing retries, alongside existing agent/assignment/build/policy tests.
`node scripts/chief-event-delivery-db-check.mjs` exercises the real SQL in
PGlite: repeat application, tenant and browser isolation, atomic batches,
expired leases, bounded retries, legacy rollback fences, acknowledgement and
completion. It is included in CI. Set `PGLITE_MODULE` to an installed PGlite
module path when running locally. No live customer actions are needed.
