---
title: "Member app new look: a church devotional's page as Kevin's Plans design draws it, and Start over"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Plans, step 2: a plan's page that works for church devotionals, topic plans and reading plans: the cover header, about, Continue day N or Start, Start over, and every day with its check state. The reminder and 'read with' rows come with the group-and-reminder step."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Remind me and who you read with: they need a table for the member's choice, so they come with the group-and-reminder step (its migration file first)."
  - "The devotional's daily practices ('Every day') aren't on the page: the design's page doesn't draw them. The day still has its checklist."
decisions:
  - "A church devotional's page under the new look is member_lumen_plans.render_devotional, on the reads today's page already makes (the devotional, the member's start, their days): no new read. Off, today's page byte for byte."
  - "The cover: the devotional's picture spot (or a church photo named for it) drawn in the church's colour, else a cover made of that colour; '<church> · <kind>' over the serif title, how many days and about how long a day takes (the days' own reading times, averaged)."
  - "What it offers follows where the member is (member_portal_devotionals.state): Start (one started on your own day), when the church starts it, Continue day N (today's day, or the first open day not read), You finished it with Read it again. Every day is listed with its scripture, today marked, a day not open yet saying when it opens; open days link to the day."
  - "Start over is a quiet button that opens to say what it does, then the form that does it (no script): a reading or topic plan runs again from today (its old ticks stay with the old start); a devotional's days marked read are cleared, its journal and checklist kept, and one started on the member's own day starts again today. It shows only where there is something to start over, never in the owner's preview."
  - "POST /my/bible/plans/over: the member's session, same-site (member_portal._same_origin), the member-action rate limit, only the member's own rows (member_plan_starts upsert, a devotional_progress PATCH filtered to their business, contact and devotional), the plans version stamped so Plans reads afresh."
related: [2026-11-21-lumen-plans-tab.md]
---
A church devotional's page in the new look, and Start over on every plan's page.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295): same 951, differ 0 against main, both. Reads with the switch on, per page and table, in four
looks: Home harness 1984 / 1984 over 328 page-looks; Bible harness with the Plans pages 1277 on main, 1274 here
over 248 page-looks: the devotional pages read exactly what they read on main; the only pages that moved are /my and
/my/directory (both 500 in that harness), whose 30-second feed cache flips between looks on either side. Member
suites with the Bible and devotional ones: 1676 passed. Shots before and after (Chromium and WebKit, light and dark,
390x844 @2x, Love City's Consecrate Your Focus seeded from the design page) in the session scratchpad's
plans-build-shots/pr2/, Start over opened in after-*-devotional-over.
