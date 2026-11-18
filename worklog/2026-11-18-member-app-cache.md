---
title: Member app stops repeating itself — the church, the member and the tab bar kept a little while
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: '"the members app move slow when send messages in chat, switching from one tab to another… what is the problem and how can that be sped up?" … "yes build all four" (Kevin, 2026-11-18). Fix two of four, after the stopwatch (2026-11-18-member-app-stopwatch.md).'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "A change the owner makes elsewhere (taking the site offline, the theme, the custom domain, giving settings) shows on the member app within a minute: only the member app switch (PATCH /member-portal/{id}) forgets the church at once, and only on the server copy that saved it."
  - "A member's spaces (space_leaders: who reaches the Youth and Kids rooms) are still read on every page, on purpose: a leader taken off must lose those rooms at once."
  - "Signed-in pages weren't timed live (no member session can be made for a real member); the after numbers for them come from the stopwatch's [member] lines and the Database card."
decisions:
  - "The church on an address: kept 60 s per address (the PostgREST filter is the key), only when a row with its church came back; a failed read and 'no such site' are read again. Offline and a sample church's preview cookie are still checked on every request"
  - "A signed-in member's record (contacts_for_ident): kept 30 s per (church, email or phone). A removed member, or one whose email changed, or one whose address another record now shares, keeps their session at most 30 s. The signature, the church's sign-out epoch and the one-person rule still run on every request. A failed read is never kept. The owner's preview never uses it"
  - "Why 30 s, not 60: tab taps come seconds apart, so 30 s keeps nearly all of the gain; a member taken off the list is out within half a minute"
  - "The Lead and Board tabs: kept 60 s per member. They only draw the tab bar; the Lead and Board pages read who may see what on their own. A 'no' is kept only when the role and group reads both answered; a Board read that fails is never kept"
  - "'Sign everyone out' and switching the member app off reach every server copy within a minute (the church's settings are kept that long); on the copy that saved it, at once"
  - "A hit is a fresh copy (kept as JSON text and read back, ~4x faster than deepcopy for a large settings blob), so no request can change what the next one sees. At most 2000 entries a kind"
  - "MEMBER_CACHE=off reads everything every time, as before"
related: [2026-11-18-member-app-stopwatch.md, 2026-10-20-member-app-speed.md, 2026-10-20-member-app-lookups-together.md]
---
Every member page and POST started with the same reads, one after another: the church on
this address (about 140 ms on lovecityc.com, measured by the stopwatch the day it went
live: the church's settings ride along), the signed-in member's record, then (at once with
the member's spaces) the Lead tab's chain (roles and groups, then tasks, then serving
parts) and the Board tab. `member_cache.py` keeps those answers per server copy, briefly;
`member_portal._site_row`, `_people_for` and `_leads`, and `member_portal_board.on_board`
use it.

Tests: `__tests__/test_member_cache.py`. A signed-in member's second page skips the
church, record, roles and groups reads: with every other read faked empty, 15 reads before
the page's own became 4. Two tests in `test_member_portal.py` now say "within 30 s" where
they said "at once".
