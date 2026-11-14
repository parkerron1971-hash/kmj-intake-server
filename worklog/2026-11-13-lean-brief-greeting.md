---
title: The launch greeting asks one question on both briefs, so the short brief (CHIEF_BRIEF=lean) matches the full one on the turn eval
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-13: "Let''s make the build to test the block 45,000 tokens so it could save money."'
status: shipped, switch still off
prs: [kmj-intake-server#PRNUM]
migrations: []
left_undone:
  - "Turning the short brief on is Kevin's call: CHIEF_BRIEF=lean on the kmj-intake-server web service, on a Thursday. Then watch `railway logs --filter \"cache rewrite\"` (a cold message should write ~65-70k tokens, not ~120k)"
  - "Found, not fixed (answer check, PR #1832's area): on some greeting turns the answer check runs three times and its repair cuts the reply to a sentence or two ('Good morning, Dre Carter. Welcome to Fade Street Barbers.'), or leaves a stray fragment ('three.', 'Separately,  Your call.'). It happens on both briefs; on the branch it was the short brief's only greeting miss in 20"
  - "Found, not fixed: on the short brief the barber greeting says 'Dre Carter' most runs (the turn tail says FIRST NAME only); the full brief says 'Dre' most runs. The eval doesn't check names"
  - "The FIRST WEEK (days 2-7) greeting has the same 'ONE question, then one sentence for the sit-down' shape and was left as it is: no eval row measures it"
  - "create_session and nb_barber_hours still fail on both briefs every run (not looked at)"
decisions:
  - "The fix is in the launch greeting's own steps (chief_prompt.py, the uncached turn tail), so it changes both briefs the same way and leaves the manual, the tools and every cached segment byte for byte as they were. This is a deliberate full-brief prompt change: two lines of the LAUNCH GREETING clause"
  - "Step 2: the setup question is the greeting's ONLY question mark, and the 'how' line's choices go inside it. Step 3: the sit-down sentence is a STATEMENT, never 'Which would you rather?'"
  - "No manual section moved into the short brief: the short and full prompts for nb_ministry_greeting differ only in the manual and the tools (per-business block, snapshot and tail compare equal), and nothing the short manual drops is about greetings or questions"
related: [2026-11-03-chief-lean-brief.md]
---
The short brief lost to the full brief on one check: `reply:one_question`
on the day-one launch greetings. The prompt was not missing anything: the
launch greeting's steps are in the turn tail, which both briefs share. Full
replies showed two ways a greeting got a second question mark, on BOTH
briefs. The short brief made the first one far more often:

- the sit-down sentence asked as a choice: "We can do it now, or start with
  setup and do it by day three. Which would you rather?" (short brief 4 of
  5 ministry runs; full brief 2 of 5 barber runs);
- the setup question's options asked on their own: "where do your clients
  live today? Your phone contacts, a spreadsheet, a booking app?" (full
  brief 2 of 5 barber runs).

Steps 2 and 3 of the LAUNCH GREETING now name both. A test pins the
wording on both briefs, and was sabotage-checked against main's text.

Results (live, `chief_turn_eval --live`, CI-shaped env, every read stubbed):

| | main, full brief | main, short brief | branch, full brief | branch, short brief |
|---|---|---|---|---|
| turn eval | 201/204 (1 run) | 196, 199 | 201/204 | 200, 200 |
| nb_ministry_greeting passes | 9 of 11 | 1 of 12 | 10 of 10 | 10 of 10 |
| nb_barber_greeting passes | 6 of 11 | 6 of 11 | 10 of 10 | 9 of 10 |

On the branch, every turn-eval run fails only create_session and
nb_barber_hours (both briefs, every run, as before), and no run takes a
must_not verb. The short brief's one greeting miss in 20 had no question
mark at all: the answer check cut the reply (see left_undone).

Live spend: $6.70 (baselines $0.77, greeting rows $1.36, three turn-eval
runs $4.58). Saving if the short brief is switched on, from api_usage for
the 30 days to 2026-11-13: 627 main Chief calls cost $45.88; the 52 cold
ones (8.3%, ~128k tokens written, 50.1c each) cost $25.15 in cache writes,
and cache reads on every call $6.08. A brief at 54-58% of the size saves
~$13-14 every 30 days at today's volume (~$160-175 a year), about 22c per
cold call, and grows with use.
