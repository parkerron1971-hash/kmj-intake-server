# Operations — how Solutionist runs while it's Kevin and the agents

Kevin, 2026-10-15: *"Make my operation easy. Create a structure that allows me
to maximize my time building without becoming overwhelmed … a task list that
can connect to calendar on my phone … a path for KAI … turn what you found
into a system for myself."*

This is that system. It comes from the team plan
(https://claude.ai/artifact/1aZ4dpUZVvknD8V2bUCSwN), which has the why: agents
made building cheap, they didn't make owning cheap, and one person holds every
job. The code is `ops_desk.py`. The screen is **Mission Control → Build →
Plan**, with a "Your day" band on **Today**.

## The lanes

Every piece of work sits in one lane.

| Lane | Limit | What goes here |
|---|---|---|
| **Fix** | none, always first | Anything a customer, Sentry or an agent found broken. Fixes merge any day. |
| **Build** | **two at a time** | New features. One leaves Build only when it's live, switched on, used by a real customer and on the scorecard. |
| **Try** | none | Ideas, prototypes, proposals. Nothing in Try merges to main. |
| **Ops** | none | Chores that keep the company running: setup, decisions, hiring, cleanup. |

**The door into Build.** A task enters Build only with five answers: who asked
for it (a real customer or a measured problem), who owns it when it breaks at
night, what it costs a month to run, what switches it off, and what waits
because of it. The server refuses a third Build item (409) and a Build item
without its answers (422). Kevin can change anything else freely.

**The other rules.**
- Anything built and switched off gets a decide-by date 30 days out, as a
  `switch` task. On that date it's switched on or taken out.
- At most three build sessions at a time, each on a named lane item.
- Features switch on on Thursdays. Fixes merge whenever they're ready.
- The last full week of the month is the quiet week: fixes, deletions and docs.
- Until 100 paying businesses, Build items come from customers or measurements.
  Ideas go to Try first.

**For build sessions (Claude Code, Codex, KAI's workers):** before starting a
feature, check it's in the Build lane on Plan. If it isn't, ask Kevin or file it
in Try. A fix needs no slot.

## Kevin's week

The rhythm is computed, not stored. Kevin can move any of it (`PUT
/platform/ops/settings`, rhythm overrides). Times are Kevin's local time
(America/New_York by default) and follow the clock changes.

| When | What | Length |
|---|---|---|
| Weekdays 7:30 AM | **Morning queue.** Mission Control → Today on the phone: KAI's note, then approve, send, decide. | 20 min |
| Tue + Thu 9 AM | **Build block.** Brief the sessions on the two Build items, check what landed, merge what's green. | 3 h |
| Thu noon | **Release.** Switch on what's finished; the release editor writes What's New. | 15 min |
| Fri 3 PM | **Scorecard.** Read it, log your hours, pick what moves from Try into Build. | 30 min |
| First Monday | **Close the month** (bookkeeping, the money auditor's month). | 45 min |
| First Friday | **Check the agents.** Read ten outputs from each; retire one you keep overriding. | 30 min |
| Last full week | **Quiet week.** Build blocks become Fix blocks; no release. | — |

Weekends are off. Only four things should ring the phone: an outage, payments
or giving failing, data or security, a safety report. Everything else waits for
the morning queue (the Dev Desk alert quiet hours already hold the rest).

## The calendar on the phone

**Plan → Put it on my phone** gives a private link to an `.ics` feed of the
rhythm and every open task Kevin holds that has a date:
- a task with a start time is a block;
- a dated task is an all-day "Due:" reminder;
- a late task shows on today as "Past due:" so it can't slip into the past.

- **iPhone:** tap the webcal link, then Subscribe.
- **Google/Android:** calendar.google.com → Other calendars → From URL.

Phone calendars refresh subscriptions on their own clock (about hourly to a few
hours).

The link is `HKDF(CUSTOMER_TOKEN_SECRET, "ops-calendar", owner|version)`, so no
secret is stored. **Make a new link** bumps the version, and the old link stops
working at once. The feed is public by necessity (calendars can't sign in), so
it's read-only, carries no customer data beyond Kevin's own task titles, and
answers 404 to anything but the current link.

## The scorecard

Measured, never typed in, except Kevin's hours. A source that fails reads
"couldn't read", never zero. It covers:
- Today items waiting more than a day;
- support tickets and the oldest one's age;
- phone alerts between 10 PM and 7 AM;
- Chief's error rate (from Chief quality);
- AI spend at this week's pace against MRR;
- Build slots in use and anything parked there three weeks;
- switches left off;
- Kevin's late tasks;
- open PRs in both repos;
- paying businesses and the week's change;
- Kevin's hours.

It also shows the **first hire's signals**. Move when any two hold for two
weeks:
- tickets average 5+ a day;
- queue items wait more than a day on 3 days in a week;
- about 25 paying businesses;
- more than 5 hours a week answering customers. This one only Kevin can say.

**The Scope keeper** (agent, daily 10:30 UTC, before the morning queue):
- snapshots the scorecard into `platform_ops_settings.history`;
- writes a `platform_agent_runs` row every pass;
- flags on Today:
  - a Build item parked 21+ days;
  - a switch past its decide-by date;
  - two hiring signals held for two weeks.

It never moves anything. Run it now from Systems → Agents.

## KAI's seat until the first hire

KAI is the orchestrator in Solution Space (`claude-bench/electron/kai-orchestrator.md`).
Until someone is hired, it holds the routine half of every seat. Kevin keeps the
decisions.

**What it does every day (Level 1: prepare and watch).** Solution Space polls
`/dev-bridge/ops/moments` and hands KAI each prompt as it comes due:

- **Morning prep** (30 min before the queue): read the brief, clear what needs
  no one (CI on its workers, branches that only need updating, its own tasks),
  file what it found, and write **KAI's note** on Today in three lines: what
  needs Kevin, what it handled, what it's watching.
- **Block prep** (20 min before a build block): where each Build item stands
  (branches, PRs, CI), the first move on each, and the best Try candidate if a
  slot is open.
- **Scorecard prep** (30 min before Friday's read): the number that moved most,
  any rule being broken, what should enter Build next, what KAI handled.

Its tools: `ops_brief` (reads the desk), `ops_task` (files or updates Fix, Try
and Ops tasks; at most 20 a day), `ops_note` (Today's note). The server enforces
the lines it can't cross:
- KAI never moves work into or out of Build;
- KAI only changes tasks it holds or filed;
- KAI's notes and tasks pass through `dev_redact`.

**The path up.** Each step is earned by the step before going well, and each one
is a change Kevin makes in Solution Space → Settings → Charter, never one KAI
can make:

| Level | KAI may | Earned by | Charter change |
|---|---|---|---|
| 1 · Prepare and watch | Read everything, file tasks, write the note, keep its own workers' CI green | (now) | none: `read`, `check-repo`, `report-desk` already allow |
| 2 · Run the Fix lane | Open a worker on a Fix item it filed, get it to a green, reviewed PR (reviewed by the other agent) | Two weeks of morning notes Kevin found useful | `open-worker`, `commit`, `push-branch`, `open-pr` → allow, as a standing order for Fix work |
| 3 · Ship routine fixes | Put a green, reviewed Fix PR in the merge lane; Kevin's one click (desktop or phone) merges it | A month of Level 2 PRs Kevin merged without changes | `merge-protected` stays **ask** (one click). Never allow for money, data or safety code. |

Always Kevin's, at every level: what enters Build, pricing, money going out,
anything a customer sees (`send-outside` is locked to never), database changes,
deploy settings, and saying no.

## Endpoints

Owner (`require_owner`):
- `GET /platform/ops`
- `POST /platform/ops/tasks`
- `PATCH /platform/ops/tasks/{id}`
- `PUT /platform/ops/settings`
- `POST /platform/ops/hours`
- `GET /platform/ops/calendar`
- `POST /platform/ops/calendar/rotate`
- `POST /platform/agents/scope-keeper/run`

Device (the paired Solution Space's token):
- `GET /dev-bridge/ops/brief`
- `POST /dev-bridge/ops/tasks`
- `PATCH /dev-bridge/ops/tasks/{id}`
- `POST /dev-bridge/ops/note`
- `GET /dev-bridge/ops/moments`
- `POST /dev-bridge/ops/moments/ack`

Public: `GET /ops/calendar/{token}.ics`.

Today: `GET /platform/today` carries `ops`: KAI's note, today's rhythm, the
Build items, and due tasks, plus a queue item when Kevin has late tasks.

Storage: `platform_ops_tasks`, `platform_ops_settings`
(`supabase/APPLY-2026-10-16-ops-desk.sql`, service role only). Kill switch:
`OPS_DESK=off` quiets the keeper, the moments and the Today band. Plan and the
feed keep working.
