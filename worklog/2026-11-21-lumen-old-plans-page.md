---
title: "Member app new look: the old Plans & devotionals page opens the new Plans tab"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Point the old /my/bible/plans to the new Plans tab in the new look only, so the old look is unchanged."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone: []
decisions:
  - "Under the new look, /my/bible/plans (and ?show=all, ?show=reading) answers 303 to /my/bible?tab=plans: the tab has Continue, the church's devotionals, the topics and the whole-Bible plans. Every older link (the Devotional tab's All, a plan page's way back, a bookmark) lands there."
  - "Two lists stay, because the tab doesn't carry them: ?show=church (the church's every devotional; the tab's 'See all' opens it) and ?show=yours (the devotionals a member started or touched)."
  - "Off, and for anyone the switch doesn't show the new look to, the page is today's, byte for byte (member_lumen.page() decides, as everywhere)."
related: [2026-11-21-lumen-plans-tab.md]
---
The old Plans & devotionals page is the new Plans tab's front door now, in the new look only.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295): same 951, differ 0 against main, both. Reads with the switch on, in four looks: Home harness 1984 on
main, 1948 here over 328 page-looks; Bible harness with the Plans pages 1274 on main, 1221 here over 248: the only pages
that moved are /my/bible/plans, ?show=all and ?show=reading, which now open the tab (its reads kept), and /my and
/my/directory (500 in that harness) with their 30-second feed cache. Member suites with the Bible and devotional ones:
1715 passed.
