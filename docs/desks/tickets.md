# Desk: tickets

## 1. What it owns

The front door for problems. A pastor or practitioner presses Help → Contact (or reports a Chief
reply, or Chief files a request for them) and a ticket appears in Mission Control → Support
Tickets. They see a badge on their ticket: Received, Someone's looking, Being worked on,
Fixed (try it), Answered. They get an email when someone answers.

This desk reads tickets, finds out what actually happened (with evidence), writes down which
desk owns the fix, and hands it off. **It does not fix code itself.** Its output is a diagnosis
and a hand-off note, and sometimes a draft answer for the owner to send.

## 2. Where the code is

Backend (`kmj-intake-server`):
- `support_router.py`: the fix queue: triage, dispatch, walk back, tell them.
  - Owner-only (`require_owner`): `GET /platform/support/queue`, `POST
    /platform/support/tickets/{id}/triage`, `.../{id}/dispatch` (turns a ticket into a
    `dev_tasks` row), `.../{id}/reply` (writes the answer AND emails it).
  - The practitioner's side: `POST /support/tickets/{id}/messages` (`require_user` plus
    `_require_ticket_owner`, which returns 404 to strangers).
  - Solution Space (device token, `dev_bridge._require_device`): `GET /dev-bridge/tickets`,
    `POST /dev-bridge/tickets/{id}/dispatch` (local lane only, never the cloud builder).
  - `note_fix_shipped`: a finished dev task tells its ticket in plain words.
- `support_queue.py`: pure ranking. `FIX_STATES` (new, triaged, queued, fixing, shipped,
  answered, wont_fix, duplicate); severity first, age eventually wins, repeats across
  businesses count, unanswered tickets carry weight.
- `support_thread.py`: the practitioner's five stages (`STAGE_OF_FIX_STATE`) and
  `practitioner_safe()`, the guard against builder/GitHub/AI words.
- `support_drafts.py`: the Support desk agent (`support_desk` in
  `platform_console.AGENT_REGISTRY`; run now: `POST /agents/support-desk/run`). Drafts a reply
  for every ticket waiting on one, at most `MAX_PER_TICK` a pass, and skips when spend_guard
  says the platform is over budget. Kill switch `SUPPORT_DRAFTS=off`. **It never sends.**
- Ticket writers besides the app:
  - `chief_of_staff.handle_queue_build_request`: a non-owner's build request becomes a ticket
    ("feature request sent to the team").
  - `chief_reply_report.py`: Report on a Chief reply. `context.kind = chief_reply_report`;
    "offensive or harmful" triages high; no problem key.
  - `church_move_in.py`, `church_billing.py`: a church's move requests and move-in.
- Who else reads tickets: `platform_today.py` (Today's queue), `platform_watchdog.py` (counts
  open ones), `ops_desk.py`. Covered by export/delete in `account_lifecycle.py`.
- Tables: `support_tickets` (tenant-readable; RLS lets a business insert and read its own),
  `support_triage` (operator-only: fix_state, severity, problem key, draft fields,
  `first_response_at`), `support_ticket_messages` (tenant-readable thread), `dev_tasks`.
  Migrations: `supabase/APPLY-2026-09-02-support-fix-queue.sql`,
  `APPLY-2026-09-02-support-thread.sql`, `APPLY-2026-10-02-support-drafts.sql`.
- Evidence tools: `.github/workflows/oncall.yml` (diagnosis only, never acts),
  `uptime.yml`, `scripts/oncall_sentry_evidence.py`, `docs/RUNBOOK.md` ("Something is down").

