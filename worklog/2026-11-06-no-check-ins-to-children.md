---
title: No automated check-in goes to a church's children
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'yes fix both'
status: shipped
prs: [kmj-intake-server#1765]
migrations: []
---

The Renee run on the test church found 18 "Checking in" drafts for about 20
people, one of them a 10-year-old: "I've been thinking about you". It sent
nothing only because the child had no email on file. Both drafters now skip a
church's children: the nurture sweep and the weekly briefing. A child is anyone
on a family as a child, under 18 by birthdate, or tagged so, and a failed read
of who is a child stops the check-ins. A church also keeps at most five
check-ins waiting, and someone with no interaction on record no longer counts
as gone quiet, which is what filled Approvals after an import. A pastor who
asks Chief for a note still gets one. Other businesses' sweeps are unchanged.
