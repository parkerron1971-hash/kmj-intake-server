# Support Operations — the fix queue

**Date:** 2026-09-02
**Asked for:** "review our current support ticket process and come up with a
plan to improve operation in handling issues… set up a list and create a queue
for fixing them, so inside Solution Space we create a ticket area that is
focused on fixing the problems."
**Status:** Part 1 (the audit) and Part 2 (the plan) are below. **Phase 1 —
the backend — ships with this document.** Phases 2–4 are the two UIs and the
practitioner's side, specified here against a contract that already exists.

---

## 1. What the process actually is today

Traced end to end, not from memory:

| Step | Where it lives | What happens |
|---|---|---|
| A practitioner reports something | `HelpSupportPanel.tsx` (frontend) | POSTs a row straight into `support_tickets` via PostgREST under tenant RLS. Attaches `context`: app version, screen, theme, viewport, user agent. |
| It lands | `support_tickets` (frontend repo: `supabase/support-tickets-migration.sql`) | `category` ∈ bug/question/billing/feature/general · `status` ∈ open/in_progress/resolved · one `admin_reply` column. |
| Kevin reads it | `SupportTicketsPanel.tsx` (Mission Control) | Reads and writes the table **directly from the browser**; the `tickets_owner_all` policy (`is_platform_owner()`) is the only gate. Sorted `created_at desc`, filter chips by status. |
| Kevin replies | same panel | Writes `admin_reply` + `replied_at`. Nothing is sent. The panel's own subtitle: *"no email notification yet — fast-follow"*. |
| Chief can file one | `chief_of_staff.py:5244` `handle_queue_build_request` | A practitioner asking Chief for a change gets a `support_tickets` row, `category='feature'`, subject prefixed `BUILD:`. The owner's own businesses additionally fire a GitHub `@claude` issue. |
| Something gets fixed | `dev_tasks` + `dev_bridge.py` | The Dev Desk dispatches work: the **cloud** lane files an `@claude` issue, the **local** lane is polled by Solution Space, which opens a Claude Code session and reports back. |
| Anyone notices the load | `platform_watchdog.py:176` | Counts `status=open` tickets, warns at ≥10, and counts the "build queue" as `subject like BUILD:*`. |

### The six things wrong with it

**1. The two lists never touch.** `support_tickets` is where problems are
reported. `dev_tasks` is where problems get fixed. There is no column, no
foreign key and no code path between them. Every ticket that needs a code
change has to be read by a human and retyped into the Dev Desk, and from that
moment the ticket is orphaned — the fix ships, and the ticket still says
"open".

**2. Nothing walks back.** No mechanism moves a ticket when its fix lands, so
even a perfectly handled problem stays on the board until someone remembers it.
The board therefore stops being trustworthy, which is the point at which people
stop reading it and start working from whatever they remember.

**3. Nobody is ever told.** The reply is a column. The practitioner has to
reopen Help & Support and click *My tickets* to discover it. There is no email,
no in-app notification, no Chief message. Measured from where the practitioner
sits, reporting a problem is indistinguishable from shouting into a well.

