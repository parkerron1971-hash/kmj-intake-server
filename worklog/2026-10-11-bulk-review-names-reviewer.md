---
title: "A queue sweep records who approved or dismissed each draft"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "awesome. continue (Kevin, 2026-10-11, after the Layer Two build)"
status: waiting on review
prs: [kmj-intake-server#1389]
migrations: []
left_undone: []
decisions: ["only rows the database actually changed are counted and get reviewed_by; a failed PATCH leaves the row a draft with nobody's name on it", "the single dismiss now says so when its write did not land, instead of reporting success"]
related: [2026-10-11-business-brain.md]
---
Layer Two follow-up. agent_queue.reviewed_by (2026-10-11 migration) was set by the
single approve/dismiss paths but not by Chief's bulk_approve / bulk_dismiss, so a
sweep left every row it touched with nobody's name on it. Both now mark the turn's
person on each row they actually changed. The PR reviewer also caught that a failed
dismiss PATCH was still counted (and would have been marked); both dismiss paths now
check the write.
