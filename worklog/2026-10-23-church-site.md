---
title: The church section of the site, /churches and seven product pages, in Stained Glass Light
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23, after six design rounds on the "Church Front Page" canvas: "I like the design, build this!"'
status: waiting on Kevin (switch-on)
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Switched off (CHURCH_SITE unset). Lanes: features switch on on Thursdays and the week of Oct 26 is the quiet week, so the next switch-on Thursday is Nov 5, unless Kevin sets CHURCH_SITE=on in Railway sooner"
  - "This is a new feature; Kevin said build it, so it takes one of the two Build slots on Plan (his click)"
  - "CHURCHSAVVY_URL: unset until ChurchSavvy has its own site; until then the partner band has no button"
  - "Photos: only the main site's own pastor photo (static/home/p-james.jpg); no Love City photos, per Kevin"
  - "The coaches and consultants pages have not had the same treatment yet"
decisions:
  - "The pages are the approved canvas markup (claude.ai/artifact/AEtgwqRKascF3YW5rNu6Wk, version 14), converted once into church_site/*.html; the templates are now the source, edit them directly"
  - "Nothing that must match checkout is typed in: prices, yearly prices (ANNUAL_MONTHS), AI actions, meter widths, the trial and card wording and the founding seat are tokens filled from the same dials the main site reads; logins, banks and the depth ladder are prose, pinned to the dials by test_the_prose_matches_the_plan_dials"
  - "'no card' appears only while marketing_pages._no_card_trial_offered() is true, the same test the signup door uses"
  - "Switched off, /churches stays the church edition from #1546 and /churches/<page> is handed to the catch-all, so turning it off is a true rollback"
  - "The overview's billing switch is a few lines of plain JS on data attributes; the canvas used a DCLogic component"
related: [2026-10-22-one-brand-three-front-pages.md, 2026-10-22-professional-texting-number-and-logins.md]
---
Kevin wanted the church part of the site to feel like its own place on the same site, as Planning Center's product pages do. The concept, Stained Glass Light: the S mark is already faceted, so each part of church life gets a glass tile and its own colour, and that colour lights its page (the line under the Solutionist strip, a tinted product bar with "In this room" links, the aurora, the floor and the glint word). Chief is the character on every page, doing that room's real job. The devices are drawn in HTML and stand still, Kevin's call after an animated round. The member app is drawn from member_app_ui.py's real design.

Pages: /churches (overview), /churches/people-and-care, /giving, /kids-and-youth, /groups-and-classes, /member-app, /website-and-sermons, /office-and-books. Every product claim was checked against the module behind it before it was drawn (the per-page claim lists are in the design session's agent reports). Examples: shepherding placement rules (church_shepherding), drifting rules (church_shepherd_signals), kids pickup codes and stations (kids_checkin, kids_station), group study drafts (group_study), statements (giving_statements, giving_statement_mail), and giving visible only to owner, admin and accountant (ministry_finance_access). Things that are not built, such as our own livestream relay, money-approval levels and app-store apps, are left out.

`church_site.py` renders a page: it reads the template, removes the ChurchSavvy links while CHURCHSAVVY_URL is unset, and fills the tokens. `public_site.py`: /churches serves the overview when CHURCH_SITE is on, and the new /churches/{slug} route (ahead of the catch-all) serves the seven pages or hands the path to the catch-all. The sitemap lists the seven while on. `.env.example` documents both settings.

Checked:
- 17 tests in `__tests__/test_church_site.py`: tokens, the voice, links and anchors, dials, trial wording, the founding seat, ChurchSavvy, routes on and off, the sitemap, and the billing script under `node --check`.
- The 8 existing test files that touch /churches, the sitemap or the home page: 188 passed.
- The rendered pages screenshotted at 1440 and 390 in headless Chromium.
