---
title: The church home's Member App and Office sections fold into the rooms tour
date: 2026-11-09
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-09, on the 11-08 left-undone list (the Member App and Office sections repeat the tour): "ok make the changes for the left for later stuff."'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "About 130 one-line style rules in church_site/overview.html were already unused on main (the old bento, ribbon, kiosk and member-app mocks from earlier editions). Only the 46 this fold orphaned were removed, plus two older office-mock rules (.oa-row, .oa-pill) the review caught; the rest are a separate tidy-up"
  - "Lanes say features switch on on Thursdays; this is a page change Kevin asked for on a Monday, live on merge like #1739 and #1769. Rollback for the home: HOME_EDITION=v3 or CHURCH_SITE=off"
decisions:
  - "The two sections are gone from the overview; the tour's Member app and Office rooms carry each room's headline, three facts, screens and link to its page, as the other rooms do"
  - "#app and #office still land. The header's Member app link and every room page's /churches#app link go to anchors at the top of the tour, and the tour opens that room as chosen (no walking on) and scrolls itself into view, because the browser's own jump landed short on phones while the page above still loaded"
  - "Page length at 1440: 14.7 to 12.5 screens; at 390: 27.6 to 23.2. The page now runs: hero, mission, week, Chief, the rooms tour, why one system, moving over, pricing, ChurchSavvy, start"
related: [2026-11-08-home-rooms-and-week.md]
---
On 11-08 the rooms tour went live, and the Member App and Office sections lower down the church home repeated two of its rooms. They're folded in: the sections and the style only they used are removed, and the links that pointed at them open those rooms in the tour.

test_church_home's test_the_member_app_and_the_office_live_in_the_tour pins it: the sections are gone, both anchors sit in the tour, the menu and the room pages still link there, and the tour handles both. Checked in a browser at 1440 and 390: /#app opens Member app and /#office opens Office with the tour at the top of the screen, no script errors, no sideways scroll.
