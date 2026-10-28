---
title: The member app on a computer (Home, Watch, Connect, Coming up, Me)
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28: "the system should allow for logins for elders and pastors etc to have a view on desktop. really everyone should be able to view their account on desktop or mobile phone". Two ways in: the 7 office logins stay for the office; everyone else uses the member app, by role. This is step 3 (a computer layout for member Home and the other tabs); steps 1-2 (the Board tab and the board member''s yes from the member app) are the money-levels session''s'
status: in progress
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Bible, Give, Prayer, My details, Messages, News and the other reading and form pages stay one column (600px), centred: they read best that way"
  - "Youth and Kids Homes (member_spaces) are not laid out for a computer yet"
  - "The Board tab (steps 1-2, the other session) should be built wide from the start: _shell(wide=True) and band(); it gets the sidebar on its own"
decisions:
  - "A page asks for it: _shell(wide=True) puts mb-wide on the body. From 1000px the bar and the page are 1180px wide, and from 1100px they sit beside the 92px tab rail (the Lead tab's own rule, made general)"
  - "member_portal.band(*cols) is one row of blocks side by side. Empty blocks are left out; a row of one block is the full width. On a phone the row and its columns are display:contents, so a phone reads the same blocks in the same order, pixel for pixel (checked on 11 rendered pages at 390px)"
  - "Home: what's on and the four ways in beside Today; the latest message (and, on a computer only, the next two) beside the church's tiles; this week across the width; then the small cards (prayer, install, alerts, Ask). Connect: your groups beside the ones to find. Me: your photo beside your name, you and your giving beside your church life"
  - "Round two (Kevin: 'this design could be even better'): from 1200px the tab bar is a 252px sidebar (member_portal._side: the church's logo, every tab by name, 'Your church' = Coming up and Prayer unless the church made them tabs, the person's FIRST name at the foot opening Me; a group in first-names mode shows no full name on the page). The page sits beside the bar by body padding (92px rail from 1100px, 252px sidebar from 1200px), which replaced the old margin-left rules here and in member_portal_lead"
  - "Watch on a computer: the latest message as a cinema (art beside the title, Watch and the next live; .wt-cine places feat's parts on a grid, its text wrapped in hm-txt), then the series, then every message on a grid (.wt-grid). Coming up: an agenda (oc-row: a date block beside each card, filled when you said yes) beside the month (month_card: days with something on link to their card; two months when the list runs over; today ringed). Rows to swipe become grids on a computer (.hm-col .mb-rail). Hover (mouse only, motion allowed): cards lift, pictures lean in, rows light"
---

On a computer the member app was a phone-width column (600px) beside the tab rail. Five tabs now use the width; everything else is unchanged, and phones see no difference.
