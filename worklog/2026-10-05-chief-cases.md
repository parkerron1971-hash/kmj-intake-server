---
title: Chief opens a case for a problem it diagnosed, forecasts the fix, and checks it
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: "Make the changes ... I have worked with codex on fixing chief responses ... make sure not to mess those things up"
status: in progress
prs: []
migrations: [supabase/APPLY-2026-10-05-chief-cases.sql (pending)]
left_undone: ["cases as a source in Codex's responsibility report (chief_responsibilities.py) — separate change", "Home card for open cases (frontend)"]
decisions: ["a case grants no permission and starts no work between conversations", "results are what the records show, never a causal claim (same rule as Codex's responsibilities)", "the forecast must beat the number before, read from the same length of time just before the window", "Codex's conversation rules already hold the one-question and records-vs-synthesis rules; nothing duplicated"]
related: [2026-10-03-chief-follow-through.md]
---
Solutionist Intelligence, step one: a generic AI gives advice and forgets it;
Chief now follows a diagnosed problem to a result. `open_case` records the
symptom, cause, evidence, fix and a forecast (measure, number before, number
expected, check day); a six-hourly tick reads the records on that day, records
met / partly / not_met / unmeasured, and tells the owner once. Open cases and
last week's results ride in Chief's context and in the answer check's records.
See docs/CHIEF_CASES.md. Codex's responsibilities, conversation rules and
answer-check logic are unchanged; the answer check only gained `open_cases`
as a record source.
