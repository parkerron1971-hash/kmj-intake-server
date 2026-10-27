---
title: Member app tab editor — the church picks its bar (server)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin approved the "Church Menu Upgrade" design (artifact J2Z5yQYQ9GLXN66Cy7c1sM, step 4 "Member-app tab editor"); 2026-10-27: "build it merge it"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the editor, next)]
migrations: []
left_undone:
  - "Classes, Live, Reading plan and Check-in are not offered: each is a page only some churches or some days have, so a tab could lead nowhere"
  - "The Give page's own bar (render_give) still has no Serve tab for a leader, as before"
decisions:
  - "Lane: Build, under 'Love City leaves Subsplash (M-1)'. Parity with Subsplash's Apps > Mobile App > Manage tabs"
  - "Stored in businesses.settings.member_portal.tabs (a list of keys) through the existing owner-gated PATCH /member-portal/{biz}; no migration"
  - "Nothing saved is today's bar exactly (Home, Watch, Bible, Give, Connect), checked byte for byte; saving today's bar or null removes the key so it keeps following ours"
  - "Home is always first, Give is always there and can move, five at most (the phone bar fits five plus a leader's Serve tab, still last)"
  - "Offered: Watch, Bible, Connect (on today), Events, News, Prayer, Messages. Messages stays out of the bar while member messaging is off"
  - "Unknown keys are dropped, a non-list is a 400, and only the owner saves (the route's _require_owner)"
  - "Youth and Kids keep their own bars"
related: [2026-10-26-serve-tab.md]
---
The church office can now choose which tabs its member app's bar shows and in
what order (`member_app_ui.church_tabs`, `clean_tab_keys`, `tab_choices`). The
config route returns `tabs`, `tab_choices` (label, hint, locked, ready),
`tab_limit` and `tabs_default`, and the PATCH takes `tabs`.

Events, Prayer and News pages now name themselves (`tab="events"` etc.) and map
to Home in `TAB_OF`, so with nothing saved they light Home as before. Made into
tabs, they light themselves, drop their "Home" back link, and Messages as a tab
hides the chat button at the top. The app's switch-on is in the frontend editor
(platform owner only until Thursday 2026-10-29); the server always honours a
saved bar, and only the owner can save one.

Tests: `__tests__/test_member_app_tabs.py`.
