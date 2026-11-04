---
title: mysolutionist.app opens on the church page (church-first home, Sunday Light hero)
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-04, after the church-first mock rounds: "this design will work for now. build it and merge it."'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The business home (seven kinds of business, barbers, law, contracting) is only reachable with HOME_EDITION=v3 now; the product pages' 'All of Solutionist' link is hidden while / is the church page. If Kevin wants that page kept public, give it a path (e.g. /business) and point the links there"
  - "The coaches pages' 'Solutionist home' link now lands on the church page"
  - "The move's steps 5 and 6 ('Chief drafts a note asking each monthly giver to set their gift up again', 'We're with you for your first Sunday') are service promises Kevin has not confirmed in words; they were flagged in every mock round"
  - "Lanes say features switch on on Thursdays; Kevin asked for this merged on a Wednesday, so it is live on merge. HOME_EDITION=v3 is the rollback"
decisions:
  - "church_site.is_home(): / serves the church overview unless HOME_EDITION names a business home (v3, v2) or CHURCH_SITE is off. marketing_pages.render_home() is untouched, so the business home and its tests stand as they were"
  - "While it is the home, the overview's canonical address is / (one address for search); /churches serves the same page"
  - "The page is the approved mock (claude.ai/artifact/CgBg3zVjHSQ2EFgaZyHdUy, version 8) and only it: no mock bar, what's-new tags, letter, earlier heroes or switches. Built by the session's scratchpad port_live.py from the live template plus the mock's parts; the new parts' style and script sit in church_site/overview.css and overview.js, inlined as {{OVERVIEW_CSS}} / {{OVERVIEW_JS}}"
  - "Numbers stay the dials': the size picker's plans, prices, logins, texts, messages to Chief, clips and Multi-site price are JSON written by church_site._picker_data(); the move's offer is _move_tokens() from church_offer(); the hero's 'priced by the size of your Sunday' and the picker are sections that show only while PLAN_CHURCH_OFFERED is on"
  - "No founder by name and no Love City on the page (Kevin: Love City is going through changes; owners don't put themselves up front). The sample church is Grace Fellowship"
  - "'Office' only as a product name (Office and Books, office logins); the pitch is grow, belong, serve"
related: [2026-10-23-church-site.md, 2026-10-23-church-site-on-and-linked.md, 2026-11-03-church-site-pricing-by-size.md, 2026-11-03-church-plans-by-size.md]
---
Before building I read both repos' `worklog/`: the church site (10-23), its pricing by size (11-03) and the coach site touch this code; nothing in flight overlaps, and no open PR touches church_site or the home route.

The overview now runs: the strip (for churches, coaches door, sign in) → the Sunday Light hero, "Many pieces. One light." (a faded stained-glass window at the right edge, sunlight cast from its own shape, the pastor's tablet, a member's phone, a printed kids label) → the reel → Why Solutionist exists (Grow. Belong. Serve., the mission lit word by word, the vision, the four parts feeding one rose) → a week at a sample church (Sunday is one day; ministry is all seven) → Meet Chief and the rest of the page as it was → moving day is on us → pricing with the size picker → the partner band → the closing ("No one unknown. No gift unused. No church too small.").

Checked: `__tests__/test_church_home.py` (14 new: the front door and its rollback, canonical, links, the approved design and none of the mock's furniture, picker and move from the dials, the script parses); `test_church_site.py` and `test_meet_chief.py` updated for the home page; 1,579+ tests across every file that touches the public site, the church pages or the home pass. Rendered with the plans by size on at 1440, 1024 and 390 wide: no page errors, no sideways scroll.
