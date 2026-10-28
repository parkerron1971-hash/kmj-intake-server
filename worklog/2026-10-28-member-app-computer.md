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
  - "The Board tab (steps 1-2, the other session) should be built wide from the start: _shell(wide=True) and band()"
decisions:
  - "A page asks for it: _shell(wide=True) puts mb-wide on the body. From 1000px the bar and the page are 1180px wide, and from 1100px they sit beside the 92px tab rail (the Lead tab's own rule, made general)"
  - "member_portal.band(*cols) is one row of blocks side by side. Empty blocks are left out; a row of one block is the full width. On a phone the row and its columns are display:contents, so a phone reads the same blocks in the same order, pixel for pixel (checked on 11 rendered pages at 390px)"
  - "Home: what's on and the four ways in beside Today; the latest message beside the church's tiles; this week; then the small cards (prayer, install, alerts, Ask). Watch: the latest message beside the series and every message. Connect: your groups beside the ones to find. Coming up: the cards three across (hm-grid). Me: you and your giving beside your church life"
---

On a computer the member app was a phone-width column (600px) beside the tab rail. Five tabs now use the width; everything else is unchanged, and phones see no difference.
