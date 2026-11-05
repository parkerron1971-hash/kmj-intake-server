---
title: The business home has its own address, mysolutionist.app/business
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-04, after the church page became the front door (#1739): "give the business home its own page at /business for now."'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The church overview itself has no link to /business (its strip has the coaches door and sign-in only); the way there is the church product pages' 'All of Solutionist', the coach pages and the sitemap. Add one to the overview's footer if Kevin wants businesses to find it from the front door"
  - "'For now': when the business side gets its own front page (or is retired), /business is the one route and church_site.BUSINESS_PATH the one name to change"
decisions:
  - "/business serves marketing_pages.render_business(): the business home (v3, or v2 with HOME_EDITION=v2) with canonical and og:url /business while church_site.is_home(). Rolled back (HOME_EDITION=v3/v2 or CHURCH_SITE=off) / is the business home again and /business is the same page with canonical /"
  - "church_site.business_path() says where the business home lives right now; the edition pages' 'See every kind of business' uses it"
  - "Church product pages: 'All of Solutionist' goes to /business while / is the church page (it was hidden in #1739); 'Solutionist home' still goes to / (the church page)"
  - "Coach pages: every link to the main site (strip 'Solutionist home', footer 'All of Solutionist' and 'Solutionist home') goes to /business while / is the church page, so a coach isn't dropped on the church page. The came-from-the-main-site script is unchanged"
  - "The sitemap lists /business only while it is the business home's address"
related: [2026-11-04-church-first-home.md]
---
#1739 made the church overview the front door and left the business home (seven kinds of business: barbers, law, contracting, coaches) with no public address. This gives it /business.

Checked: `__tests__/test_church_home.py` (5 new: the address and its canonical both ways, the route sits ahead of the catch-all, the coach pages' links, the sitemap, the edition link); `test_meet_chief.py`, `test_coach_site.py` and `test_brand_voice.py` follow the new links. 570 tests across every file that touches the home, the editions, the church and coach sections and the sitemap pass.
