---
title: The member app's space switcher shows each church's own initials
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23, after the church product pages: "you can fix the LC problem."'
status: done
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions: ["the badge is member_app_ui.initials(church name), the same initials the app uses elsewhere; an empty name shows C"]
related: []
---
The Church row of the member app's space switcher (Church, Youth, Kids; top left on Home for a leader or a parent) carried a hardcoded "LC" badge, Love City's initials, for every church. Found while drawing the Member App product page. `member_spaces.switcher` now uses `member_app_ui.initials(church_name)`: Love City Church is still LC, Grace Fellowship is GF. `test_the_switcher_badge_is_the_churchs_own_initials`.