**4. There is no priority at all.** The list is newest-first. A blocker filed
last Tuesday sits below a feature idea filed this morning. `category` is not
priority (a `bug` may be cosmetic; a `question` may be "I can't log in"), and
`status` is not progress (`in_progress` covers both "I read it" and "the fix is
in review").

**5. Repeat reports don't add up.** Ten practitioners hitting one bug produce
ten independent rows. The single most useful triage signal — *how many people
is this happening to* — is not computed anywhere.

**6. The fix queue is a string prefix.** The watchdog measures the build
backlog with `subject like 'BUILD:*'`. And `queue_build_request` files every
request as `category='feature'` whether it is a feature or a broken button, so
the one field that could have carried the distinction doesn't.

### One more, worth stating separately

Mission Control writes tickets **from the browser** under RLS. That is why
there is no notification: there is no server in the path to send one. Any
automation at all — email on reply, a dev task on dispatch, an SLA sweep —
requires the write to move server-side first. That is the prerequisite, and it
is what Phase 1 does.

---

## 2. The shape of the fix

**One queue, four lanes.** The lanes *are* the operating procedure:

```
   TRIAGE            READY             FIXING            CONFIRM
   ──────            ─────             ──────            ───────
   nobody has        decided,          a dev task        fixed, and they
   looked at it      waiting for       exists and is     still don't know
                     a session         running

   fix_state:        fix_state:        fix_state:        fix_state:
   new               triaged           queued, fixing    shipped

   → set severity    → dispatch it     → nothing; it     → reply. That
     (auto on          into a            reports its       closes it:
     arrival)          session           own progress      'answered'
```

Everything closed — `answered`, `wont_fix`, `duplicate` — leaves the board.

Three rules make the order trustworthy, and all three are in
`support_queue.py` where they can be read and argued with:

- **Severity dominates; age eventually wins.** `blocker` 1000, `high` 400,
  `normal` 120, `low` 30, plus 8 points per day of waiting, capped at 240.
  A month-old nuisance climbs past a fresh one but never displaces a real
  `high` reported this morning.
- **Repeats count.** +60 per additional business reporting the same
  `problem_key`, capped at 300.
- **Silence is a defect.** +50 while nobody has answered at all — because the
  failure practitioners actually feel is not a slow fix, it is never hearing
  back.

Every ranked row carries a `why` array (`["high", "13d old", "3 reports of
this", "never answered"]`). A queue that cannot explain its own order does not
get trusted, and an untrusted queue gets ignored in favour of scrolling the raw
list — which is the process being replaced.

### Why a separate table, not columns on the ticket

`support_tickets` is **tenant-readable**: `tickets_tenant_select` lets a
practitioner `select=*` their own rows. Operator judgement — severity, "won't
fix", the internal note explaining why something waits — must never sit on that
row. So it lives in `support_triage`: service-role only, RLS on with no
policies, the same posture as `dev_tasks` and `platform_changelog`.

### Why `fix_state` and not a wider `status`

`support_tickets.status` has a three-value CHECK, and Mission Control's panel
indexes a lookup table by it — `NEXT_STATUS[t.status].map(...)`. A row carrying
a fourth value would throw on render and blank the panel. `fix_state` is
additive: old UI never sees it, and the two never have to be migrated together.

---

## 3. Phase 1 — the backend (ships with this document)

**Migration:** `supabase/APPLY-2026-09-02-support-fix-queue.sql` — the
`support_triage` table. Apply after merge.

**Code:** `support_queue.py` (the ranking, pure and tested),
`support_router.py` (the endpoints), mounted in `kmj_intake_automation.py`.
38 tests in `__tests__/test_support_fix_queue.py`, including a parity test that
fails the build if the Python vocabulary and the SQL CHECK ever disagree.

### The contract

Owner JWT (`require_owner`), like every other Mission Control surface:

| Endpoint | What it does |
|---|---|
| `GET /platform/support/queue` | The whole ticket area in one call: `lanes` (triage/ready/fixing/confirm/closed, each ranked), `clusters` (repeat problems), `counts` (per state, plus `open_total`, `unanswered`, `oldest_open_days`, `blockers`). Reconciles and back-fills triage as it reads. |
| `POST /platform/support/tickets/{id}/triage` | `{severity, fix_state, problem_key, duplicate_of, note}` — any subset. A hand-set severity is never overwritten by the guess afterwards. |
| `POST /platform/support/tickets/{id}/dispatch` | `{lane: local\|cloud, repo, project_path, title, details}` → creates the `dev_tasks` row, links it, moves the ticket to `queued`, and flips the practitioner's own view to `in_progress`. |
| `POST /platform/support/tickets/{id}/reply` | `{text, resolve}` → writes `admin_reply` **and emails the person who filed it**. Returns `emailed` + `email_error`; the reply is saved either way, but a failed send is reported, never swallowed. |

Device token (the one Solution Space already holds):

| Endpoint | What it does |
|---|---|
| `GET /dev-bridge/tickets` | The same queue payload, no owner JWT needed. |
| `POST /dev-bridge/tickets/{id}/dispatch` | Local lane only. A device token opens a session on Kevin's machine; it must never be able to fire a cloud build, which spends the platform owner's API budget. A test enforces this. |

### What now happens without anyone doing anything

- **Triage is automatic.** Every ticket gets a severity and a `problem_key` on
  the first queue read — keyword-based, deterministic, free. The list is ranked
  on arrival instead of waiting to be curated. An operator's explicit severity
  always wins, and `triaged_by` records which one you're looking at.
- **The walk-back is automatic.** Reconciliation runs on every queue read:
  `dev_tasks.status` → `fix_state`. Task working → ticket `fixing`. Task done
  → ticket `shipped` (**not** closed — the practitioner still hasn't been
  told, and the confirm lane is what remembers that). Task failed or cancelled
  → back to `ready` with a note, because a task that died is a ticket nobody is
  working on.
- **Turning it on is safe.** Existing tickets seed into the lane their old
  status already implies, so day one does not dump months of resolved history
  into the triage lane.

---

## 4. Phase 2 — the ticket area in Solution Space

This is the piece the brief names, and the backend above is already shaped for
it: `GET /dev-bridge/tickets` returns the whole board against the device token
the app holds, and one POST turns a row into a session.

**A blocked note first:** Solution Space (`C:\Users\kmccl\claude-bench`) is a
local git repo with **no remote** on this machine. Every other change in this
system ships as a PR; this one cannot. It has to be a local commit or a patch —
Kevin's call, and it is the one open decision below.

**The screen.** A third rail item next to Projects and Saved Work — **Tickets**
— showing the four lanes as columns:

- Each card: severity dot, subject, business, age, `why` chips, and — when the
  ticket has a dev task — that task's live status.
- **Fix this** on a card in *triage* or *ready*: POST
  `/dev-bridge/tickets/{id}/dispatch` with the repo, then let the existing
  bridge do exactly what it already does for a Dev Desk task — open a session
  in the project, seed the brief, report status. The brief is already composed
  server-side and carries the practitioner's verbatim words plus their client
  context.
- The *confirm* lane is the one that pays for the whole thing: it is the list
  of people who are owed a sentence. Solution Space can't reply (that endpoint
  is owner-JWT), so the card links to Mission Control — or Phase 3 puts reply
  on the device lane behind a second confirmation.
