---
title: The answer check sees the site and who is talking, and reads a saved record as a fact (fewer repairs)
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-13: "yes do all three credit fixes" (this one: make the answer check cheaper rather than charge churches more)'
status: waiting on Kevin (draft PR; the parent session reviews the bench numbers before it is marked ready)
prs: [kmj-intake-server (this PR, draft)]
migrations: []
left_undone:
  - "Church room strips: room_orientation has no entry for the church rooms (worship-setup, Sundays, services), so THIS ROOM says only 'Operate' and Chief's first-visit line describes the room from elsewhere; the check sent 4 of the week's 26 repairs there. Fix is product copy for those rooms, checked against the app, not a check rule"
  - "The repair sends ~22,900 uncached tokens (4.78c a call, $3.92 in 30 days, most of the repair-path spend). Letting it read the review's cached records would cut it to about 0.8c (~$3/month at today's volume); it needs one system prompt shared by review and repair, a quality risk to bench first. Not built"
  - "The first reviews are $11.01 of $15.40 a month, mostly cache writes on cold checks (11,035 written tokens on a passing check). A 1-hour TTL was already ruled out; nothing else tried"
  - "Re-measure after deploy: railway logs per deployment (7-day retention), the new 'reply review cleanup gave up: ...' lines split the gap-cleanup failures (10 of the week's 26 repairs) by cause"
decisions:
  - "No prompt, model or lane change: the review gets the evidence Chief already had (the site record, who is talking), and one claim class the prompt already calls a fact is checked as a fact"
  - "context:site only when a site row with a slug is on file; a missing row may be a failed read and never means 'no site'"
  - "A saved-record claim filed as an action is a fact only with no first person, no completion claim and no delivery word (sent, out, inbox, calendar, site, page...); it still needs a record and a quote"
related: [2026-11-13-ai-credits-pricing-check.md, 2026-10-18-review-possessive-names.md, 2026-10-22-chief-early-check-rows.md]
---
Measured first (read-only): in the 30 days to 2026-11-13 the Sonnet answer
check cost $16.29; by turn, 189 of 263 checked turns passed in one review and
71 (27%) went to the repair path (repair 4.78c + re-check 1.40c, so one avoided
repair saves about 6.2c). Railway's chief.truth lines (7 days of logs, 88
checks, 26 repairs) named the causes: a gap the cleanup could not cut around
14, an action claim with no receipt 7, a figure 5. The check's own wrong
rejections among them: the site record and the speaker were never review
evidence, and saved-record sentences filed as actions.

`chief_truth.py`: `context:site` (only with a site row on file) and
`context:login` (office logins) join the review's evidence; `is_record_state`
reads a saved-record claim filed as an action as a fact, which still needs a
record and a quote; the gap cleanup logs why it gives up.
`__tests__/test_chief_review_cheaper_checks.py` (34; 8 behaviour tests fail
on main, the 8 guards pass on both).

Bench (`C:\Users\kmccl\Projects\review-bench\`, uncommitted): the 25 advice
answers, 9 new production-shaped rows on the fictional businesses, 124 planted
falsehoods, the factual eval's 28 drafts. The advice and factual review input
is byte-identical on both sides; all 207 of main's recorded reviews there get
the same verdict under the branch's code. Main vs branch: withheld 4/34 vs
4/34; withheld or the true answer replaced/cut 8/34 vs 4/34 (3x repeat of the
9 rows: 10/27 vs 2/27); repair path 8/34 vs 7/34 (repeat 8/27 vs 5/27); plants
through 0/124 vs 0/124; factual 14/14 and 14/14 on both. Live spend about
$5.02. Estimated saving at today's volume is small, about $0.20-0.80 a month
(1 to 5 of the week's 26 repairs); the bigger levers are listed above.