Frontend (`solutionist-studio`):
- `src/core/components/HelpSupportPanel.tsx` (Contact: inserts into `support_tickets` with
  `supabaseQuery`), `TicketConversation.tsx` (the thread), `ChiefReplyReport.tsx`,
  `church/findway/HelpCenter.tsx` (a church's Help Center lists its tickets).
- Mission Control: `src/modules/platform/pages/SupportTicketsPanel.tsx` (id `platform-support`),
  `TodayPanel.tsx`, `DevDeskPanel.tsx`.
- Solution Space (`C:\Users\kmccl\claude-bench`, local only, no remote): `electron/bridge.js`
  reads `/dev-bridge/tickets`.

## 3. Rules that must not break

- Diagnose; don't fix. No code edits, branches or migrations from this desk. A fix goes to the
  owning desk through a hand-off note, or to the owner as a Dev Desk dispatch.
- Nothing internal in anything the customer can read. `support_tickets` and
  `support_ticket_messages` are tenant-readable. That means no PR numbers, repo names,
  "Claude", "GitHub", "builder", file paths, other businesses' names or figures, and no
  "AI agent". `practitioner_safe` only guards `system` messages and drafts. An operator's typed
  reply is not checked by the server, so write it in plain words.
- Drafts never send. A person reads the draft in Mission Control → Support, edits it and presses
  Send. Send goes through `/reply`, which writes to the ticket and emails the customer.
- Read-only on production. Investigate with SELECTs (service role, from a `railway run` scratch
  script or the SQL editor) and `railway logs`. Never PATCH a customer row to "see if it works".
- Live evals or repro runs against Chief bill the production AI account. Say the cost first.
- Privacy in hand-offs: refer to the business by id and a role ("the treasurer"), not a person's
  name or contact details. Never paste tokens, card or bank data.

## 4. Traps already hit

- On-call confidently misdiagnosed a probe of a fake URL as a deploy restart. It couldn't see the
  probed URL, and its own curl was refused. Gather evidence with plain code first, and read the
  real status code before trusting any diagnosis (yours included).
- A probe that returns '' from Chief's reviewer may be a billing 400 (credits ran out), not a bug.
- "Chief can't find X" is often a soft-failing read: a 400 from `_gather_context` (a `+00:00`
  timestamp, a quoted `eq."value"`). Grep the logs for `: 400 ` before blaming the model.
- A withheld "couldn't verify" count is often the list's row limit, not a check bug.
- "Nothing was recorded" can be an RLS-refused write that returned None. Check the table's
  policies in `supabase/APPLY-*.sql`.
- `logging` never reaches Railway; only `print()` lines and the HTTP log do.
  `railway logs --http --filter '@path:/x'` gives each call's status and ms, and the timing
  rhythm of the calls points to the client code behind them.
- Several web replicas: "it worked on retry" can mean a different replica, not a fix.
- Old tickets: the panel used to email nobody. Check `replied_at` and `support_ticket_messages`
  before assuming a customer was told.
- A test failing only in CI with DNS errors is an env leak from another test file, not a flake.

## 5. How to check work

Diagnosis checklist:
1. Read the ticket, its `context` (`kind`, surface, conversation id), the thread, and the triage
   row. Note the business id, plan, and who asked (owner or an office login).
2. Find the time window. Pull `railway logs --since/--until` around it and the HTTP log for the
   paths involved. Note real status codes.
3. Check Sentry for the window (`scripts/oncall_sentry_evidence.py` shows the shape).
4. Read the rows: `audit_log` (actor, verb, ok, error), `chief_activity`, `api_usage` by
   turn_id, the domain table. SELECT only.
5. Reproduce in a preview harness or a local test if you can, without touching the customer's data.
6. Check `worklog/` in both repos and open PRs: is this known, already fixed, or behind a
   switch that's off?
7. Write the hand-off. If it is a question rather than a bug, leave a draft answer for the owner.

Tests for this desk's own code (when another desk changes it):
`pytest -q __tests__/test_support_fix_queue.py __tests__/test_support_thread.py
__tests__/test_support_drafts.py __tests__/test_chief_reply_report.py
__tests__/test_oncall_sentry_evidence.py __tests__/test_watchdog_incidents.py`.

Hand-off note template (to the owning desk's worker, or as the dispatch details):

```
Ticket: <id>   Business: <id> (<plan>, church|practitioner)   Asked by: owner | <role>
Desk: member-app | church-office | chief | websites | money | messaging | live-media | system
What they saw: <their words, short>
What happened: <the cause, one or two sentences>
Evidence: <log lines with timestamps + status codes, Sentry issue, row ids, query used>
Confidence: confirmed (reproduced) | likely (evidence points one way) | unknown
Suspect code: <file:function>, why
Not the cause: <what you ruled out>
Customer told: nothing yet | draft waiting | answered <date>
```

## 6. Edges

- Hands to every other desk. Pick one by where the fix lands, not where the symptom shows.
  "Chief said the wrong giving total" goes to `money` if the read is wrong, `chief` if the read
  is right but the reply misstates it.
- `system` owns `support_router`'s auth, the Dev Desk (`dev_bridge.py`), the watchdog,
  on-call and the migrations behind these tables. A change to the queue's code is a `system`
  job.
- `chief` owns the build bridge's wording and `chief_reply_report.py`. This desk reads what
  they produce.
- `messaging` owns `email_sender.send_via_resend`, the path a reply's email takes. A "they never
  got our answer" ticket goes there.