- Poll on its own slower timer — 60s, not the bridge's 15s. The task queue is
  polled fast because a dispatched task should open now; a ticket board that
  changes a few times a day does not need four reads a minute, and each read
  costs three Supabase queries plus reconciliation. No new auth and no new
  config either way: the pairing token already in `space.json` is enough.

**Why here and not only Mission Control:** the fix happens in this window. A
ticket area anywhere else is a list you read and then retype. Here, the
distance between "this is the worst problem we have" and "a session is working
on it" is one click.

---

## 5. Phase 3 — Mission Control's panel, rebuilt

`SupportTicketsPanel.tsx` today is a flat status-filtered list that writes
straight to PostgREST. It becomes a thin client of `/platform/support/queue`:
the same four lanes, the same ranking, plus the things only the owner can do —
severity and `wont_fix`, the reply box (now actually sending), the cluster view
that merges duplicates, and the cloud lane for dispatch.

The direct-PostgREST writes go away with it. That is the point: it is what
makes every future automation possible.

**Also in this phase, both cheap:**

- `platform_watchdog` stops counting `subject like 'BUILD:*'` and starts
  reading the real numbers: `blockers`, `unanswered`, `oldest_open_days`. The
  warning that matters is not "10 open tickets", it is "somebody has been
  waiting six days for any reply at all".
- `queue_build_request` stops filing every request as `category='feature'` and
  files bugs as bugs.

---

## 6. Phase 4 — the practitioner's side

The loop only actually closes at a person.

- **Chief can answer "what happened to my ticket?"** — a read action over the
  tenant's own tickets, in plain language: *"You reported the cancel button on
  1 Sept. It's fixed as of yesterday — try it and tell me if it still misses."*
  Chief must never say builder, GitHub or Claude Code; the dispatch brief
  already ends by asking the fixing session for the one plain sentence that
  goes back.
- **A shipped fix announces itself** in the app, once, on next open.
- **The diagnostics gap.** Today a bug ticket carries app version, screen,
  theme, viewport and user agent — and nothing about what actually broke.
  Client errors go to `platform_watchdog._ERRORS`, an in-process ring buffer of
  400 entries with no `business_id`, lost on every deploy. So the errors that
  would explain the ticket are usually gone before the ticket is read. The fix
  is a small `client_errors` table (business, user, screen, message, stack,
  timestamp) and attaching that business's last few errors to the ticket at
  filing time. That is its own arc; it is the highest-value one after the UIs,
  because it decides whether "something looks wrong" is reproducible.

---

## 7. The routine this is meant to produce

Not a process document — four habits:

1. **Once a day, look at TRIAGE.** Every card already has a severity; the job
   is to correct the wrong ones. Anything not a code change gets a reply and
   leaves. Two minutes.
2. **Dispatch the top of READY.** Not the whole lane — the top. The rank is
   there so the choice is already made.
3. **Never touch FIXING.** It reports its own progress. If a card sits there
   for days, the dev task stalled, and that is a Dev Desk problem.
4. **Empty CONFIRM before starting anything new.** Every card is a person who
   reported something, waited, got it fixed, and still doesn't know. This is
   the lane that turns support from a cost into the reason someone stays.

The health of the whole thing is two numbers, both already in `counts`:
`unanswered` and `oldest_open_days`. If those two are small, support is fine no
matter what the total is.

---

## 8. The one decision needed

**Where does the ticket area live, and how does it ship?** The backend serves
both surfaces, so this is not blocking, but Solution Space has no git remote —
Phase 2 has to be a local commit or a patch rather than a PR. Options:

- **Solution Space (as briefed).** Fastest path from "worst problem" to
  "session working on it". Ships as a local commit.
- **Mission Control (Phase 3 first).** Ships as a normal PR, reachable from a
  phone, and can reply — but dispatching still means walking to the machine.
- **Both, in that order.** The contract already supports it; the second one is
  a day's work once the first exists.

Everything else in this plan is decided and specified.
