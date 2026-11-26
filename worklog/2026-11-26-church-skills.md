---
title: Chief can follow written steps for three church giving jobs, behind a switch that starts off
date: 2026-11-26
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-26, on the "Church Skills for Chief" proposal and my recommendation (the fact sheet first, then two giving skills behind a switch that starts off, at Love City first): "build in the recommended order", then "ok sounds good"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "OFF everywhere (CHIEF_CHURCH_SKILLS unset). 'owner' turns it on for the platform owner's own church (Love City); 'on' for every church. Nothing was switched on"
  - "The with/without comparison that decides whether a skill stays (the same church questions with and without its steps) was not run: it bills production. Its cost is to be stated to Kevin first"
  - "'Fill a serving gap' is not a skill: Chief can read open spots (serving_week, event_volunteers) but has no action that asks someone to cover one. A skill for it would teach Chief to promise what it can't do"
  - "The church's own way (a church's own version of a job, owner-approved) is not built"
  - "A login that only sees giving (the giving tick, can_work off) gets no steps for the Sunday count, since it can't record. Steps for a read-only part of a job would be a separate skill"
  - "The bank match (giving-bank-match) is for the owner and Admins: its actions aren't in a giving tick's verbs (chief_areas.TICK_VERBS), so a treasurer on a tick gets the count's steps but not the match's"
  - "No saving is claimed: the steps add a little to the turns that use them. The short manual (CHIEF_BRIEF=lean) already keeps rare jobs' how-to out of the opening brief"
decisions:
  - "church_skills/*.md, one job a file, in build_skills' shape (frontmatter, then the steps): name, use_when, triggers, actions. Three, all on actions that are fully built: sunday-giving-count (giving_counts, record_service_gifts, undo_service_gifts), giving-bank-match (giving_deposits, match_giving_deposits, unmatch_giving_deposits) and year-end-giving-statements (giving_statements_run, giving_statement). The Sunday giving job was split in two after the review, so the person who counts gets its steps. Their steps were written against the handlers and the manual's own lines"
  - "Kevin's cost idea: only the contents (one line a job) ride every turn, in the per-church segment, for a church with skills on. The per-church segment and not the global one, so while skills are on for one church the shared manual stays the same for every business"
  - "The server matches the message (whole words, as build_skills does) and checks the login's key BEFORE handing over a job's steps: every action the job names must pass chief_areas.refusal for that login. No key, nothing loaded. One job a turn"
  - "When the words miss, Chief can ask for a job's steps by name through the short manual's own lookup (action_guide), with the same key check"
  - "It only adds. Nothing moves out of the manual (docs/PROMPT_EXTRACTION_RULING.md: an earlier keyword-loaded slimming was closed because a missed match meant nothing worked). The key check saves words, not safety: the handlers still check who may do what"
  - "The steps are handed to the answer check as conversation, never as a record: they say what to do, not what is true"
  - "After an independent review (safe to merge off, not to switch on). (1) The giving keeper never got the count's steps, because the skill also listed the bank-match actions a giving tick can't use: the match is now its own skill. (2) 'on' would have handed every church jobs whose features (GIVING_SERVICES, GIVING_DEPOSITS) are on only at the platform's church: a job now names the features it needs, and a church where one is off gets neither its steps nor its line in the contents. (3) The count's step said to read back totals record_service_gifts doesn't return: it now says to look again with giving_counts. (4) The statements' year disagreed with the handler from July: the step now passes the year every time. (5) It told churches to put givers on unattributed gifts, which are mostly plate cash and gifts given anonymously on purpose: now only where the giver is actually known. (6) The words were too broad (head count, count me in, statement of faith, the bank called...): they are phrases now, a plural no longer counts twice, and a test pins fifteen ordinary sentences that load nothing. (7) Only with the short manual, since the contents point at its lookup; the reads (who owns the church, which features are on) run off the event loop, once a turn"
  - "Tests: every skill parses, names only Chief's own actions, and its steps mention no action it doesn't list (or the key check could be passed by a step that uses something else)"
related: [2026-11-26-church-fact-sheet.md]
---
Read both repos' work logs first; nothing open touches Chief's turn tail or the
short manual's lookup.

`church_skills.py` and `church_skills/` are new; `chief_of_staff.chief_chat` hands
a matching job's steps to the turn's tail and the contents to
`chief_prompt._build_system_prompt`; `chief_lean_brief.tool_result` answers a job's
name with its steps. Tests: `__tests__/test_church_skills.py`.
