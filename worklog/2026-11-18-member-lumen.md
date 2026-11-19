---
title: Member app new look (Lumen) — the switch
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the member app: it "feels like ai built it but not creative designer". He approved the "clean Lumen" mock (version 29, accent level 2) after several rounds. Step one: the switch every Lumen page asks.'
status: in review
prs: ["kmj-intake-server (the switch)"]
migrations: []
left_undone:
  - "The look itself: the shared Lumen stylesheet, the top bar and tab bar, Connect, Home (the foundation PR, next)."
decisions:
  - "MEMBER_LUMEN = off | preview | owner | on, preview by default. preview: only the platform owner, at a church they own (member_asks.platform_church): their Preview as a member session, or their own member sign-in (the record's email or the address they signed in with is PLATFORM_OWNER_EMAIL). owner: every member at that church. on: every church. Anything else is off."
  - "Another church's owner previewing their own app keeps today's look under preview: the first pastor previews this week, and the new look isn't switched on for anyone but the platform owner yet."
  - "member_portal.serve decides once per page, after the session (member_lumen.decide); a page reads it with member_lumen.here(). Anything drawn outside serve (a POST's reply, the sign-in pages) is today's look."
  - "Cost: off, on, and an ordinary member under preview decide with no read. The owner lookup runs only for a preview session or the platform owner's own address (and every page under owner), kept ten minutes per server copy by member_asks."
related: [2026-11-18-member-app-tabs-fast.md, 2026-11-18-member-app-cache.md]
---
`member_lumen.py` holds the switch for the member app's new look. `visible(request, ctx)`
answers for a request and its session (ctx = {"business", "session"}); `serve()` keeps the
answer for the page (`here()`), so the bell, "I'm new here" and the Lumen pages all ask the
same thing. Nothing looks different yet: no page reads it in this PR.

Before building, both repos' worklog/ had nothing on a member app redesign (the 2026-11-18
speed work, the stopwatch and the new-here room are other pieces).
