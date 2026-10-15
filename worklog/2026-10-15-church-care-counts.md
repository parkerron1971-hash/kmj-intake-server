---
title: Prayer & care numbers for the church Operate overview (GET /church/care-counts)
date: 2026-10-15
agent: Claude Code (Claude Opus 5.5)
asked: "add the count-only backend route the church Operate overview's Prayer & care card needs (Kevin approved)"
status: waiting on Kevin
prs: [kmj-intake-server#1453]
migrations: []
left_undone: ["Frontend: wire the Operate overview's Prayer & care card to GET /church/care-counts (solutionist-studio worklog 2026-10-15-church-room-overviews.md)"]
decisions: ["Owner and staff only: business_access('manager') admits owner, admin and manager, the same set as Chief's _CARE_ROLES; member, viewer, accountant collaborators and strangers get business_access's 404", "Numbers only, in a fixed shape: {care: {new, reviewed, closed, prayed, oldest_new_days}, window_days: 90}; the route names its keys so a new status or field cannot leak", "The care half of care_counts is now church_reads.care_request_counts; the route never reads child_checkins; Chief's care_counts output and query order are unchanged", "A failed read is a 503 with a plain sentence, never zeros"]
related: [2026-10-13-church-website-forms.md]
---
The church Operate overview (frontend, first pass waiting on Kevin) has a
"Prayer & care" card: how many prayer requests are new and how long the
oldest has waited. church_reads.care_counts already worked these numbers out
for Chief, but nothing served them to the app. Added
`GET /church/care-counts?business_id=` to church_router.py, next to
first-time-guests, with the same id check (400) and failure rule (503).

Moved the care half of care_counts into `care_request_counts(business_id,
now=None)` so the route reads only ministry_care_requests (status and two
timestamps, no words, names or ids) and never children's check-ins.
care_counts calls it and still makes both reads in the same order: 5,000
random inbox and check-in states, failures included, gave byte-identical
output and queries before and after.

Tests: `__tests__/test_church_care_counts.py` (owner, manager and admin get
the counts; member, viewer, accountant and stranger are refused before any
read; exact shape even when rows carry words or odd statuses; oldest-new
days; 503; 400; mounted before the catch-all; the ownership sweep sees it as
guarded). Read both repos' worklogs first: the 2026-10-13 church forms work
(care rows written by the website) and the frontend's 2026-10-15 overview
entry, which lists this route as its missing piece. No overlap in open PRs.
