---
title: The church section is on and one click from anywhere on mysolutionist.app
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23, after #1565 merged switched off: "i should be able to get to churches page and any other page from from mysolutionist.app. I will get it''s own domain name it the future as well"'
status: done
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Its own domain: when Kevin has one, add it in Cloudflare for SaaS (custom_domain_cutover_facts) and teach church_site to serve the overview at that domain's / and the pages at /giving etc. (the templates link /churches/..., so that is a path-prefix change in church_site.render plus one host check in public_site)"
  - "The Build slot on Plan is still Kevin's click"
decisions:
  - "CHURCH_SITE is now on when unset; CHURCH_SITE=off is the rollback (the #1546 church edition at /churches, the product paths to the catch-all). Kevin's message asks for the pages to be reachable now, ahead of the Lanes Thursday (Nov 5)"
  - "Churches and Coaches lead the home page's top menu and its phone menu, and sit after What it is in the menu every other marketing page shares (marketing_pages)"
  - "The church header's Products link is a menu of all eight pages, each with its colour, the current page marked; a details element, so it works without script"
related: [2026-10-23-church-site.md]
---
After #1565 merged with the church section switched off, Kevin wanted to reach the churches page and the rest from mysolutionist.app. Three changes:
- The section is on by default.
- The main site's menus link to Churches and Coaches.
- Every church page's Products link opens a menu of all eight pages.

Checked:
- `__tests__/test_church_site.py`, 20 tests: on unless off, the menu holds all eight pages with the current one marked, and the home and shell menus link /churches.
- 17 test files touching the menus and pages: 390 passed.
- Screenshots of the open menu and the home menu at 1440.
