---
title: Chief answers "what was the giving today", and a church's lookups are in hand (step 1 of 5)
date: 2026-11-22
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-22: "I signed up Elevation of Grace ... the treasurer ... went to ask Chief what was the giving today, Chief couldn''t find it ... any person that we add in, it seems like Chief doesn''t get the information about the church, the role, responsibilities"; then "yes go ahead with step 1, she''s an admin"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Step 2: a 'who I'm talking with' card for every login, Admins included (an Admin gets no 'Their jobs here' line: chief_duties.jobs_line), from the church's own jobs, not Love City's duty catalog"
  - "Step 2 also: the giving tick (CHURCH_MONEY_TICKS) is still off, so a treasurer who is NOT an Admin is still told money isn't that login's (chief_areas.block)"
  - "Step 3: a church fact sheet Chief always carries (services and times, ministries, leaders, what is on, what is set up), built from the system, in the per-church cached segment"
  - "Step 4: a test that fails when a room on the church menu has no Chief lookup that reads it"
  - "Step 5: a per-role question set run on a made-up church before releases, and a weekly list of 'couldn't find that' replies across churches"
  - "No live Chief eval was run (they bill production): that a church's Chief now picks giving_summary is pinned by which tools are loaded and what the manual says, not by a model run"
  - "The cost of the church edition is an estimate from sizes (about 18,500 more characters, about 6,000 tokens, on a church's cached prefix), not a measured week: re-measure after a week of church use (chief-cost probes read api_usage)"
  - "A scheduled giving_summary always fails (no person in a scheduled run), so 'text me Sunday's giving every week' cannot work yet: closed on purpose, a gap all the same"
  - "'last week' is read as the seven days ending today (the reply states the dates), not the calendar week before"
  - "The church's clock falls back to the owner's profile, then the platform's, when a church has set no timezone (business_marketing.business_tz, as 'Giving this week' does); the reply says 'on the church's clock' and doesn't name the zone"
  - "Not checked: whether a non-owner seat on an ordinary business can read invoices under its own login; if it can't, show_revenue would say $0.00 rather than 'couldn't be read' (show_view invoices has the same question)"
  - "Kevin's call, not made here: whether show_revenue should give an outside agent (the MCP surface) or a scheduled run real figures. Today it gives them none, as before"
decisions:
  - "giving_summary names no giver and asks the giving gate (owner, Admin, accountant, or the giving tick). The total, the count, the funds and the days need no Giving keeper's key: an Admin already reads those without it (GET /giving/{biz}/week and /amounts). HOW it was given (cash, check, online) is not on those pages and Chief's service counts keep it behind the keeper, so it is said only where Giving & money is open to that person; locked, the reply says that part needs the key"
  - "giving_summary is loaded for every business (CORE_READS), not only churches: a nonprofit asks the same question; a plain business is pointed at show_revenue"
  - "A long span is answered small so the tool loop never cuts it to an 'incomplete sample': past 31 days no day-by-day, past 92 no 'days before' (it would read a second year of gifts), at most 12 funds named and the rest counted"
  - "show_revenue returns figures only inside a signed-in turn, and still opens the screen: for a church or nonprofit the month's giving (behind the giving gate, a refusal said as one), for any other business paid invoices less refunds this month and last, cut on the business's own clock, and what is sent and unpaid"
  - "show_revenue's `result` is one plain line a person can read (the app prints an action's result under Chief's reply); the detail and anything written for Chief ride in `figures`"
  - "With nobody signed in (an outside agent, a scheduled run, the standing agent) show_revenue is the screen's action exactly as before: this PR widens no outside surface"
  - "The church edition only ADDS to the standard edition (a test holds it to that); nothing a business's Chief has in full was taken from a church's"
  - "Two cached manuals instead of one: every business shares the standard edition, every church the church edition. The tools follow the prompt they travel with (the edition is read from the short manual's own opening line), never a remembered setting"
  - "Rollback: CHIEF_CHURCH_EDITION=off (a church reads the standard manual again); giving_summary and the show_revenue figures stay"
  - "An independent review ran before the PR. It found no path to giving for a login that shouldn't have it, and three real defects, all fixed here: a year came back cut to a sample; show_revenue's result carried sentences written for Chief onto the screen; the business figures were cut at UTC midnight, ignored refunds and compared timestamps as text"
related: [2026-11-03-chief-lean-brief.md, 2026-11-13-lean-brief-greeting.md, 2026-11-01-giving-close.md, 2026-11-17-chief-office-roster-exec.md]
---
Before building I read both repos' work logs. The short brief's own logs
(11-03, 11-13) are what this builds on; `2026-11-17-chief-office-roster-exec.md`
gave Chief THE OFFICE; the frontend's `2026-11-17-church-briefing-giving.md` is
the "Giving this week" block whose readers and gate this reuses. No open PR
touches `chief_lean_brief.py` or the giving reads.

**What was wrong (read in code on main d9493327, and run offline with the live
setting CHIEF_BRIEF=lean):** on a church's turn 68 of Chief's 143 tools were
deferred, among them the service counts, the Sunday match, bills, whose job
something is, someone's job, the duties, assignments, the serving week and who
is away. The short manual kept what Chief had used in the 60 days to 11-03,
which was mostly business work. Its line for the service counts was the bare
name. The one money read left in hand, `show_revenue`, answered the single word
"navigating". And the service counts answer "no services are set up" for a
church that hasn't added its services, whatever it was given.

**What this PR does:**
- `chief_giving_summary.py`: the `giving_summary` read. One day or a span on the
  church's clock (today, yesterday, the last seven days, this month, last
  month, this year, or from/to): the total, the gifts and givers counted, by
  fund, by how it was given, by day for a short span, and the same number of
  days before. It never asks for a service to be set up, and it says "nothing
  recorded" only when the read came back whole.
- `show_revenue` returns figures (above).
- `chief_lean_brief.py`: a church edition of the short manual (`CHURCH_VERBS`,
  `edition_for`, `edition_of`), and `giving_summary` in the everyday reads. On a
  church's turn 49 tools are deferred instead of 68.
- The manual: "WHAT CAME IN" beside giving by service, and the request map
  routes "what was the giving today" to the lookup.

Not seen: the treasurer's own conversation (the Chrome connection was down);
Kevin said she is an Admin, so she passes the giving gate and was stopped by
the empty lookups, not by a refusal.
